import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend import postprocess, settings
from backend.job_store import JobManager, JobPatch
from backend.routes import process
from backend.schemas import ProcessRequest
from backend.settings import build_open_public_config

from b2t.config import SummarizeModelProfile, create_app_config
from b2t.storage import ArtifactKind, StoredArtifact


def test_report_postprocessing_uses_original_source_and_tracks_ephemeral_artifact(
    monkeypatch,
):
    manager = JobManager()
    job = manager.create(
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
        report_options={"mode": "brief"},
    )
    job_id = job["job_id"]
    manager.patch(
        job_id,
        JobPatch(
            status="succeeded",
            is_ephemeral_upload=True,
            ephemeral_artifacts=[],
            report_source_url="https://example.com/video",
        ),
    )
    monkeypatch.setattr(postprocess, "job_manager", manager)
    monkeypatch.setattr(postprocess, "_get_job", manager.get)
    monkeypatch.setattr(
        postprocess,
        "_update_job",
        lambda job_id, **kwargs: manager.patch(job_id, JobPatch(**kwargs)),
    )
    monkeypatch.setattr(postprocess, "submit_report", lambda fn: fn())
    source = StoredArtifact(
        "source.md", "source/source.md", "local", ArtifactKind.MARKDOWN
    )
    summary = StoredArtifact(
        "summary.md", "source/summary.md", "local", ArtifactKind.SUMMARY
    )
    report = StoredArtifact(
        "report.html", "source/report.html", "local", ArtifactKind.SUMMARY_FANCY_HTML
    )

    report_logs = []
    monkeypatch.setattr(
        postprocess,
        "_append_job_log",
        lambda target_job_id, message: report_logs.append((target_job_id, message)),
    )

    def generate(**kwargs):
        kwargs["progress_callback"]("Pi 工具：写入文件")
        assert kwargs["source_artifact"] == source
        assert kwargs["options"].mode == "brief"
        assert kwargs["metadata"]["url"] == "https://example.com/video"
        return report

    monkeypatch.setattr(postprocess, "generate_stored_report", generate)
    monkeypatch.setattr(
        postprocess,
        "_artifact_download_item",
        lambda a: {"url": "/report", "filename": a.filename},
    )
    postprocess.PostProcessScheduler().trigger_fancy_html_generation(
        job_id=job_id,
        bvid=None,
        results={"markdown": source, "summary": summary},
        config=None,
        storage_backend=None,
        run_id=None,
        summary_preset=None,
        summary_profile=None,
    )
    final = manager.get(job_id)
    assert final["fancy_html_status"] == "succeeded"
    assert all(target == job_id for target, _ in report_logs)
    assert any("进入队列" in message for _, message in report_logs)
    assert any("写入文件" in message for _, message in report_logs)
    assert any("已加入下载列表" in message for _, message in report_logs)
    assert final["ephemeral_artifacts"][0]["storage_key"] == report.storage_key
    assert final["all_downloads"][0]["url"] == "/report"


def test_url_route_saves_report_options_without_requiring_summary(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        process,
        "_ensure_runtime_ready",
        lambda **kwargs: captured.update(readiness=kwargs),
    )
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: captured.update(job=kwargs) or {"job_id": "report-job"},
    )
    monkeypatch.setattr(
        process.job_manager,
        "submit",
        lambda *args, **kwargs: captured.update(submission=kwargs),
    )
    response = process.process_video(
        ProcessRequest(
            url="https://www.bilibili.com/video/BV1AB411c7mD",
            skip_summary=True,
            auto_generate_fancy_html=True,
            report_options={"mode": "brief", "profile": "custom"},
            custom_llm_api_key="user-only",
        )
    )
    assert response.job_id == "report-job"
    assert captured["job"]["report_options"]["mode"] == "brief"
    assert captured["readiness"]["require_transcription_key"] is False
    assert "user-only" not in str(captured["job"])
    assert captured["submission"]["custom_llm_api_key"] == "user-only"


def test_public_config_does_not_retain_other_provider_server_keys():
    config = create_app_config(
        summarize_api_key="admin-secret",
        summarize_provider="openai_compatible",
        summarize_base_url="https://example.com/v1",
        summarize_model="test",
    )
    public = build_open_public_config(
        config,
        "",
        custom_llm_base_url="https://user.example/v1",
        custom_llm_api_key="user-key",
        custom_llm_model="user-model",
    )
    assert all(p.api_key != "admin-secret" for p in public.summarize.profiles.values())
    assert public.fancy_html.profile == config.fancy_html.profile
    assert public.summarize.profiles[public.fancy_html.profile].api_key == ""
    assert (
        public.summarize.profiles[settings.OPEN_PUBLIC_CUSTOM_LLM_PROFILE].api_key
        == "user-key"
    )


def test_report_only_preflight_uses_selected_provider_without_dashscope(monkeypatch):
    config = create_app_config(
        summarize_api_key="",
        summarize_model="test",
        summarize_provider="openai_compatible",
        summarize_base_url="https://example.com/v1",
    )
    config.summarize.profiles["report-user"] = SummarizeModelProfile(
        provider="openai_compatible",
        model="test",
        api_key="user-key",
        api_base="https://user.example/v1",
    )
    monkeypatch.setattr(process, "get_runtime_app_config", lambda **kwargs: config)
    monkeypatch.setattr(process, "check_runtime", lambda: None)
    process._ensure_runtime_ready(
        skip_summary=True,
        require_transcription_key=False,
        report_options=ProcessRequest(
            url="x", report_options={"profile": "report-user"}
        ).report_options,
    )


def test_removed_report_parameters_are_rejected_before_starting_job():
    with pytest.raises(ValueError):
        ProcessRequest(
            url="x", report_options={"context_window": 16000, "max_tokens": 32000}
        )


def test_report_runtime_does_not_fall_back_to_shared_public_keys(monkeypatch):
    config = create_app_config(summarize_api_key="admin-secret", summarize_model="test")
    monkeypatch.setattr(settings, "get_app_config", lambda: config)
    monkeypatch.setattr(settings, "is_open_public_mode", lambda: True)
    monkeypatch.setattr(settings, "get_public_api_key", lambda: "shared-dashscope")
    monkeypatch.setattr(
        settings, "get_public_deepseek_api_key", lambda: "shared-deepseek"
    )
    public = settings.get_runtime_app_config(user_credentials_only=True)
    assert all(not profile.api_key for profile in public.summarize.profiles.values())
    assert public.stt.qwen_api_key == ""
