"""Platform abstraction: enum, metadata, and downloader interface."""

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

FILESYSTEM_COMPONENT_MAX_BYTES = 255
TRANSCRIPTION_TITLE_MAX_LENGTH = 15
TRANSCRIPTION_ARTIFACT_RESERVED_SUFFIX = "_summary_no_table.png"


def truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    """Truncate text to a UTF-8 byte limit without splitting a code point."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def build_filename_component(
    stem: str,
    *,
    prefix: str = "",
    suffix: str = "",
    max_bytes: int = FILESYSTEM_COMPONENT_MAX_BYTES,
    reserved_suffix: str = "",
) -> str:
    """Build one filesystem component while preserving prefix and suffix.

    ``reserved_suffix`` leaves room for a suffix that may replace ``suffix``
    later, such as ``_transcription.json`` derived from an audio filename.
    """
    suffix_bytes = max(
        len(suffix.encode("utf-8")),
        len(reserved_suffix.encode("utf-8")),
    )
    stem_budget = max_bytes - len(prefix.encode("utf-8")) - suffix_bytes
    if stem_budget < 0:
        raise ValueError("prefix and suffix exceed the filename byte limit")

    bounded_stem = truncate_utf8_bytes(stem, stem_budget)
    if bounded_stem != stem:
        bounded_stem = bounded_stem.rstrip(" .-")
    return f"{prefix}{bounded_stem}{suffix}"


def sanitize_filename_component(text: str, max_length: int = 80) -> str:
    """Sanitize a string for use as a filename component.

    Replaces characters that are problematic in filenames (slashes, colons,
    etc.) with safe alternatives, collapses whitespace, and truncates.
    """
    if not text:
        return "untitled"
    # Normalize unicode and strip
    cleaned = unicodedata.normalize("NFKC", text).strip()
    # Replace problematic chars
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", cleaned)
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .-")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .-")
    cleaned = truncate_utf8_bytes(cleaned, FILESYSTEM_COMPONENT_MAX_BYTES).rstrip(" .-")
    return cleaned or "untitled"


def build_transcription_artifact_name(
    name: str,
    resource_id: str,
    *,
    preserve_extension: bool = False,
) -> str:
    """Build a transcription filename with a bounded human-readable title."""
    suffix = Path(name).suffix if preserve_extension else ""
    stem = name[: -len(suffix)] if suffix else name
    resource_id = resource_id.strip()
    if not resource_id:
        raise ValueError("resource_id must not be empty")

    if stem.lower().startswith(resource_id.lower()) and (
        len(stem) == len(resource_id) or stem[len(resource_id)] in {"_", "-", " "}
    ):
        title = stem[len(resource_id) :].lstrip("_- ")
    else:
        title = stem

    if not title:
        return build_filename_component(resource_id, suffix=suffix)

    safe_title = sanitize_filename_component(
        title,
        max_length=TRANSCRIPTION_TITLE_MAX_LENGTH,
    )
    return build_filename_component(
        safe_title,
        prefix=f"{resource_id}_",
        suffix=suffix,
        reserved_suffix=TRANSCRIPTION_ARTIFACT_RESERVED_SUFFIX,
    )


class Platform(Enum):
    BILIBILI = "bilibili"
    XIAOYUZHOU = "xiaoyuzhou"
    XIMALAYA = "ximalaya"


@dataclass(frozen=True)
class PlatformMetadata:
    """Unified metadata for any platform."""

    platform: Platform
    platform_id: str  # bvid / episode eid / trackId
    title: str
    author: str
    author_uid: str = ""
    pubdate: str = ""
    pubdate_timestamp: int = 0
    description: str = ""
    duration_seconds: int = 0
    extra: dict = field(default_factory=dict)


class PlatformDownloader(ABC):
    """Interface for platform-specific audio download."""

    @abstractmethod
    def download_audio(
        self, url: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        """Download audio and return (file_path, metadata)."""
        raise NotImplementedError
