"""兼容导入：请改用 b2t.storage.minio_client。"""

from b2t.storage.minio_client import MinIOStorageBackend

__all__ = ["MinIOStorageBackend"]
