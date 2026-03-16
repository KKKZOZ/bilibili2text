"""Download index management: register artifacts and resolve media types."""

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from uuid import uuid4

from b2t.storage import StoredArtifact

from backend.state import _download_index, _download_lock, _download_limit

# In-memory content cache for ephemeral downloads (e.g. RAG answers before persistence)
_content_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_content_cache_lock = Lock()
_content_cache_limit = 100


def _store_download(artifact: StoredArtifact) -> str:
    download_id = uuid4().hex

    with _download_lock:
        _download_index[download_id] = artifact
        while len(_download_index) > _download_limit:
            _download_index.popitem(last=False)

    return download_id


def _store_content_download(content: bytes, filename: str) -> str:
    """Register raw bytes for immediate download. Returns download_id."""
    download_id = uuid4().hex
    with _content_cache_lock:
        _content_cache[download_id] = (content, filename)
        while len(_content_cache) > _content_cache_limit:
            _content_cache.popitem(last=False)
    return download_id


def _media_type_for_filename(filename: str) -> str:
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
