"""MinIO storage backend."""

from contextlib import contextmanager
from datetime import timedelta
import mimetypes
from pathlib import Path
from typing import BinaryIO, Iterator
import uuid

from minio import Minio
from minio.error import S3Error

from b2t.config import MinIOStorageConfig
from b2t.storage.base import (
    PublicURLStorageBackend,
    StoredArtifact,
    classify_artifact_filename,
)


class MinIOStorageBackend(PublicURLStorageBackend):
    backend_name = "minio"
    persist_local_outputs = False

    def __init__(self, config: MinIOStorageConfig) -> None:
        self._bucket = config.bucket.strip()
        self._base_prefix = config.base_prefix.strip("/")
        self._temporary_url_expire_seconds = config.temporary_url_expire_seconds
        self._client = Minio(
            endpoint=config.endpoint.strip(),
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region.strip() or None,
        )
        self._ensure_bucket(auto_create=config.auto_create_bucket)

    def _ensure_bucket(self, *, auto_create: bool) -> None:
        try:
            exists = self._client.bucket_exists(self._bucket)
        except S3Error as exc:
            raise RuntimeError(f"Failed to check MinIO bucket: {exc}") from exc

        if exists:
            return

        if not auto_create:
            raise RuntimeError(f"MinIO bucket does not exist: {self._bucket}")

        try:
            self._client.make_bucket(self._bucket)
        except S3Error as exc:
            raise RuntimeError(f"Failed to create MinIO bucket: {exc}") from exc

    def _resolve_object_key(self, object_key: str) -> str:
        key = object_key.strip("/")
        if not key:
            raise ValueError("MinIO object key cannot be empty")

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

    def _delete_object(self, object_key: str) -> None:
        self._client.remove_object(self._bucket, object_key)

    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")

        resolved_key = self._resolve_object_key(object_key)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        try:
            self._client.fput_object(
                bucket_name=self._bucket,
                object_name=resolved_key,
                file_path=str(path),
                content_type=content_type,
            )
        except S3Error as exc:
            raise RuntimeError(f"Failed to upload to MinIO: {exc}") from exc

        return StoredArtifact(
            filename=path.name,
            storage_key=resolved_key,
            backend=self.backend_name,
        )

    @contextmanager
    def open_stream(self, storage_key: str) -> Iterator[BinaryIO]:
        try:
            response = self._client.get_object(self._bucket, storage_key)
        except S3Error as exc:
            raise FileNotFoundError(
                f"MinIO object does not exist: {storage_key}"
            ) from exc

        try:
            yield response
        finally:
            response.close()
            response.release_conn()

    def delete_file(self, storage_key: str) -> None:
        """Delete an object from MinIO."""
        try:
            self._delete_object(storage_key)
        except S3Error as exc:
            raise RuntimeError(f"Failed to delete MinIO object: {exc}") from exc

    @contextmanager
    def temporary_public_url(
        self,
        file_path: Path,
        *,
        object_key_prefix: str = "temp-audio",
    ) -> Iterator[str]:
        file_path = Path(file_path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {file_path}")

        key = self._resolve_object_key(
            f"{object_key_prefix}/{uuid.uuid4().hex}-{file_path.name}"
        )
        content_type = (
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        )
        self._client.fput_object(
            bucket_name=self._bucket,
            object_name=key,
            file_path=str(file_path),
            content_type=content_type,
        )

        try:
            url = self._client.presigned_get_object(
                self._bucket,
                key,
                expires=timedelta(seconds=self._temporary_url_expire_seconds),
            )
            yield url
        finally:
            try:
                self._delete_object(key)
            except S3Error:
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

        try:
            objects = self._client.list_objects(
                self._bucket,
                prefix=prefix,
                recursive=True,
            )
        except S3Error:
            return []

        try:
            for obj in objects:
                object_name = getattr(obj, "object_name", "")
                if not object_name:
                    continue

                relative = self._strip_base_prefix(object_name)
                if "/" not in relative:
                    continue

                run_prefix, filename = relative.split("/", 1)
                if not run_prefix.lower().startswith(f"{bvid.lower()}-"):
                    continue

                artifact_key = classify_artifact_filename(filename)
                if artifact_key is None:
                    continue

                last_modified = getattr(obj, "last_modified", None)
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
                            storage_key=object_name,
                            backend=self.backend_name,
                        ),
                    )
                )
        except S3Error:
            return []

        artifact_items.sort(key=lambda item: item[0], reverse=True)
        artifacts: list[StoredArtifact] = []
        seen_keys: set[str] = set()
        for _, artifact in artifact_items:
            if artifact.storage_key in seen_keys:
                continue
            seen_keys.add(artifact.storage_key)
            artifacts.append(artifact)
        return artifacts
