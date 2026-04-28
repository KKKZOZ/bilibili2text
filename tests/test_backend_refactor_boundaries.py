from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.storage import StoredArtifact
from backend.download_registry import DownloadRegistry, media_type_for_filename
from backend.job_store import JobPatch, JobRepository


def test_job_repository_create_patch_cancel() -> None:
    repository = JobRepository(limit=10)
    created = repository.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
    )

    job_id = str(created["job_id"])
    repository.patch(
        job_id,
        JobPatch(
            status="running",
            stage="downloading",
            progress=25,
            bvid="BV1234567890",
        ),
    )

    running = repository.get(job_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["stage"] == "downloading"
    assert running["progress"] == 25
    assert running["bvid"] == "BV1234567890"

    cancelled, status = repository.cancel(job_id)
    assert cancelled is True
    assert status == "cancelled"
    assert repository.get(job_id)["status"] == "cancelled"


def test_download_registry_artifacts_content_and_media_types() -> None:
    registry = DownloadRegistry(artifact_limit=10, content_limit=10)
    artifact = StoredArtifact(
        filename="summary.md",
        storage_key="runs/summary.md",
        backend="local",
    )

    artifact_id = registry.store_artifact(artifact)
    content_id = registry.store_content(b"hello", "answer.txt")

    assert registry.get_artifact(artifact_id) == artifact
    assert registry.get_content(content_id) == (b"hello", "answer.txt")
    assert media_type_for_filename("answer.txt") == "text/plain; charset=utf-8"
    assert media_type_for_filename("summary.md") == "text/markdown; charset=utf-8"

    registry.remove_artifacts_by_storage_keys({"runs/summary.md"})
    assert registry.get_artifact(artifact_id) is None
