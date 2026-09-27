import asyncio

import httpx
import pytest

from b2t.config import BackendConfig
from b2t.monitor.backend_client import (
    BackendError,
    MonitorBackendClient,
    SubmissionUnknown,
    parse_progress,
)


@pytest.mark.parametrize(
    ("kind", "skip_summary", "report"),
    [("summary", False, False), ("report", True, True), ("both", False, True)],
)
def test_submission_uses_backend_defaults(kind, skip_summary, report):
    import json

    async def scenario():
        calls = []

        def handler(request):
            calls.append(request)
            assert request.url.path == "/api/process"
            assert json.loads(request.content) == {
                "url": "https://www.bilibili.com/video/BV1AB411c7mD",
                "skip_summary": skip_summary,
                "auto_generate_fancy_html": report,
            }
            return httpx.Response(200, json={"job_id": "job-1"})

        client = MonitorBackendClient(
            BackendConfig(host="0.0.0.0", port=8080),
            transport=httpx.MockTransport(handler),
        )
        try:
            assert await client.submit("BV1AB411c7mD", kind) == "job-1"
            assert len(calls) == 1
            assert str(calls[0].url) == "http://127.0.0.1:8080/api/process"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_report_completion_waits_for_postprocessing():
    data = {"status": "succeeded", "fancy_html_status": "pending"}
    assert parse_progress(data, "summary").done
    assert not parse_progress(data, "report").done
    assert not parse_progress(data, "both").done
    data["fancy_html_status"] = "running"
    assert not parse_progress(data, "both").done
    data["fancy_html_status"] = "succeeded"
    result = parse_progress(data, "both")
    assert result.done
    assert result.label == "总结和报告完成"
    data.update(fancy_html_status="failed", fancy_html_error="报告环境未配置")
    result = parse_progress(data, "both")
    assert result.done
    assert result.label == "阅读报告失败"
    assert result.error == "报告环境未配置"


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_job_does_not_wait_for_report(status):
    result = parse_progress(
        {"status": status, "fancy_html_status": "pending", "error": "stop"}, "both"
    )
    assert result.done
    assert result.error == "stop"


def test_connection_and_ambiguous_submission_errors_are_distinct():
    async def scenario():
        for error, expected in [
            (httpx.ConnectError("offline"), BackendError),
            (httpx.ReadTimeout("timeout"), SubmissionUnknown),
        ]:
            calls = []

            def handler(request, calls=calls, error=error):
                calls.append(request)
                raise error

            client = MonitorBackendClient(
                BackendConfig(), transport=httpx.MockTransport(handler)
            )
            try:
                with pytest.raises(expected) as exc:
                    await client.submit("BV1AB411c7mD", "both")
                assert type(exc.value) is expected
                assert len(calls) == 1
            finally:
                await client.close()

    asyncio.run(scenario())


def test_backend_rejection_and_progress_endpoint():
    async def scenario():
        def handler(request):
            if request.method == "POST":
                return httpx.Response(429, json={"detail": "队列已满"})
            assert request.url.path == "/api/process/job-1"
            return httpx.Response(
                200, json={"status": "running", "stage_label": "总结", "progress": 70}
            )

        client = MonitorBackendClient(
            BackendConfig(), transport=httpx.MockTransport(handler)
        )
        try:
            with pytest.raises(BackendError, match="队列已满"):
                await client.submit("BV1AB411c7mD", "summary")
            result = await client.progress("job-1", "summary")
            assert result.label == "总结 70%"
            assert not result.done
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["summary", "report", "both"])
def test_requests_match_real_backend_api(monkeypatch, kind):
    from pathlib import Path

    from fastapi import FastAPI

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "web-ui"))
    from backend.routes import process

    captured = {}
    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: captured.update(kwargs) or {"job_id": "test-job"},
    )
    monkeypatch.setattr(process.job_manager, "submit", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(process.router)

    async def scenario():
        client = MonitorBackendClient(
            BackendConfig(), transport=httpx.ASGITransport(app=app)
        )
        try:
            assert await client.submit("BV1AB411c7mD", kind) == "test-job"
        finally:
            await client.close()

    asyncio.run(scenario())
    assert captured["summary_profile"] is None
    assert captured["summary_preset"] is None
    assert captured["report_options"] == {"mode": "standard", "profile": ""}
    assert captured["skip_summary"] == (kind == "report")
    assert captured["auto_generate_fancy_html"] == (kind != "summary")
