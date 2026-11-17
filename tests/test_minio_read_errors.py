from types import SimpleNamespace

import pytest
from minio.error import S3Error

from b2t.storage.minio_client import MinIOStorageBackend


@pytest.mark.parametrize("code", ["AccessDenied", "InternalError", "NoSuchBucket"])
def test_storage_errors_are_not_cache_misses(code):
    backend = MinIOStorageBackend.__new__(MinIOStorageBackend)
    backend._bucket = "test"

    def fail(*args):
        raise S3Error(None, code, "failed", "key", "request", "host")

    backend._client = SimpleNamespace(get_object=fail)
    with pytest.raises(RuntimeError, match=code), backend.open_stream("key"):
        pass


def test_missing_object_is_a_cache_miss():
    backend = MinIOStorageBackend.__new__(MinIOStorageBackend)
    backend._bucket = "test"

    def fail(*args):
        raise S3Error(None, "NoSuchKey", "missing", "key", "request", "host")

    backend._client = SimpleNamespace(get_object=fail)
    with pytest.raises(FileNotFoundError), backend.open_stream("key"):
        pass
