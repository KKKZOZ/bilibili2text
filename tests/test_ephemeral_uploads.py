from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.storage import StoredArtifact  # noqa: E402
from backend.download_registry import DownloadRegistry  # noqa: E402
from backend.ephemeral_uploads import cleanup_expired_ephemeral_uploads  # noqa: E402
from backend.job_store import JobPatch, JobRepository  # noqa: E402


def test_job_repository_lists_and_marks_expired_ephemeral_uploads() -> None:
    repository = JobRepository(limit=10)
    created = repository.create(
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=False,
    )
    job_id = str(created["job_id"])
    repository.patch(
        job_id,
        JobPatch(
            status="succeeded",
            stage="completed",
            progress=100,
            is_ephemeral_upload=True,
            expires_at=(
                datetime.now(tz=timezone.utc) - timedelta(seconds=1)
            ).isoformat(),
            ephemeral_artifacts=[
                {
                    "filename": "upload_transcription.md",
                    "storage_key": "runs/upload_transcription.md",
                    "backend": "local",
                }
            ],
        ),
    )

    expired = repository.list_expired_ephemeral_uploads()
    assert len(expired) == 1
    assert expired[0]["job_id"] == job_id

    repository.mark_expired(job_id)
    payload = repository.get(job_id)
    assert payload is not None
    assert payload["status"] == "failed"
    assert payload["all_downloads"] == []
    assert payload["ephemeral_artifacts"] == []


def test_cleanup_expired_ephemeral_uploads_deletes_storage_and_download_tokens(
    monkeypatch,
) -> None:
    class FakeRepository:
        def __init__(self) -> None:
            self.marked: list[str] = []

        def list_expired_ephemeral_uploads(self):
            return [
                {
                    "job_id": "job-1",
                    "artifacts": [
                        {
                            "filename": "upload_transcription.md",
                            "storage_key": "runs/upload_transcription.md",
                            "backend": "local",
                        }
                    ],
                }
            ]

        def mark_expired(self, job_id: str) -> None:
            self.marked.append(job_id)

    class FakeStorage:
        persist_local_outputs = False

        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_file(self, storage_key: str) -> None:
            self.deleted.append(storage_key)

    fake_repository = FakeRepository()
    fake_storage = FakeStorage()
    registry = DownloadRegistry()
    artifact_id = registry.store_artifact(
        StoredArtifact(
            filename="upload_transcription.md",
            storage_key="runs/upload_transcription.md",
            backend="local",
        )
    )

    monkeypatch.setattr("backend.ephemeral_uploads.job_repository", fake_repository)
    monkeypatch.setattr(
        "backend.ephemeral_uploads.get_storage_backend", lambda: fake_storage
    )
    monkeypatch.setattr("backend.ephemeral_uploads.download_registry", registry)

    assert cleanup_expired_ephemeral_uploads() == 1
    assert fake_storage.deleted == ["runs/upload_transcription.md"]
    assert fake_repository.marked == ["job-1"]
    assert registry.get_artifact(artifact_id) is None
