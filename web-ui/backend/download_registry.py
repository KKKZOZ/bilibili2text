"""In-memory download registry for stored and ephemeral artifacts."""

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from uuid import uuid4

from b2t.storage import StoredArtifact


class DownloadRegistry:
    def __init__(
        self,
        *,
        artifact_limit: int = 100,
        content_limit: int = 100,
    ) -> None:
        self._artifacts: OrderedDict[str, StoredArtifact] = OrderedDict()
        self._content: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._artifact_limit = artifact_limit
        self._content_limit = content_limit
        self._lock = Lock()

    def store_artifact(self, artifact: StoredArtifact) -> str:
        download_id = uuid4().hex
        with self._lock:
            self._artifacts[download_id] = artifact
            while len(self._artifacts) > self._artifact_limit:
                self._artifacts.popitem(last=False)
        return download_id

    def store_content(self, content: bytes, filename: str) -> str:
        download_id = uuid4().hex
        with self._lock:
            self._content[download_id] = (content, filename)
            while len(self._content) > self._content_limit:
                self._content.popitem(last=False)
        return download_id

    def get_artifact(self, download_id: str) -> StoredArtifact | None:
        with self._lock:
            return self._artifacts.get(download_id)

    def get_content(self, download_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            return self._content.get(download_id)

    def remove_artifacts_by_storage_keys(self, storage_keys: set[str]) -> None:
        with self._lock:
            stale_ids = [
                item_id
                for item_id, artifact in self._artifacts.items()
                if artifact.storage_key in storage_keys
            ]
            for item_id in stale_ids:
                self._artifacts.pop(item_id, None)

    @property
    def legacy_artifacts(self) -> OrderedDict[str, StoredArtifact]:
        return self._artifacts

    @property
    def legacy_content(self) -> OrderedDict[str, tuple[bytes, str]]:
        return self._content

    @property
    def legacy_lock(self) -> Lock:
        return self._lock


download_registry = DownloadRegistry()


def media_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"
