"""Storage backend abstract definition."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


def classify_artifact_filename(filename: str) -> str | None:
    """Infer artifact type key from filename."""
    lowered = filename.lower()

    if lowered.endswith("_summary_fancy.html"):
        return "summary_fancy_html"
    if lowered.startswith("rag_") and lowered.endswith("_fancy.html"):
        return "summary_fancy_html"
    if lowered.startswith("rag_") and lowered.endswith(".md"):
        return "rag_answer"
    if lowered.endswith("_summary_table.pdf"):
        return "summary_table_pdf"
    if lowered.endswith("_summary_table.md"):
        return "summary_table_md"
    if lowered.endswith("_summary.txt"):
        return "summary_text"
    if lowered.endswith("_summary.md"):
        return "summary"
    if lowered.endswith("_transcription.json"):
        return "json"
    if lowered.endswith(".txt"):
        return "text"
    if lowered.endswith(".md"):
        return "markdown"
    if lowered.endswith((".m4a", ".mp3", ".flac", ".wav", ".aac", ".ogg")):
        return "audio"
    return None


@dataclass(frozen=True)
class StoredArtifact:
    """Unified description of a stored file."""

    filename: str
    storage_key: str
    backend: str


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
