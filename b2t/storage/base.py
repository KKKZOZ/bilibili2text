"""Storage backend abstract definition."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO


class ArtifactKind(StrEnum):
    """Canonical artifact kinds persisted in manifests and history."""

    FILE = "file"
    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"
    AUDIO = "audio"
    SUMMARY = "summary"
    SUMMARY_TEXT = "summary_text"
    SUMMARY_FANCY_HTML = "summary_fancy_html"
    SUMMARY_PNG = "summary_png"
    SUMMARY_NO_TABLE_PNG = "summary_no_table_png"
    SUMMARY_TABLE_MD = "summary_table_md"
    SUMMARY_TABLE_PNG = "summary_table_png"
    SUMMARY_TABLE_PDF = "summary_table_pdf"
    SUMMARY_TIMELINE = "summary_timeline"
    RAG_ANSWER = "rag_answer"


SUMMARY_ARTIFACT_KINDS = frozenset(
    {
        ArtifactKind.SUMMARY,
        ArtifactKind.SUMMARY_TEXT,
        ArtifactKind.SUMMARY_FANCY_HTML,
        ArtifactKind.SUMMARY_PNG,
        ArtifactKind.SUMMARY_NO_TABLE_PNG,
        ArtifactKind.SUMMARY_TABLE_MD,
        ArtifactKind.SUMMARY_TABLE_PNG,
        ArtifactKind.SUMMARY_TABLE_PDF,
        ArtifactKind.SUMMARY_TIMELINE,
    }
)


def classify_artifact_filename(filename: str) -> ArtifactKind | None:
    """Infer artifact type key from filename."""
    lowered = filename.lower()

    if lowered.endswith("_summary_fancy.html"):
        return ArtifactKind.SUMMARY_FANCY_HTML
    if lowered.startswith("rag_") and lowered.endswith("_fancy.html"):
        return ArtifactKind.SUMMARY_FANCY_HTML
    if lowered.startswith("rag_") and lowered.endswith(".md"):
        return ArtifactKind.RAG_ANSWER
    if lowered.endswith("_summary_table.pdf"):
        return ArtifactKind.SUMMARY_TABLE_PDF
    if lowered.endswith("_summary_table.png"):
        return ArtifactKind.SUMMARY_TABLE_PNG
    if lowered.endswith("_summary_table.md"):
        return ArtifactKind.SUMMARY_TABLE_MD
    if lowered.endswith("_summary_no_table.png"):
        return ArtifactKind.SUMMARY_NO_TABLE_PNG
    if lowered.endswith("_summary_timeline.txt"):
        return ArtifactKind.SUMMARY_TIMELINE
    if lowered.endswith("_summary.png"):
        return ArtifactKind.SUMMARY_PNG
    if lowered.endswith("_summary.txt"):
        return ArtifactKind.SUMMARY_TEXT
    if lowered.endswith("_summary.md"):
        return ArtifactKind.SUMMARY
    if lowered.endswith("_comments.json"):
        return "comments_json"
    if lowered.endswith("_comments.md"):
        return "comments_markdown"
    if lowered.endswith("_transcription.json"):
        return ArtifactKind.JSON
    if lowered.endswith(".txt"):
        return ArtifactKind.TEXT
    if lowered.endswith(".md"):
        return ArtifactKind.MARKDOWN
    if lowered.endswith((".m4a", ".mp3", ".flac", ".wav", ".aac", ".ogg")):
        return ArtifactKind.AUDIO
    return None


def resolve_artifact_kind(
    kind: ArtifactKind | str | None,
    filename: str,
) -> ArtifactKind | str:
    """Use explicit manifest metadata, with filename inference for legacy artifacts."""
    normalized = str(kind or "").strip()
    if normalized and normalized != ArtifactKind.FILE:
        return normalized
    return classify_artifact_filename(filename) or normalized or ArtifactKind.FILE


@dataclass(frozen=True)
class StoredArtifact:
    """Unified description of a stored file."""

    filename: str
    storage_key: str
    backend: str
    kind: ArtifactKind | str | None = None
    derived_from: str = ""
    summary_preset: str = ""
    summary_profile: str = ""


class StorageBackend(ABC):
    """Unified file storage interface."""

    backend_name: str
    persist_local_outputs: bool

    @abstractmethod
    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        """Write a local file to the backend and return storage info."""
        raise NotImplementedError

    @contextmanager
    @abstractmethod
    def open_stream(self, storage_key: str) -> Iterator[BinaryIO]:
        """Open a readable binary stream by storage_key."""
        raise NotImplementedError

    def delete_file(self, storage_key: str) -> None:
        """Delete the specified file."""
        raise NotImplementedError

    def find_existing_transcription(
        self,
        bvid: str,
    ) -> dict[str, StoredArtifact] | None:
        """Find existing transcription results by BV ID."""
        return None

    def list_existing_transcription_artifacts(
        self,
        bvid: str,
    ) -> list[StoredArtifact]:
        """List existing transcription-related files by BV ID."""
        return []

    def supports_public_url(self) -> bool:
        """Whether the backend supports generating publicly accessible URLs for local files."""
        return False

    @contextmanager
    def temporary_public_url(
        self,
        file_path: Path,
        *,
        object_key_prefix: str = "temp-audio",
    ) -> Iterator[str]:
        """Temporarily upload a local file and return a public URL; cleans up on context exit."""
        raise RuntimeError(
            f"{self.backend_name} backend does not support public URL upload"
        )


class PublicURLStorageBackend(StorageBackend, ABC):
    """Storage abstraction supporting temporary public URLs."""

    def supports_public_url(self) -> bool:
        return True

    @contextmanager
    @abstractmethod
    def temporary_public_url(
        self,
        file_path: Path,
        *,
        object_key_prefix: str = "temp-audio",
    ) -> Iterator[str]:
        raise NotImplementedError
