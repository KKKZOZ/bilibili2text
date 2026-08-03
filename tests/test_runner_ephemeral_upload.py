import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend import runner

from b2t.cancellation import CancellationToken
from b2t.storage import StoredArtifact


def test_ephemeral_upload_runner_skips_history_and_rag(monkeypatch, tmp_path) -> None:
    uploaded = tmp_path / "upload.wav"
    uploaded.write_bytes(b"audio")
    captured_updates: list[dict[str, object]] = []

    markdown = StoredArtifact(
        filename="upload_transcription.md",
        storage_key="runs/upload_transcription.md",
        backend="local",
    )
    json_artifact = StoredArtifact(
        filename="upload_transcription.json",
        storage_key="runs/upload_transcription.json",
        backend="local",
    )

    class FakeStorage:
        persist_local_outputs = False
        backend_name = "local"

    monkeypatch.setattr(runner, "get_runtime_app_config", lambda **kwargs: object())
    monkeypatch.setattr(runner, "get_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "get_stt_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(
        runner,
        "run_pipeline",
        lambda *args, **kwargs: {"markdown": markdown, "json": json_artifact},
    )
    monkeypatch.setattr(
        runner,
        "_build_success_download_fields",
        lambda results: {
            "download_url": "/api/download/md",
            "filename": markdown.filename,
            "txt_download_url": None,
            "txt_filename": None,
            "summary_download_url": None,
            "summary_filename": None,
            "summary_txt_download_url": None,
            "summary_txt_filename": None,
            "summary_table_pdf_download_url": None,
            "summary_table_pdf_filename": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "_build_all_download_items",
        lambda artifacts: [{"filename": artifact.filename} for artifact in artifacts],
    )
    monkeypatch.setattr(
        runner,
        "_update_job",
        lambda job_id, **kwargs: captured_updates.append(kwargs),
    )
    monkeypatch.setattr(runner, "_append_job_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner.existing_transcription_service,
        "handle_if_existing",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("should not reuse history")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_record_history",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not record")),
    )
    monkeypatch.setattr(
        runner.postprocess_scheduler,
        "trigger_rag_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not index")
        ),
    )

    runner._run_job(
        "job-1",
        url=None,
        input_audio_path=str(uploaded),
        input_bvid="upload-job-1",
        ephemeral_upload=True,
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
    )

    success_update = next(
        item for item in captured_updates if item.get("status") == "succeeded"
    )
    assert success_update["is_ephemeral_upload"] is True
    assert isinstance(success_update["expires_at"], str)
    assert success_update["ephemeral_artifacts"] == [
        {
            "filename": "upload_transcription.md",
            "storage_key": "runs/upload_transcription.md",
            "backend": "local",
        },
        {
            "filename": "upload_transcription.json",
            "storage_key": "runs/upload_transcription.json",
            "backend": "local",
        },
    ]
    assert any("2 小时" in str(item.get("notice", "")) for item in captured_updates)


def test_png_export_failure_does_not_fail_completed_summary(monkeypatch) -> None:
    captured_updates: list[dict[str, object]] = []
    captured_logs: list[str] = []

    markdown = StoredArtifact(
        filename="episode_transcription.md",
        storage_key="runs/episode_transcription.md",
        backend="local",
    )
    summary = StoredArtifact(
        filename="episode_summary.md",
        storage_key="runs/episode_summary.md",
        backend="local",
    )

    class FakeStorage:
        persist_local_outputs = False
        backend_name = "local"

    monkeypatch.setattr(runner, "get_runtime_app_config", lambda **kwargs: object())
    monkeypatch.setattr(runner, "get_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "get_stt_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(
        runner,
        "run_pipeline",
        lambda *args, **kwargs: {"markdown": markdown, "summary": summary},
    )
    monkeypatch.setattr(
        runner,
        "_generate_summary_png_exports",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("Page.screenshot: Timeout 30000ms exceeded")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_build_success_download_fields",
        lambda results: {
            "download_url": "/api/download/md",
            "filename": markdown.filename,
            "txt_download_url": None,
            "txt_filename": None,
            "summary_download_url": "/api/download/summary",
            "summary_filename": summary.filename,
            "summary_txt_download_url": None,
            "summary_txt_filename": None,
            "summary_table_pdf_download_url": None,
            "summary_table_pdf_filename": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "_build_all_download_items",
        lambda artifacts: [{"filename": artifact.filename} for artifact in artifacts],
    )
    monkeypatch.setattr(
        runner,
        "_update_job",
        lambda job_id, **kwargs: captured_updates.append(kwargs),
    )
    monkeypatch.setattr(
        runner,
        "_append_job_log",
        lambda job_id, message: captured_logs.append(message),
    )

    runner._run_job(
        "job-1",
        url=None,
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
    )

    assert not any(item.get("status") == "failed" for item in captured_updates)
    success_update = next(
        item for item in captured_updates if item.get("status") == "succeeded"
    )
    assert success_update["error"] is None
    assert "PNG 图片导出失败" in str(success_update["notice"])
    assert any("[WARNING]" in message for message in captured_logs)


def test_runner_cancellation_after_pipeline_skips_persistence_and_postprocessing(
    monkeypatch, tmp_path
) -> None:
    uploaded = tmp_path / "BV1R9i4BoE7H_audio.wav"
    uploaded.write_bytes(b"audio")
    token = CancellationToken()
    updates: list[dict[str, object]] = []

    class FakeStorage:
        persist_local_outputs = False
        backend_name = "local"

    monkeypatch.setattr(runner, "get_runtime_app_config", lambda **kwargs: object())
    monkeypatch.setattr(runner, "get_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "get_stt_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(
        runner.existing_transcription_service,
        "handle_if_existing",
        lambda **kwargs: False,
    )

    def cancel_after_pipeline(*_args, **kwargs):
        kwargs["cancellation_token"].cancel()
        return {}

    monkeypatch.setattr(runner, "run_pipeline", cancel_after_pipeline)
    monkeypatch.setattr(
        runner,
        "_build_success_download_fields",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not persist cancelled work")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_record_history",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not write history after cancellation")
        ),
    )
    monkeypatch.setattr(
        runner.postprocess_scheduler,
        "trigger_rag_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not schedule postprocessing after cancellation")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_update_job",
        lambda _job_id, **kwargs: updates.append(kwargs),
    )

    runner._run_job(
        "job-1",
        url=None,
        input_audio_path=str(uploaded),
        input_bvid="BV1R9i4BoE7H",
        ephemeral_upload=False,
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=True,
        cancellation_token=token,
    )

    assert token.is_cancelled()
    assert not any(item.get("status") == "succeeded" for item in updates)
