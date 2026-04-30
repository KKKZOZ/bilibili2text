"""Storage backend factory."""

from pathlib import Path

from b2t.config import AppConfig
from b2t.storage.alicloud_client import AlicloudStorageBackend
from b2t.storage.base import PublicURLStorageBackend, StorageBackend, StoredArtifact
from b2t.storage.local import LocalStorageBackend
from b2t.storage.minio_client import MinIOStorageBackend


def _create_backend_from_storage_section(
    *,
    backend_name: str,
    local_output_dir: str | Path,
    minio_config,
    alicloud_config,
) -> StorageBackend:
    backend = backend_name.strip().lower()
    if backend == "local":
        return LocalStorageBackend(local_output_dir)
    if backend == "minio":
        return MinIOStorageBackend(minio_config)
    if backend == "alicloud":
        return AlicloudStorageBackend(alicloud_config)
    raise ValueError(
        "Unsupported storage.backend: "
        f"{backend_name}, supported values: local, minio, alicloud"
    )


def create_storage_backend(config: AppConfig) -> StorageBackend:
    return _create_backend_from_storage_section(
        backend_name=config.storage.backend,
        local_output_dir=config.download.output_dir,
        minio_config=config.storage.minio,
        alicloud_config=config.storage.alicloud,
    )


def create_stt_storage_backend(
    config: AppConfig,
) -> StorageBackend:
    selected_backend = config.stt.storage_profile.strip() or config.storage.backend
    return _create_backend_from_storage_section(
        backend_name=selected_backend,
        local_output_dir=config.download.output_dir,
        minio_config=config.storage.minio,
        alicloud_config=config.storage.alicloud,
    )


__all__ = [
    "StorageBackend",
    "PublicURLStorageBackend",
    "StoredArtifact",
    "create_storage_backend",
    "create_stt_storage_backend",
]
