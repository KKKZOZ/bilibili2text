"""Shared helpers for stored artifacts and summary derivative families."""

import shutil
from pathlib import Path
from typing import Protocol

from b2t.storage import SUMMARY_ARTIFACT_KINDS, StorageBackend, StoredArtifact


class ArtifactRecord(Protocol):
    kind: object
    filename: str
    storage_key: str
    derived_from: str


class ArtifactCollection(Protocol):
    artifacts: list[ArtifactRecord]


def storage_parent_key(storage_key: str) -> str:
    normalized = storage_key.replace("\\", "/").strip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def sibling_storage_key(storage_key: str, filename: str) -> str:
    parent = storage_parent_key(storage_key)
    return f"{parent}/{filename}" if parent else filename


def materialize_artifact(
    storage_backend: StorageBackend,
    artifact: StoredArtifact,
    target_dir: Path,
) -> Path:
    target_path = target_dir / artifact.filename
    with (
        storage_backend.open_stream(artifact.storage_key) as stream,
        target_path.open("wb") as output,
    ):
        shutil.copyfileobj(stream, output, length=1024 * 1024)
    return target_path


def summary_family_storage_keys(
    detail: ArtifactCollection,
    summary_artifact: ArtifactRecord,
) -> set[str]:
    related = {summary_artifact.storage_key}
    while True:
        expanded = {
            artifact.storage_key
            for artifact in detail.artifacts
            if artifact.kind in SUMMARY_ARTIFACT_KINDS
            and artifact.derived_from.strip() in related
        }
        if expanded.issubset(related):
            break
        related.update(expanded)

    summary_stem = Path(summary_artifact.filename).stem
    expected_filenames = {
        summary_artifact.filename,
        f"{summary_stem}.txt",
        f"{summary_stem}.png",
        f"{summary_stem}_fancy.html",
        f"{summary_stem}_table.md",
        f"{summary_stem}_table.png",
        f"{summary_stem}_table.pdf",
        f"{summary_stem}_no_table.png",
        f"{summary_stem}_timeline.txt",
    }
    parent_key = storage_parent_key(summary_artifact.storage_key)
    for artifact in detail.artifacts:
        if artifact.kind not in SUMMARY_ARTIFACT_KINDS:
            continue
        if artifact.storage_key == summary_artifact.storage_key:
            related.add(artifact.storage_key)
            continue
        if artifact.derived_from.strip():
            continue
        if storage_parent_key(artifact.storage_key) != parent_key:
            continue
        if artifact.filename in expected_filenames:
            related.add(artifact.storage_key)
    return related
