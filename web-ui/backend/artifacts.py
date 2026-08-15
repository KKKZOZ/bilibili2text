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
    summary_preset: str
    summary_profile: str


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


def _summary_family_stem(filename: str) -> str:
    stem = Path(filename).stem
    for suffix in ("_no_table", "_fancy", "_table", "_timeline"):
        if stem.lower().endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def summary_artifact_group_ids(
    artifacts: list[ArtifactRecord],
) -> dict[str, str]:
    """Assign summary roots and their derivatives to deterministic groups."""
    indexed_roots = [
        (index, artifact)
        for index, artifact in enumerate(artifacts)
        if artifact.kind == "summary"
    ]
    if not indexed_roots:
        return {}

    group_ids = {
        artifact.storage_key: f"summary-{group_index}"
        for group_index, (_, artifact) in enumerate(indexed_roots, start=1)
    }
    artifacts_by_key = {artifact.storage_key: artifact for artifact in artifacts}

    def explicit_group_id(artifact: ArtifactRecord) -> str:
        parent_key = artifact.derived_from.strip()
        visited: set[str] = set()
        while parent_key and parent_key not in visited:
            if parent_key in group_ids:
                return group_ids[parent_key]
            visited.add(parent_key)
            parent = artifacts_by_key.get(parent_key)
            if parent is None:
                break
            parent_key = parent.derived_from.strip()
        return ""

    unresolved: list[tuple[int, ArtifactRecord]] = []
    for index, artifact in enumerate(artifacts):
        if artifact.kind not in SUMMARY_ARTIFACT_KINDS or artifact.kind == "summary":
            continue
        resolved_group_id = explicit_group_id(artifact)
        if resolved_group_id:
            group_ids[artifact.storage_key] = resolved_group_id
        else:
            unresolved.append((index, artifact))

    for artifact_index, artifact in unresolved:
        candidates = indexed_roots
        same_config = [
            candidate
            for candidate in candidates
            if candidate[1].summary_preset.strip() == artifact.summary_preset.strip()
            and candidate[1].summary_profile.strip() == artifact.summary_profile.strip()
        ]
        if same_config:
            candidates = same_config

        family_stem = _summary_family_stem(artifact.filename)
        same_family = [
            candidate
            for candidate in candidates
            if _summary_family_stem(candidate[1].filename) == family_stem
        ]
        if same_family:
            candidates = same_family

        parent_key = storage_parent_key(artifact.storage_key)
        same_parent = [
            candidate
            for candidate in candidates
            if storage_parent_key(candidate[1].storage_key) == parent_key
        ]
        if same_parent:
            candidates = same_parent

        preceding = [
            candidate for candidate in candidates if candidate[0] <= artifact_index
        ]
        selected = max(preceding or candidates, key=lambda candidate: candidate[0])
        group_ids[artifact.storage_key] = group_ids[selected[1].storage_key]

    return group_ids


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
