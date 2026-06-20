"""Lifecycle helpers for open-public ephemeral upload jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import shutil
from pathlib import Path
from threading import Event, Thread
from typing import Iterable

from b2t.storage import StoredArtifact

from backend.dependencies import get_storage_backend
from backend.download_registry import download_registry
from backend.job_store import job_repository
from backend.settings import (
    EPHEMERAL_UPLOAD_CLEANUP_INTERVAL_SECONDS,
    EPHEMERAL_UPLOAD_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

_stop_event = Event()
_cleanup_thread: Thread | None = None


def ephemeral_upload_expires_at(*, completed_at: datetime | None = None) -> str:
    base = completed_at or datetime.now(tz=timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(seconds=EPHEMERAL_UPLOAD_TTL_SECONDS)).isoformat()


def serialize_ephemeral_artifacts(
    artifacts: Iterable[StoredArtifact],
) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for artifact in artifacts:
        if artifact.storage_key in seen_keys:
            continue
        seen_keys.add(artifact.storage_key)
        serialized.append(
            {
                "filename": artifact.filename,
                "storage_key": artifact.storage_key,
                "backend": artifact.backend,
            }
        )
    return serialized


def _storage_keys_for_job_artifacts(artifacts: list[dict[str, str]]) -> set[str]:
    return {
        storage_key
        for artifact in artifacts
        if (storage_key := artifact.get("storage_key", "").strip())
    }


def _delete_local_parent_dirs(storage_keys: set[str]) -> None:
    parent_dirs = {
        Path(storage_key).expanduser().resolve().parent
        for storage_key in storage_keys
        if storage_key.startswith("/")
    }
    for directory in sorted(
        parent_dirs, key=lambda path: len(path.parts), reverse=True
    ):
        try:
            if directory.exists() and directory.is_dir():
                shutil.rmtree(directory)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除临时上传目录失败 %s: %s", directory, exc)


def cleanup_expired_ephemeral_uploads() -> int:
    expired_jobs = job_repository.list_expired_ephemeral_uploads()
    if not expired_jobs:
        return 0

    storage_backend = get_storage_backend()
    cleaned = 0
    for job in expired_jobs:
        job_id = str(job.get("job_id", ""))
        artifacts = job.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
        storage_keys = _storage_keys_for_job_artifacts(
            [item for item in artifacts if isinstance(item, dict)]
        )
        for storage_key in storage_keys:
            try:
                storage_backend.delete_file(storage_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("删除临时上传文件失败 %s: %s", storage_key, exc)
        if storage_backend.persist_local_outputs:
            _delete_local_parent_dirs(storage_keys)
        download_registry.remove_artifacts_by_storage_keys(storage_keys)
        if job_id:
            job_repository.mark_expired(job_id)
        cleaned += 1
    return cleaned


def _cleanup_loop() -> None:
    while not _stop_event.wait(EPHEMERAL_UPLOAD_CLEANUP_INTERVAL_SECONDS):
        try:
            count = cleanup_expired_ephemeral_uploads()
            if count:
                logger.info("已清理 %s 个过期临时上传任务", count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("临时上传清理任务失败: %s", exc)


def start_ephemeral_upload_cleanup() -> None:
    global _cleanup_thread
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return
    _stop_event.clear()
    _cleanup_thread = Thread(
        target=_cleanup_loop,
        name="b2t-ephemeral-upload-cleanup",
        daemon=True,
    )
    _cleanup_thread.start()


def stop_ephemeral_upload_cleanup() -> None:
    _stop_event.set()
    if _cleanup_thread is not None:
        _cleanup_thread.join(timeout=5)
