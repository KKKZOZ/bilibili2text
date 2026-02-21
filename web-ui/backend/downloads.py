"""Download index management: register artifacts and resolve media types."""

from pathlib import Path
from uuid import uuid4

from b2t.storage import StoredArtifact

from backend.state import _download_index, _download_lock, _download_limit


def _store_download(artifact: StoredArtifact) -> str:
    download_id = uuid4().hex

    with _download_lock:
        _download_index[download_id] = artifact
        while len(_download_index) > _download_limit:
            _download_index.popitem(last=False)

    return download_id


def _media_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"
