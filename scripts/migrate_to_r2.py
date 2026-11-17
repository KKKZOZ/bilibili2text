"""Copy MinIO objects to R2 without changing keys or deleting source objects."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
import tomllib
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from b2t.config import load_config


def stream_digest(client, bucket: str, key: str) -> tuple[str, int]:
    response = client.get_object(bucket, key)
    digest = hashlib.sha256()
    size = 0
    try:
        for chunk in response.stream(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        response.close()
        response.release_conn()
    return digest.hexdigest(), size


def fingerprint(info) -> tuple:
    return info.etag, info.size, info.last_modified


def copy_verified(source, target, source_bucket: str, target_bucket: str, key: str):
    before = source.stat_object(source_bucket, key)
    try:
        target.stat_object(target_bucket, key)
    except S3Error as exc:
        if exc.code not in {"NoSuchKey", "NoSuchObject", "NotFound"}:
            raise
    else:
        original = stream_digest(source, source_bucket, key)
        existing = stream_digest(target, target_bucket, key)
        if fingerprint(before) != fingerprint(source.stat_object(source_bucket, key)):
            raise RuntimeError(f"Source changed during verification: {key}")
        if original != existing:
            raise RuntimeError(f"Destination conflict; refusing to overwrite: {key}")
        return "verified existing", original[1]

    with tempfile.TemporaryDirectory(prefix="b2t-r2-migration-") as temporary:
        local = Path(temporary) / "object"
        source.fget_object(source_bucket, key, str(local))
        with local.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = local.stat().st_size
        if size != before.size or fingerprint(before) != fingerprint(
            source.stat_object(source_bucket, key)
        ):
            raise RuntimeError(f"Source changed during copy: {key}")
        metadata = {
            k: v
            for k, v in (before.metadata or {}).items()
            if k.lower().startswith("x-amz-meta-")
        }
        target.fput_object(
            target_bucket,
            key,
            str(local),
            content_type=before.content_type or "application/octet-stream",
            metadata=metadata,
        )
        if stream_digest(target, target_bucket, key) != (digest, size):
            raise RuntimeError(f"Destination SHA-256 verification failed: {key}")
        if fingerprint(before) != fingerprint(source.stat_object(source_bucket, key)):
            raise RuntimeError(f"Source changed during upload: {key}")
    return "copied and verified", size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--target-config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Copy; default only lists")
    args = parser.parse_args()
    config = load_config(args.config)
    if config.storage.backend != "minio":
        raise ValueError("Source must use the minio storage backend")
    source_config = config.storage.minio
    with args.target_config.open("rb") as stream:
        target_config = tomllib.load(stream)["r2"]
    endpoint = target_config["endpoint"].strip()
    if not endpoint.endswith(".r2.cloudflarestorage.com") or "/" in endpoint:
        raise ValueError("Use the R2 S3 endpoint hostname, without https:// or a path")
    target_bucket = target_config["bucket"].strip()
    if (source_config.endpoint.strip(), source_config.bucket.strip()) == (
        endpoint,
        target_bucket,
    ):
        raise ValueError("Source and destination must differ")
    source = Minio(
        source_config.endpoint.strip(),
        access_key=source_config.access_key,
        secret_key=source_config.secret_key,
        secure=source_config.secure,
        region=source_config.region.strip() or None,
    )
    target = Minio(
        endpoint,
        access_key=target_config["access_key"],
        secret_key=target_config["secret_key"],
        secure=True,
        region="auto",
    )
    if not target.bucket_exists(target_bucket):
        raise ValueError("Create the target R2 bucket before migrating")
    prefix = source_config.base_prefix.strip("/")
    prefix = f"{prefix}/" if prefix else ""
    objects = list(
        source.list_objects(source_config.bucket, prefix=prefix, recursive=True)
    )
    print(f"Objects: {len(objects)}; bytes: {sum(o.size for o in objects)}", flush=True)
    for item in objects:
        if args.apply:
            status, size = copy_verified(
                source, target, source_config.bucket, target_bucket, item.object_name
            )
            print(f"{status}: {item.object_name} ({size} bytes)", flush=True)
        else:
            print(f"Would copy: {item.object_name} ({item.size} bytes)")
    if args.apply:
        after = {
            o.object_name: fingerprint(o)
            for o in source.list_objects(
                source_config.bucket, prefix=prefix, recursive=True
            )
        }
        if after != {o.object_name: fingerprint(o) for o in objects}:
            raise RuntimeError(
                "Source listing changed; stop writers and rerun before switching"
            )
        print("All listed objects verified. Configuration has NOT been switched.")


if __name__ == "__main__":
    main()
