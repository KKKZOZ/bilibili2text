"""Persistent index for reproducible PNG exports with a fixed 14-day lifetime."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from b2t.storage.base import StoredArtifact

TTL_SECONDS = 14 * 24 * 60 * 60
CACHE_PREFIX = "cache/png"
RENDER_VERSION = "dpr1.5-colors128-dither0.3-v1"
logger = logging.getLogger(__name__)


class PngCache:
    def __init__(self, db_dir: str | Path):
        directory = Path(db_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "b2t_history.db"
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS png_cache (
                    storage_key TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    render_mode TEXT NOT NULL,
                    render_version TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_png_cache_lookup
                    ON png_cache(source_key, variant, render_mode, render_version);
                CREATE INDEX IF NOT EXISTS idx_png_cache_expiry ON png_cache(expires_at);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def register(
        self,
        artifact,
        *,
        source_key="",
        variant="",
        render_mode="",
        created_at=None,
        render_version=RENDER_VERSION,
    ):
        created_at = time.time() if created_at is None else created_at
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO png_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact.storage_key,
                    artifact.filename,
                    artifact.backend,
                    source_key,
                    variant or "",
                    render_mode or "",
                    render_version,
                    created_at,
                    created_at + TTL_SECONDS,
                ),
            )

    def store(
        self, storage, path: Path, *, output_dir, source_key, variant="", render_mode=""
    ):
        key = f"{CACHE_PREFIX}/{uuid4().hex}/{path.name}"
        if storage.persist_local_outputs:
            target = Path(output_dir).expanduser().resolve() / key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            path = target
        artifact = storage.store_file(path, object_key=key)
        try:
            self.register(
                artifact,
                source_key=source_key,
                variant=variant,
                render_mode=render_mode,
            )
        except Exception:
            storage.delete_file(artifact.storage_key)
            raise
        return artifact

    def find(self, storage, *, source_key, variant="", render_mode="", now=None):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM png_cache WHERE source_key=? AND variant=? "
                "AND render_mode=? AND render_version=? AND backend=? "
                "ORDER BY created_at DESC LIMIT 1",
                (
                    source_key,
                    variant or "",
                    render_mode or "",
                    RENDER_VERSION,
                    storage.backend_name,
                ),
            ).fetchone()
        if row is None:
            return None
        try:
            with storage.open_stream(row["storage_key"]):
                pass
        except FileNotFoundError:
            self.forget(row["storage_key"])
            return None
        return StoredArtifact(
            filename=row["filename"],
            storage_key=row["storage_key"],
            backend=row["backend"],
        )

    def expired(self, storage_key, *, now=None):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT expires_at FROM png_cache WHERE storage_key=?", (storage_key,)
            ).fetchone()
        return row is not None and row["expires_at"] <= (
            time.time() if now is None else now
        )

    def cleanup(self, storage, *, now=None):
        now = time.time() if now is None else now
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT storage_key FROM png_cache WHERE expires_at<=? AND backend=?",
                (now, storage.backend_name),
            ).fetchall()
        deleted = set()
        for row in rows:
            key = row["storage_key"]
            try:
                storage.delete_file(key)
            except FileNotFoundError:
                pass
            except Exception:
                logger.exception("PNG 缓存清理失败，将在下次重试: %s", key)
                continue
            self.forget(key)
            deleted.add(key)
        return deleted

    def forget(self, key):
        """Drop stale metadata after an object is confirmed missing."""

        with self.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='transcription_artifacts'"
            ).fetchone():
                run_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT run_id FROM transcription_artifacts WHERE storage_key=?",
                        (key,),
                    )
                ]
                conn.execute(
                    "DELETE FROM transcription_artifacts WHERE storage_key=?",
                    (key,),
                )
                conn.executemany(
                    "UPDATE transcription_runs SET file_count=(SELECT COUNT(*) FROM transcription_artifacts WHERE run_id=?) WHERE run_id=?",
                    [(r, r) for r in run_ids],
                )
            conn.execute("DELETE FROM png_cache WHERE storage_key=?", (key,))
