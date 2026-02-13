"""SQLite-backed metadata store and helpers for transcription history."""

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from b2t.storage.base import StoredArtifact, classify_artifact_filename

_DB_FILENAME = "b2t_history.db"
_RUN_ID_SUFFIX_PATTERN = re.compile(r"^-[0-9a-f]{8}(?:_|$)", re.IGNORECASE)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS transcription_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL UNIQUE,
    bvid          TEXT    NOT NULL,
    title         TEXT    NOT NULL DEFAULT '',
    author        TEXT    NOT NULL DEFAULT '',
    pubdate       TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    has_summary   INTEGER NOT NULL DEFAULT 0,
    file_count    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_bvid       ON transcription_runs(bvid);
CREATE INDEX IF NOT EXISTS idx_runs_created_at  ON transcription_runs(created_at);

CREATE TABLE IF NOT EXISTS transcription_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL REFERENCES transcription_runs(run_id),
    kind          TEXT    NOT NULL,
    filename      TEXT    NOT NULL,
    storage_key   TEXT    NOT NULL,
    backend       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON transcription_artifacts(run_id);
"""


@dataclass(frozen=True)
class HistoryItem:
    """Summary row returned by list queries."""

    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    file_count: int


@dataclass(frozen=True)
class HistoryArtifact:
    """One downloadable file within a run."""

    kind: str
    filename: str
    storage_key: str
    backend: str


@dataclass(frozen=True)
class HistoryDetail:
    """Full detail for a single run."""

    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    artifacts: list[HistoryArtifact]


@dataclass(frozen=True)
class HistoryPage:
    """Paginated result."""

    items: list[HistoryItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class HistoryDB:
    """Thread-safe SQLite metadata store.

    One connection per thread is maintained via ``threading.local()``.
    """

    def __init__(self, db_dir: Path | str) -> None:
        db_dir = Path(db_dir).expanduser().resolve()
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_dir / _DB_FILENAME
        self._local = threading.local()
        # Ensure schema on the calling thread.
        self._ensure_schema(self._conn())

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_SQL)

    def record_run(
        self,
        *,
        run_id: str,
        bvid: str,
        title: str,
        author: str = "",
        pubdate: str = "",
        created_at: str | None = None,
        has_summary: bool = False,
        artifacts: list[HistoryArtifact] | None = None,
    ) -> None:
        """Insert or replace a transcription run and its artifacts."""
        if created_at is None:
            created_at = datetime.now(tz=timezone.utc).isoformat()

        artifact_list = artifacts or []
        conn = self._conn()
        with conn:
            conn.execute(
                """\
                INSERT INTO transcription_runs
                    (run_id, bvid, title, author, pubdate, created_at, has_summary, file_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    bvid        = excluded.bvid,
                    title       = excluded.title,
                    author      = excluded.author,
                    pubdate     = excluded.pubdate,
                    created_at  = excluded.created_at,
                    has_summary = excluded.has_summary,
                    file_count  = excluded.file_count
                """,
                (
                    run_id,
                    bvid,
                    title,
                    author,
                    pubdate,
                    created_at,
                    int(has_summary),
                    len(artifact_list),
                ),
            )
            conn.execute(
                "DELETE FROM transcription_artifacts WHERE run_id = ?",
                (run_id,),
            )
            conn.executemany(
                """\
                INSERT INTO transcription_artifacts
                    (run_id, kind, filename, storage_key, backend)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (run_id, a.kind, a.filename, a.storage_key, a.backend)
                    for a in artifact_list
                ],
            )

    def list_runs(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str = "",
    ) -> HistoryPage:
        """Paginated listing with optional search on title/bvid."""
        conn = self._conn()

        where = ""
        params: list[str] = []
        query = search.strip()
        if query:
            where = "WHERE title LIKE ? OR bvid LIKE ?"
            like = f"%{query}%"
            params = [like, like]

        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM transcription_runs {where}",
            params,
        ).fetchone()
        total: int = row["cnt"] if row else 0

        offset = (max(1, page) - 1) * page_size
        rows = conn.execute(
            f"""\
            SELECT run_id, bvid, title, author, pubdate, created_at, has_summary, file_count
            FROM transcription_runs
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        items = [
            HistoryItem(
                run_id=r["run_id"],
                bvid=r["bvid"],
                title=r["title"],
                author=r["author"],
                pubdate=r["pubdate"],
                created_at=r["created_at"],
                has_summary=bool(r["has_summary"]),
                file_count=r["file_count"],
            )
            for r in rows
        ]

        return HistoryPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(offset + page_size) < total,
        )

    def get_run_detail(self, run_id: str) -> HistoryDetail | None:
        """Get full detail including artifacts for one run."""
        conn = self._conn()
        run_row = conn.execute(
            """\
            SELECT run_id, bvid, title, author, pubdate, created_at, has_summary
            FROM transcription_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None

        artifact_rows = conn.execute(
            """\
            SELECT kind, filename, storage_key, backend
            FROM transcription_artifacts
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

        artifacts = [
            HistoryArtifact(
                kind=r["kind"],
                filename=r["filename"],
                storage_key=r["storage_key"],
                backend=r["backend"],
            )
            for r in artifact_rows
        ]

        return HistoryDetail(
            run_id=run_row["run_id"],
            bvid=run_row["bvid"],
            title=run_row["title"],
            author=run_row["author"],
            pubdate=run_row["pubdate"],
            created_at=run_row["created_at"],
            has_summary=bool(run_row["has_summary"]),
            artifacts=artifacts,
        )

    def delete_run(self, run_id: str) -> list[HistoryArtifact]:
        """Delete a transcription run and return its artifacts for file cleanup."""
        conn = self._conn()

        # Get artifacts before deleting
        artifact_rows = conn.execute(
            """\
            SELECT kind, filename, storage_key, backend
            FROM transcription_artifacts
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

        artifacts = [
            HistoryArtifact(
                kind=r["kind"],
                filename=r["filename"],
                storage_key=r["storage_key"],
                backend=r["backend"],
            )
            for r in artifact_rows
        ]

        # Delete from database
        with conn:
            conn.execute(
                "DELETE FROM transcription_artifacts WHERE run_id = ?",
                (run_id,),
            )
            conn.execute(
                "DELETE FROM transcription_runs WHERE run_id = ?",
                (run_id,),
            )

        return artifacts


def infer_run_id(storage_key: str, *, bvid: str) -> str:
    """Infer run_id from storage key path."""
    normalized = storage_key.replace("\\", "/").strip("/")
    if not normalized:
        return bvid
    parts = normalized.split("/")
    if len(parts) < 2:
        return bvid
    parent = parts[-2].strip()
    return parent or bvid


def infer_title(filename: str, *, bvid: str) -> str:
    """Infer title from artifact filename like 'BV1xx_title_transcription.md'."""
    stem = Path(filename).stem
    for suffix in ("_summary_table", "_summary", "_transcription"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    bvid_lower = bvid.lower()
    if not stem.lower().startswith(bvid_lower):
        return stem if stem else bvid

    remainder = stem[len(bvid) :]
    if remainder.startswith("_"):
        remainder = remainder[1:]

    # Optional run suffix like "-a1b2c3d4" inserted before title.
    remainder = _RUN_ID_SUFFIX_PATTERN.sub("", remainder)
    if remainder.startswith("_"):
        remainder = remainder[1:]

    return remainder if remainder else bvid


def build_history_artifacts(
    results: Mapping[str, StoredArtifact],
) -> list[HistoryArtifact]:
    """Convert stored artifacts to history rows."""
    return [
        HistoryArtifact(
            kind=classify_artifact_filename(artifact.filename) or "file",
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
        )
        for artifact in results.values()
    ]


def record_pipeline_run(
    *,
    db: HistoryDB,
    bvid: str,
    results: Mapping[str, StoredArtifact],
    author: str = "",
    pubdate: str = "",
    created_at: str | None = None,
) -> str | None:
    """Persist one pipeline run to history DB and return run_id.

    Args:
        db: History database instance
        bvid: Bilibili video BV ID
        results: Mapping of artifact keys to StoredArtifact
        author: Video author name
        pubdate: Video publish date (YYYY-MM-DD HH:MM:SS format)
        created_at: Record creation timestamp (ISO format)

    Returns:
        run_id if successful, None otherwise
    """
    # Filter out metadata from results as it's not a file artifact
    file_results = {
        k: v for k, v in results.items() if not k.startswith("_")
    }

    markdown = file_results.get("markdown")
    if markdown is None:
        return None

    run_id = infer_run_id(markdown.storage_key, bvid=bvid)
    title = infer_title(markdown.filename, bvid=bvid)
    db.record_run(
        run_id=run_id,
        bvid=bvid,
        title=title,
        author=author,
        pubdate=pubdate,
        created_at=created_at,
        has_summary="summary" in file_results,
        artifacts=build_history_artifacts(file_results),
    )
    return run_id


__all__ = [
    "HistoryArtifact",
    "HistoryDB",
    "HistoryDetail",
    "HistoryItem",
    "HistoryPage",
    "build_history_artifacts",
    "infer_run_id",
    "infer_title",
    "record_pipeline_run",
]
