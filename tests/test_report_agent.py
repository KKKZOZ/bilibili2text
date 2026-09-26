import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.job_store import JobCapacityError, JobManager, JobPatch
from backend.report_service import generate_stored_report

from b2t.cancellation import CancellationToken, PipelineCancelled
from b2t.config import SummarizeModelProfile, create_app_config
from b2t.report.generate import finish_html, source_units
from b2t.report.options import ReportOptions
from b2t.report.pi import child_environment, consume, model_config, run_pi
from b2t.storage import ArtifactKind, StoredArtifact
from b2t.storage.local import LocalStorageBackend


def profile(key="user-a", url="https://a.example/v1"):
    return SummarizeModelProfile(
        provider="openai_compatible", model="model-a", api_key=key, api_base=url
    )


def test_request_credentials_do_not_mutate_process_or_persist_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    before = dict(os.environ)
    a, b = child_environment("user-a"), child_environment("user-b")
    assert a["B2T_REPORT_API_KEY"] == "user-a"
    assert b["B2T_REPORT_API_KEY"] == "user-b"
    assert "OPENAI_API_KEY" not in a
    assert dict(os.environ) == before
    config = model_config(profile())
    assert config["providers"]["b2t-user"]["apiKey"] == "$B2T_REPORT_API_KEY"
    assert "user-a" not in json.dumps(config)
    assert config["providers"]["b2t-user"]["baseUrl"] == "https://a.example/v1"


def test_transcript_timing_preserves_units_and_unknown_boundaries():
    rows = source_units(
        "fallback",
        {
            "segments": [
                {"start": 1.5, "end": 2.75, "text": "完整条件"},
                {"start": 3, "text": "没有结束时间"},
            ]
        },
    )
    assert rows[0]["start_ms"] == 1500 and rows[0]["end_ms"] == 2750
    assert rows[1]["start_ms"] is None and rows[1]["end_ms"] is None
    assert source_units("第一段\n第二段")[1]["id"] == "u000002"


def test_report_requires_valid_bindings_and_applies_csp():
    raw = '<html><head></head><body><section data-source-units="u000001">内容</section></body></html>'
    result = finish_html(raw, {"u000001"}, {"mode": "brief"})
    assert "Content-Security-Policy" in result
    assert "b2t-report-settings" in result
    with pytest.raises(ValueError, match="来源"):
        finish_html(raw, {"u000002"}, {})
    with pytest.raises(ValueError, match="占位符"):
        finish_html(raw.replace("内容", "{{SOURCES}}"), {"u000001"}, {})


class Writer:
    def write(self, value):
        self.value = value

    async def drain(self):
        pass


def test_rpc_waits_past_agent_end_and_checks_final_stop_reason():
    async def scenario(reason):
        reader = asyncio.StreamReader()
        process = SimpleNamespace(stdin=Writer(), stdout=reader)
        task = asyncio.create_task(consume(process, "report", None))
        reader.feed_data(b'{"type":"agent_end"}\n')
        await asyncio.sleep(0.01)
        assert not task.done()
        for event in [
            {
                "type": "message_end",
                "message": {"role": "assistant", "stopReason": reason},
            },
            {"type": "agent_settled"},
        ]:
            reader.feed_data((json.dumps(event) + "\n").encode())
        await task

    asyncio.run(scenario("stop"))
    with pytest.raises(RuntimeError, match="未正常完成"):
        asyncio.run(scenario("error"))


def test_rpc_cancellation_interrupts_silent_provider():
    async def scenario():
        token = CancellationToken()
        process = SimpleNamespace(stdin=Writer(), stdout=asyncio.StreamReader())
        task = asyncio.create_task(consume(process, "report", token))
        await asyncio.sleep(0.01)
        token.cancel()
        with pytest.raises(PipelineCancelled):
            await asyncio.wait_for(task, 1)

    asyncio.run(scenario())


def test_report_pending_after_transcription_remains_cancellable_and_retained():
    manager = JobManager(limit=1)
    job = manager.create(
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
        report_options={"mode": "brief"},
    )
    job_id = job["job_id"]
    manager.patch(job_id, JobPatch(status="succeeded"))
    assert manager.list_active()[0]["job_id"] == job_id
    with pytest.raises(JobCapacityError):
        manager.create(
            skip_summary=True,
            summary_preset=None,
            summary_profile=None,
            auto_generate_fancy_html=False,
        )
    assert manager.cancel(job_id) == (True, "cancelled")
    assert manager.cancellation_token(job_id).is_cancelled()


def test_local_report_survives_temporary_workspace_cleanup(tmp_path, monkeypatch):
    source = tmp_path / "BV123_transcript.md"
    source.write_text("完整原文", encoding="utf-8")
    artifact = StoredArtifact(source.name, str(source), "local", ArtifactKind.MARKDOWN)

    def fake_generate(path, config, **kwargs):
        assert path.read_text() == "完整原文"
        result = path.with_suffix(".html")
        result.write_text("<html>report</html>")
        return result

    monkeypatch.setattr("backend.report_service.generate_report", fake_generate)
    stored = generate_stored_report(
        source_artifact=artifact,
        storage_backend=LocalStorageBackend(),
        config=create_app_config(),
    )
    assert Path(stored.storage_key).read_text() == "<html>report</html>"
    assert stored.derived_from == str(source)
    assert stored.filename.endswith("_summary_fancy.html")


def test_local_pi_transport_with_fake_executable(tmp_path, monkeypatch):
    """Exercise real pipes and staging without network or paid model calls."""
    executable = tmp_path / "pi"
    executable.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
config = pathlib.Path(os.environ['PI_CODING_AGENT_DIR'])
assert json.loads((config / 'models.json').read_text())['providers']['b2t-user']['apiKey'] == '$B2T_REPORT_API_KEY'
assert os.environ['B2T_REPORT_API_KEY'] == 'user-a'
assert 'OPENAI_API_KEY' not in os.environ
assert not pathlib.Path('skill/modes/standard.md').exists()
json.loads(sys.stdin.readline())
pathlib.Path('report.html').write_text('<html><body>report</body></html>')
print(json.dumps({'type':'message_end','message':{'role':'assistant','stopReason':'stop'}}), flush=True)
print(json.dumps({'type':'agent_settled'}), flush=True)
""")
    executable.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("B2T_REPORT_RUNTIME", "local")
    monkeypatch.setenv("B2T_WEB_UI_MODE", "default")
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    report = asyncio.run(run_pi(work, profile(), ReportOptions(mode="brief")))
    assert report.is_file()
    assert "user-a" not in "".join(
        p.read_text() for p in work.rglob("*") if p.is_file()
    )


@pytest.mark.parametrize(
    ("reason", "detail", "expected"),
    [
        ("error", "Connection error.", "无法连接模型服务"),
        ("error", "401 Authentication failed", "401 Authentication failed"),
        ("error", "402 Insufficient Balance", "402 Insufficient Balance"),
        ("length", "", "达到模型输出上限"),
    ],
)
def test_rpc_reports_specific_failure_without_leaking_credentials(
    reason, detail, expected
):
    async def scenario():
        reader = asyncio.StreamReader()
        process = SimpleNamespace(stdin=Writer(), stdout=reader)
        for event in [
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": reason,
                    "errorMessage": detail
                    + " user-credential-123 Authorization: Bearer sk-private https://example.com/?token=secret",
                },
            },
            {"type": "agent_settled"},
        ]:
            reader.feed_data((json.dumps(event) + "\n").encode())
        await consume(process, "report", None, api_key="user-credential-123")

    with pytest.raises(RuntimeError) as error:
        asyncio.run(scenario())
    message = str(error.value)
    assert expected in message
    assert reason in message
    assert "user-credential-123" not in message
    assert "sk-private" not in message
    assert "example.com" not in message
    assert "token=secret" not in message


def test_report_runtime_network_config(tmp_path):
    from b2t.config import load_config

    example = Path(__file__).resolve().parents[1] / "config.toml.example"
    content = example.read_text().replace(
        'docker_network = "bridge"', 'docker_network = "host"'
    )
    # Keep preset/context references relative to the project root.
    root = example.parent
    content = content.replace(
        '"summary_presets.toml"', f'"{root / "summary_presets.toml"}"'
    )
    content = content.replace('"context.toml"', f'"{root / "context.toml"}"')
    config_file = tmp_path / "config.toml"
    config_file.write_text(content)
    assert load_config(config_file).report.docker_network == "host"
    assert create_app_config().report.docker_network == "bridge"


def test_rpc_progress_logs_tools_without_write_payload_or_secrets():
    logs = []

    async def scenario():
        reader = asyncio.StreamReader()
        process = SimpleNamespace(stdin=Writer(), stdout=reader)
        events = [
            {"type": "message_start", "message": {"role": "assistant"}},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "thinking_delta",
                    "delta": "private reasoning",
                },
            },
            {
                "type": "tool_execution_start",
                "toolName": "write",
                "args": {"content": "<html>private source sk-secret</html>"},
            },
            {
                "type": "tool_execution_end",
                "isError": False,
                "result": {"content": "private source"},
            },
            {"type": "auto_retry_start", "errorMessage": "sk-secret"},
            {
                "type": "message_end",
                "message": {"role": "assistant", "stopReason": "stop"},
            },
            {"type": "agent_settled"},
        ]
        for event in events:
            reader.feed_data((json.dumps(event) + "\n").encode())
        await consume(process, "report", None, progress_callback=logs.append)

    asyncio.run(scenario())
    output = "\n".join(logs)
    assert "Pi 已启动" in output
    assert "模型开始生成" in output
    assert "写入文件" in output
    assert "工具执行完成" in output
    assert "自动重试" in output
    assert "校验报告" in output
    assert "private" not in output
    assert "sk-secret" not in output
    assert "<html>" not in output


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "bilibili；https://www.bilibili.com/video/BV1Q6h16hEv7/?vd_source=tracking",
            "https://www.bilibili.com/video/BV1Q6h16hEv7/",
        ),
        (
            "https://www.bilibili.com/video/BV1Q6h16hEv7/?p=2&vd_source=tracking&t=45&spm_id_from=share#reply",
            "https://www.bilibili.com/video/BV1Q6h16hEv7/?p=2&t=45#reply",
        ),
        (
            "https://example.com/episode?id=123&utm_source=share",
            "https://example.com/episode?id=123",
        ),
        ("BV1Q6h16hEv7", "https://www.bilibili.com/video/BV1Q6h16hEv7/"),
        ("", ""),
    ],
)
def test_report_source_url_drops_tracking_preserves_target(source, expected):
    from b2t.report.generate import clean_source_url

    assert clean_source_url(source) == expected


def test_rpc_detailed_logs_match_parallel_tools_and_redact_before_truncation():
    logs = []

    async def scenario():
        reader = asyncio.StreamReader()
        process = SimpleNamespace(stdin=Writer(), stdout=reader)
        events = [
            {
                "type": "tool_execution_start",
                "toolCallId": "read-1",
                "toolName": "read",
                "args": {"path": "/work/transcript.md", "offset": 20, "limit": 40},
            },
            {
                "type": "tool_execution_start",
                "toolCallId": "bash-1",
                "toolName": "bash",
                "args": {"command": "wc -c /work/report.html"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "bash-1",
                "isError": False,
                "result": {
                    "content": [{"type": "text", "text": "12345 /work/report.html"}]
                },
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "read-1",
                "isError": False,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "source excerpt Authorization: Bearer user-secret-123 "
                            + "x" * 1800,
                        }
                    ]
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "content": [
                        {"type": "thinking", "thinking": "hidden reasoning"},
                        {"type": "text", "text": "报告已写入 report.html"},
                    ],
                },
            },
            {"type": "agent_settled"},
        ]
        for event in events:
            reader.feed_data((json.dumps(event) + "\n").encode())
        await consume(
            process,
            "report",
            None,
            api_key="user-secret-123",
            progress_callback=logs.append,
        )

    asyncio.run(scenario())
    output = "\n".join(logs)
    assert "读取文件 /work/transcript.md，起始行 20，最多 40 行" in output
    assert "Pi 工具执行完成：执行命令：wc -c /work/report.html" in output
    assert "Pi 工具执行完成：读取文件 /work/transcript.md" in output
    assert "Pi 返回：12345 /work/report.html" in output
    assert "source excerpt" in output
    assert "报告已写入 report.html" in output
    assert "user-secret-123" not in output
    assert "hidden reasoning" not in output
    assert "已截断" in output
    assert max(map(len, logs)) < 1420


def test_deepseek_report_enables_high_reasoning_support():
    config = model_config(
        SummarizeModelProfile(
            provider="deepseek",
            model="deepseek-flash",
            api_key="test-only",
        )
    )["providers"]["b2t-user"]
    assert config["models"][0]["reasoning"] is True
    assert config["compat"]["thinkingFormat"] == "deepseek"
    assert config["compat"]["supportsReasoningEffort"] is True
