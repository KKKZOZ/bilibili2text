from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.storage import StoredArtifact  # noqa: E402
from backend import runner  # noqa: E402


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
