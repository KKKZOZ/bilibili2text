"""Storage backend 抽象定义。"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


def classify_artifact_filename(filename: str) -> str | None:
    """根据文件名推断产物类型键。"""
    lowered = filename.lower()

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
    """统一描述已落库文件。"""

    filename: str
    storage_key: str
    backend: str


class StorageBackend(ABC):
    """统一的文件存储接口。"""

    backend_name: str
    persist_local_outputs: bool

    @abstractmethod
    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        """将本地文件写入后端并返回存储信息。"""
        raise NotImplementedError

    @contextmanager
    @abstractmethod
    def open_stream(self, storage_key: str) -> Iterator[BinaryIO]:
        """按 storage_key 打开一个可读取的二进制流。"""
        raise NotImplementedError

    def delete_file(self, storage_key: str) -> None:
        """删除指定的文件。"""
        raise NotImplementedError

    def find_existing_transcription(
        self,
        bvid: str,
    ) -> dict[str, StoredArtifact] | None:
        """按 BV 号查找已存在的转录结果。"""
        return None

    def list_existing_transcription_artifacts(
        self,
        bvid: str,
    ) -> list[StoredArtifact]:
        """按 BV 号列出已存在的转录相关文件。"""
        return []

    def supports_public_url(self) -> bool:
        """是否支持为本地文件生成可公网访问的 URL。"""
        return False

    @contextmanager
    def temporary_public_url(
        self,
        file_path: Path,
        *,
        object_key_prefix: str = "temp-audio",
    ) -> Iterator[str]:
        """临时上传本地文件并返回公网 URL；退出上下文时清理。"""
        raise RuntimeError(
            f"{self.backend_name} backend 不支持公网 URL 上传"
        )


class PublicURLStorageBackend(StorageBackend, ABC):
    """支持临时公网 URL 的存储抽象。"""

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
