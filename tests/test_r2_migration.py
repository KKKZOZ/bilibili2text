from pathlib import Path
from types import SimpleNamespace

import pytest
from minio.error import S3Error

from scripts.migrate_to_r2 import copy_verified


class FakeClient:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.uploads = []
        self.corrupt_upload = False

    def stat_object(self, bucket, key):
        if key not in self.objects:
            raise S3Error(None, "NoSuchKey", "missing", key, "request", "host")
        return SimpleNamespace(
            etag=str(self.objects[key]),
            size=len(self.objects[key]),
            last_modified=1,
            content_type="image/png",
            metadata={"x-amz-meta-origin": "b2t"},
        )

    def get_object(self, bucket, key):
        return SimpleNamespace(
            stream=lambda size: iter([self.objects[key]]),
            close=lambda: None,
            release_conn=lambda: None,
        )

    def fget_object(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])

    def fput_object(self, bucket, key, path, **kwargs):
        self.uploads.append((key, kwargs))
        self.objects[key] = (
            b"corrupt" if self.corrupt_upload else Path(path).read_bytes()
        )


def test_copy_preserves_key_content_and_metadata_and_can_resume():
    source = FakeClient({"b2t/example.png": b"image"})
    target = FakeClient({})
    assert copy_verified(source, target, "source", "target", "b2t/example.png") == (
        "copied and verified",
        5,
    )
    assert target.objects == source.objects
    assert target.uploads[0][1] == {
        "content_type": "image/png",
        "metadata": {"x-amz-meta-origin": "b2t"},
    }
    assert copy_verified(source, target, "source", "target", "b2t/example.png") == (
        "verified existing",
        5,
    )
    assert len(target.uploads) == 1


def test_destination_conflict_is_not_overwritten():
    source, target = FakeClient({"key": b"new"}), FakeClient({"key": b"old"})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        copy_verified(source, target, "source", "target", "key")
    assert target.objects["key"] == b"old"
    assert not target.uploads


def test_corrupted_upload_fails_verification():
    source, target = FakeClient({"key": b"image"}), FakeClient({})
    target.corrupt_upload = True
    with pytest.raises(RuntimeError, match="SHA-256 verification failed"):
        copy_verified(source, target, "source", "target", "key")
    assert source.objects["key"] == b"image"


def test_changing_source_fails_before_upload():
    source, target = FakeClient({"key": b"before"}), FakeClient({})

    def changed_download(bucket, key, path):
        source.objects[key] = b"after"
        Path(path).write_bytes(b"after")

    source.fget_object = changed_download
    with pytest.raises(RuntimeError, match="Source changed"):
        copy_verified(source, target, "source", "target", "key")
    assert not target.uploads
