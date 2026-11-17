"""Configure a 14-day lifecycle for PNG cache objects, preserving other rules."""

import argparse

from minio.commonconfig import ENABLED, Filter
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from b2t.config import load_config
from b2t.png_cache import CACHE_PREFIX, TTL_SECONDS
from b2t.storage import create_storage_backend

RULE_ID = "b2t-png-cache-14-days"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if config.storage.backend != "minio":
        raise ValueError("Requires the MinIO/S3 storage adapter (including R2)")
    storage = create_storage_backend(config)
    client = storage._client
    bucket = config.storage.minio.bucket
    prefix = (
        "/".join(
            filter(None, [config.storage.minio.base_prefix.strip("/"), CACHE_PREFIX])
        )
        + "/"
    )
    current = client.get_bucket_lifecycle(bucket)
    rules = [r for r in (current.rules if current else []) if r.rule_id != RULE_ID]
    rules.append(
        Rule(
            ENABLED,
            rule_filter=Filter(prefix=prefix),
            rule_id=RULE_ID,
            expiration=Expiration(days=TTL_SECONDS // 86400),
        )
    )
    print(
        f"Bucket={bucket}; prefix={prefix}; expiration=14 days; other rules preserved={len(rules) - 1}"
    )
    if not args.apply:
        return
    client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))
    saved = client.get_bucket_lifecycle(bucket)
    matches = [r for r in saved.rules if r.rule_id == RULE_ID]
    assert len(matches) == 1
    assert matches[0].expiration.days == 14 and matches[0].rule_filter.prefix == prefix
    print("Lifecycle rule saved and verified.")


if __name__ == "__main__":
    main()
