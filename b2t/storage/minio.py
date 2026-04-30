"""Compatibility import: use b2t.storage.minio_client instead."""

from b2t.storage.minio_client import MinIOStorageBackend

__all__ = ["MinIOStorageBackend"]
