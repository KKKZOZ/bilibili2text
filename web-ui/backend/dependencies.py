"""Lazy application dependencies used by API handlers and workers."""

from threading import Lock

from b2t.history import HistoryDB
from b2t.storage import (
    StorageBackend,
    create_storage_backend,
    create_stt_storage_backend,
)

from backend.settings import get_app_config

_storage_backend: StorageBackend | None = None
_stt_storage_backend: StorageBackend | None = None
_history_db: HistoryDB | None = None
_rag_store: "RagStore | None" = None  # noqa: F821
_rag_store_lock = Lock()


def get_storage_backend() -> StorageBackend:
    global _storage_backend
    if _storage_backend is None:
        _storage_backend = create_storage_backend(get_app_config())
    return _storage_backend


def get_stt_storage_backend() -> StorageBackend:
    global _stt_storage_backend
    if _stt_storage_backend is None:
        _stt_storage_backend = create_stt_storage_backend(get_app_config())
    return _stt_storage_backend


def get_history_db() -> HistoryDB:
    global _history_db
    if _history_db is None:
        config = get_app_config()
        _history_db = HistoryDB(config.download.db_dir)
    return _history_db


def get_rag_store() -> "RagStore":  # noqa: F821
    global _rag_store
    if _rag_store is not None:
        return _rag_store

    with _rag_store_lock:
        if _rag_store is not None:
            return _rag_store
        from b2t.rag.store import RagStore  # noqa: PLC0415

        config = get_app_config()
        _rag_store = RagStore(
            chroma_dir=config.rag.chroma_dir,
            collection_name=config.rag.collection_name,
        )
        return _rag_store
