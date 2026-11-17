"""Move existing MinIO PNG exports into the 14-day cache, preserving their age."""

import argparse
import hashlib
import time
from pathlib import PurePosixPath

from minio.commonconfig import CopySource
from minio.error import S3Error

from b2t.config import load_config
from b2t.history import HistoryDB
from b2t.png_cache import CACHE_PREFIX, TTL_SECONDS, PngCache
from b2t.storage import StoredArtifact, create_storage_backend
from scripts.migrate_to_r2 import stream_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if config.storage.backend != "minio":
        raise ValueError("This migration currently supports MinIO/S3 storage only")
    storage = create_storage_backend(config)
    client = storage._client
    bucket = config.storage.minio.bucket
    base = config.storage.minio.base_prefix.strip("/")
    prefix = f"{base}/" if base else ""
    cache_prefix = f"{prefix}{CACHE_PREFIX}/"
    objects = [
        o
        for o in client.list_objects(bucket, prefix=prefix, recursive=True)
        if o.object_name.lower().endswith(".png")
        and not o.object_name.startswith(cache_prefix)
    ]
    now = time.time()
    expired = [o for o in objects if o.last_modified.timestamp() + TTL_SECONDS <= now]
    print(
        f"Legacy PNGs: {len(objects)}; expired: {len(expired)}; expired bytes: {sum(o.size for o in expired)}",
        flush=True,
    )
    if not args.apply:
        return
    HistoryDB(config.download.db_dir)
    cache = PngCache(config.download.db_dir)
    moved = 0
    for obj in objects:
        old_key = obj.object_name
        name = PurePosixPath(old_key).name
        created_at = obj.last_modified.timestamp()
        before = client.stat_object(bucket, old_key)
        # ListObjects includes fractional seconds; HEAD uses whole-second HTTP dates.
        if (before.etag, before.size, int(before.last_modified.timestamp())) != (
            obj.etag,
            obj.size,
            int(created_at),
        ):
            raise RuntimeError(f"Source changed; rerun migration: {old_key}")
        if created_at + TTL_SECONDS <= now:
            cache.register(
                StoredArtifact(filename=name, storage_key=old_key, backend="minio"),
                created_at=created_at,
                render_version="legacy",
            )
            continue
        digest = hashlib.sha256(old_key.encode()).hexdigest()
        new_key = f"{cache_prefix}legacy-{digest}/{name}"
        try:
            target = client.stat_object(bucket, new_key)
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise
            client.copy_object(
                bucket, new_key, CopySource(bucket, old_key, match_etag=obj.etag)
            )
            target = client.stat_object(bucket, new_key)
        if target.size != obj.size:
            raise RuntimeError(f"Copy size mismatch: {old_key}")
        if target.etag != obj.etag and stream_digest(
            client, bucket, old_key
        ) != stream_digest(client, bucket, new_key):
            raise RuntimeError(f"Copy content mismatch: {old_key}")
        cache.register(
            StoredArtifact(filename=name, storage_key=new_key, backend="minio"),
            created_at=created_at,
            render_version="legacy",
        )
        with cache.connection() as conn:
            conn.execute(
                "UPDATE transcription_artifacts SET storage_key=? WHERE storage_key=? AND backend='minio'",
                (new_key, old_key),
            )
            conn.execute(
                "UPDATE transcription_artifacts SET derived_from=? WHERE derived_from=?",
                (new_key, old_key),
            )
        client.remove_object(bucket, old_key)
        moved += 1
        if moved % 100 == 0:
            print(f"Moved and verified: {moved}", flush=True)
    deleted = cache.cleanup(storage, now=now)
    remaining = list(client.list_objects(bucket, prefix=prefix, recursive=True))
    legacy = [
        o.object_name
        for o in remaining
        if o.object_name.lower().endswith(".png")
        and not o.object_name.startswith(cache_prefix)
    ]
    print(
        f"Moved: {moved}; expired deleted: {len(deleted)}; remaining legacy PNGs: {len(legacy)}",
        flush=True,
    )
    print(f"Total remaining bytes: {sum(o.size for o in remaining)}", flush=True)
    if legacy:
        raise RuntimeError("Legacy PNGs remain; stop old writers and rerun migration")


if __name__ == "__main__":
    main()
