"""Aliyun OSS storage backend."""

from contextlib import contextmanager
import mimetypes
from pathlib import Path
import tempfile
from typing import BinaryIO, Iterator
from urllib.parse import quote
import uuid

import alibabacloud_oss_v2 as oss

from b2t.config import AlicloudStorageConfig
from b2t.storage.base import (
    PublicURLStorageBackend,
    StoredArtifact,
    classify_artifact_filename,
)


class AlicloudStorageBackend(PublicURLStorageBackend):
    backend_name = "alicloud"
    persist_local_outputs = False

    def __init__(self, config: AlicloudStorageConfig) -> None:
        self._bucket = config.bucket.strip()
        self._region = config.region.strip()
        self._base_prefix = config.base_prefix.strip("/")
        self._public_base_url = config.public_base_url.strip().rstrip("/")
        self._temporary_prefix = config.temporary_prefix.strip("/")

        cfg = oss.config.Config(
            credentials_provider=oss.credentials.StaticCredentialsProvider(
                access_key_id=config.access_key_id,
                access_key_secret=config.access_key_secret,
            ),
            region=self._region,
        )
        self._client = oss.Client(cfg)
        self._ensure_bucket(auto_create=config.auto_create_bucket)

    def _ensure_bucket(self, *, auto_create: bool) -> None:
        exists = self._client.is_bucket_exist(self._bucket)
        if exists:
            return

        if not auto_create:
            raise RuntimeError(f"Aliyun OSS bucket does not exist: {self._bucket}")

        self._client.put_bucket(oss.PutBucketRequest(bucket=self._bucket))

    def _resolve_object_key(self, object_key: str) -> str:
        key = object_key.strip("/")
        if not key:
            raise ValueError("OSS object key cannot be empty")

        if self._base_prefix:
            return f"{self._base_prefix}/{key}"
        return key

    def _strip_base_prefix(self, object_key: str) -> str:
        if not self._base_prefix:
            return object_key
        prefix = f"{self._base_prefix}/"
        if object_key.startswith(prefix):
            return object_key[len(prefix) :]
        return object_key

    def _upload(
        self,
        file_path: Path,
        *,
        object_key: str,
        acl: str | None = None,
    ) -> None:
        content_type = mimetypes.guess_type(file_path.name)[0]
        request_kwargs: dict[str, str] = {
            "bucket": self._bucket,
            "key": object_key,
        }
        if acl:
            request_kwargs["acl"] = acl
        if content_type:
            request_kwargs["content_type"] = content_type

        self._client.put_object_from_file(
            oss.PutObjectRequest(**request_kwargs),
            str(file_path),
        )

    def _delete_object(self, object_key: str) -> None:
        self._client.delete_object(
            oss.DeleteObjectRequest(bucket=self._bucket, key=object_key)
        )

    def _build_public_url(self, object_key: str) -> str:
        encoded_key = quote(object_key, safe="/")
        if self._public_base_url:
            return f"{self._public_base_url}/{encoded_key}"
        return f"https://{self._bucket}.oss-{self._region}.aliyuncs.com/{encoded_key}"

    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")

        resolved_key = self._resolve_object_key(object_key)
        self._upload(path, object_key=resolved_key)

        return StoredArtifact(
            filename=path.name,
            storage_key=resolved_key,
            backend=self.backend_name,
        )

    @contextmanager
    def open_stream(self, storage_key: str) -> Iterator[BinaryIO]:
        with tempfile.NamedTemporaryFile(prefix="b2t-oss-", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            self._client.get_object_to_file(
                oss.GetObjectRequest(bucket=self._bucket, key=storage_key),
                str(temp_path),
            )
            with temp_path.open("rb") as stream:
                yield stream
        except Exception as exc:
            raise FileNotFoundError(
                f"OSS object does not exist or is not readable: {storage_key}"
            ) from exc
        finally:
            temp_path.unlink(missing_ok=True)

    def delete_file(self, storage_key: str) -> None:
        """Delete an object from Aliyun OSS."""
        try:
            self._delete_object(storage_key)
        except Exception as exc:
            raise RuntimeError(f"Failed to delete OSS object: {exc}") from exc

    @contextmanager
    def temporary_public_url(
        self,
        file_path: Path,
        *,
        object_key_prefix: str = "temp-audio",
    ) -> Iterator[str]:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")

        temp_prefix = (
            object_key_prefix.strip("/") or self._temporary_prefix or "temp-audio"
        )
        key = self._resolve_object_key(f"{temp_prefix}/{uuid.uuid4().hex}-{path.name}")
        self._upload(path, object_key=key, acl="public-read")

        try:
            yield self._build_public_url(key)
        finally:
            try:
                self._delete_object(key)
            except Exception:
                pass

    def find_existing_transcription(
        self,
        bvid: str,
    ) -> dict[str, StoredArtifact] | None:
        artifacts = self.list_existing_transcription_artifacts(bvid)
        if not artifacts:
            return None

        runs: dict[str, dict[str, StoredArtifact]] = {}
        run_order: list[str] = []
        for artifact in artifacts:
            relative = self._strip_base_prefix(artifact.storage_key)
            if "/" not in relative:
                continue
            run_prefix, _ = relative.split("/", 1)
            if run_prefix not in runs:
                runs[run_prefix] = {}
                run_order.append(run_prefix)

            artifact_key = classify_artifact_filename(artifact.filename)
            if artifact_key is None or artifact_key in runs[run_prefix]:
                continue
            runs[run_prefix][artifact_key] = artifact

        if not run_order:
            return None

        for run_prefix in run_order:
            grouped = runs[run_prefix]
            if "markdown" in grouped and "json" in grouped:
                return grouped
        for run_prefix in run_order:
            grouped = runs[run_prefix]
            if "markdown" in grouped:
                return grouped
        return None

    def list_existing_transcription_artifacts(
        self,
        bvid: str,
    ) -> list[StoredArtifact]:
        bvid = bvid.strip()
        if not bvid:
            return []

        prefix = self._resolve_object_key(f"{bvid}-")
        artifact_items: list[tuple[float, StoredArtifact]] = []

        continuation_token: str | None = None
        while True:
            request = oss.ListObjectsV2Request(
                bucket=self._bucket,
                prefix=prefix,
                continuation_token=continuation_token,
                max_keys=1000,
            )
            try:
                result = self._client.list_objects_v2(request)
            except Exception:
                return []

            contents = getattr(result, "contents", None) or []
            for item in contents:
                object_key = getattr(item, "key", "")
                if not object_key:
                    continue

                relative = self._strip_base_prefix(object_key)
                if "/" not in relative:
                    continue

                run_prefix, filename = relative.split("/", 1)
                if not run_prefix.lower().startswith(f"{bvid.lower()}-"):
                    continue

                artifact_key = classify_artifact_filename(filename)
                if artifact_key is None:
                    continue

                last_modified = getattr(item, "last_modified", None)
                modified_ts = (
                    float(last_modified.timestamp())
                    if last_modified is not None
                    else 0.0
                )
                artifact_items.append(
                    (
                        modified_ts,
                        StoredArtifact(
                            filename=filename,
                            storage_key=object_key,
                            backend=self.backend_name,
                        ),
                    )
                )

            is_truncated = bool(getattr(result, "is_truncated", False))
            if not is_truncated:
                break

            continuation_token = getattr(result, "next_continuation_token", None)
            if not continuation_token:
                break

        artifact_items.sort(key=lambda item: item[0], reverse=True)
        artifacts: list[StoredArtifact] = []
        seen_keys: set[str] = set()
        for _, artifact in artifact_items:
            if artifact.storage_key in seen_keys:
                continue
            seen_keys.add(artifact.storage_key)
            artifacts.append(artifact)
        return artifacts
