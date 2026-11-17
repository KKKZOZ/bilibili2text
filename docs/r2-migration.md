# MinIO → Cloudflare R2

R2 uses the existing S3-compatible `minio` backend. Keeping this backend name and
all object keys preserves history references; D1 and ChromaDB are unchanged.
The source bucket is retained for rollback. Live R2 compatibility must be tested
before switching production, including multipart upload and signed audio URLs.

Create a private R2 bucket and bucket-scoped S3 read/write credentials. Store the
following in a private local file outside the repository with permissions `0600`:

```toml
[r2]
endpoint = "<account-id>.r2.cloudflarestorage.com"
bucket = "transcriptions"
access_key = "<R2 S3 access key ID>"
secret_key = "<R2 S3 secret access key>"
```

From the project root, preview and then copy:

```bash
uv run python -m scripts.migrate_to_r2 --target-config /private/path/r2.toml
uv run python -m scripts.migrate_to_r2 --target-config /private/path/r2.toml --apply
```

The script copies every object under the configured MinIO base prefix, including
converted exports, preserving object keys and content types. It downloads one
source object at a time to temporary disk, uploads it, then reads the destination
back and compares SHA-256 and byte length. Existing identical objects are verified
and skipped; conflicts fail without overwriting. It detects source changes during
the pass, but cannot prevent writes after the check. Stop backend/monitor writers
and perform a final pass before cutover. Allow temporary disk space for the largest
object and network traffic for source download plus destination verification.

Before switching, test the current storage adapter against R2: upload/read/delete,
listing, existing transcription discovery, a multipart audio upload, and signed
audio GET access. Test an actual transcription provider's access to signed audio
as part of the first post-cutover transcription.

Back up `config.toml` privately, then update only `[storage.minio]`:

- `endpoint`, `bucket`, `access_key`, `secret_key`: target values above.
- `secure = true`, `region = "auto"`, `auto_create_bucket = false`.
- Keep `base_prefix` unchanged and retain `storage.backend = "minio"`.

Restart backend and monitor, which cache storage clients. Verify old history
downloads, a new export, and a new transcription. Keep the source bucket until
verification completes. Rolling back after new R2 writes requires copying those
new objects back before returning to the original configuration.

R2 migration does not automatically expire exports. Configure a separate lifecycle
rule for `b2t/converted/` if desired; do not apply export expiry to original reports,
summaries, or audio. This procedure does not set any lifecycle rules.

References: [R2 S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/),
[R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).
