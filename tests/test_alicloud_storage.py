from datetime import timedelta
from types import SimpleNamespace

import alibabacloud_oss_v2 as oss
import pytest

from b2t.storage.alicloud_client import AlicloudStorageBackend


class _FakeClient:
    def __init__(self, *, presign_error: Exception | None = None) -> None:
        self.presign_error = presign_error
        self.upload_requests = []
        self.presign_requests = []
        self.presign_kwargs = []
        self.deleted_keys = []

    def put_object_from_file(self, request, file_path: str) -> None:
        self.upload_requests.append((request, file_path))

    def presign(self, request, **kwargs):
        self.presign_requests.append(request)
        self.presign_kwargs.append(kwargs)
        if self.presign_error is not None:
            raise self.presign_error
        return SimpleNamespace(url="https://signed.example.com/audio?signature=test")

    def delete_object(self, request) -> None:
        self.deleted_keys.append(request.key)


def _backend(client: _FakeClient) -> AlicloudStorageBackend:
    backend = AlicloudStorageBackend.__new__(AlicloudStorageBackend)
    backend._bucket = "private-bucket"
    backend._region = "cn-shanghai"
    backend._base_prefix = "b2t"
    backend._public_base_url = ""
    backend._temporary_prefix = "temp-audio"
    backend._temporary_url_expire_seconds = 3600
    backend._client = client
    return backend


def test_temporary_public_url_uses_presigned_get_and_deletes_object(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    client = _FakeClient()
    backend = _backend(client)

    with backend.temporary_public_url(audio_path) as url:
        assert url == "https://signed.example.com/audio?signature=test"
        assert client.deleted_keys == []

    upload_request, uploaded_path = client.upload_requests[0]
    presign_request = client.presign_requests[0]
    assert upload_request.bucket == "private-bucket"
    assert upload_request.key.startswith("b2t/temp-audio/")
    assert getattr(upload_request, "acl", None) is None
    assert uploaded_path == str(audio_path)
    assert isinstance(presign_request, oss.GetObjectRequest)
    assert presign_request.bucket == "private-bucket"
    assert presign_request.key == upload_request.key
    assert client.presign_kwargs == [{"expires": timedelta(seconds=3600)}]
    assert client.deleted_keys == [upload_request.key]


def test_temporary_public_url_deletes_object_when_presign_fails(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    client = _FakeClient(presign_error=RuntimeError("presign failed"))
    backend = _backend(client)

    with pytest.raises(RuntimeError, match="presign failed"):
        with backend.temporary_public_url(audio_path):
            pass

    upload_request, _ = client.upload_requests[0]
    assert client.deleted_keys == [upload_request.key]
