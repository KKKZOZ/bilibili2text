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
    file_count    INTEGER NOT NULL DEFAULT 0,
    record_type   TEXT    NOT NULL DEFAULT 'transcription',
    fancy_html_status TEXT NOT NULL DEFAULT 'idle',
    fancy_html_error  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_bvid       ON transcription_runs(bvid);
CREATE INDEX IF NOT EXISTS idx_runs_created_at  ON transcription_runs(created_at);

CREATE TABLE IF NOT EXISTS transcription_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL REFERENCES transcription_runs(run_id),
    kind          TEXT    NOT NULL,
    filename      TEXT    NOT NULL,
    storage_key   TEXT    NOT NULL,
    backend       TEXT    NOT NULL,
    summary_preset  TEXT  NOT NULL DEFAULT '',
    summary_profile TEXT  NOT NULL DEFAULT ''
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
    record_type: str = "transcription"  # "transcription" | "rag_query"


@dataclass(frozen=True)
class HistoryArtifact:
    """One downloadable file within a run."""

    kind: str
    filename: str
    storage_key: str
    backend: str
    summary_preset: str = ""
    summary_profile: str = ""


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
    record_type: str = "transcription"
    fancy_html_status: str = "idle"
    fancy_html_error: str = ""


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
    def _normalize_artifact_kind(kind: str, filename: str) -> str:
        inferred = classify_artifact_filename(filename)
        normalized_kind = (kind or "").strip()
        if normalized_kind in {"", "file"} and inferred:
            return inferred
        return normalized_kind or inferred or "file"

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_SQL)
        # Backward-compatible migration for existing DB files.
        existing_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(transcription_artifacts)")
        }
        if "summary_preset" not in existing_columns:
            conn.execute(
                "ALTER TABLE transcription_artifacts "
                "ADD COLUMN summary_preset TEXT NOT NULL DEFAULT ''"
            )
        if "summary_profile" not in existing_columns:
            conn.execute(
                "ALTER TABLE transcription_artifacts "
                "ADD COLUMN summary_profile TEXT NOT NULL DEFAULT ''"
            )
        existing_run_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(transcription_runs)")
        }
        if "record_type" not in existing_run_columns:
            conn.execute(
                "ALTER TABLE transcription_runs "
                "ADD COLUMN record_type TEXT NOT NULL DEFAULT 'transcription'"
            )
        if "fancy_html_status" not in existing_run_columns:
            conn.execute(
                "ALTER TABLE transcription_runs "
                "ADD COLUMN fancy_html_status TEXT NOT NULL DEFAULT 'idle'"
            )
        if "fancy_html_error" not in existing_run_columns:
            conn.execute(
                "ALTER TABLE transcription_runs "
                "ADD COLUMN fancy_html_error TEXT NOT NULL DEFAULT ''"
            )

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
        record_type: str = "transcription",
        fancy_html_status: str | None = None,
        fancy_html_error: str | None = None,
    ) -> None:
        """Insert or replace a transcription run and its artifacts."""
        if created_at is None:
            created_at = datetime.now(tz=timezone.utc).isoformat()

        artifact_list = artifacts or []
        conn = self._conn()
        with conn:
            existing_artifact_meta = {
                str(row["storage_key"]): (
                    str(row["summary_preset"] or ""),
                    str(row["summary_profile"] or ""),
                )
                for row in conn.execute(
                    """\
                    SELECT storage_key, summary_preset, summary_profile
                    FROM transcription_artifacts
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchall()
            }
            existing_run_meta = conn.execute(
                """\
                SELECT fancy_html_status, fancy_html_error
                FROM transcription_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            persisted_fancy_html_status = (
                fancy_html_status
                if fancy_html_status is not None
                else (
                    str(existing_run_meta["fancy_html_status"])
                    if existing_run_meta is not None
                    else "idle"
                )
            )
            persisted_fancy_html_error = (
                fancy_html_error
                if fancy_html_error is not None
                else (
                    str(existing_run_meta["fancy_html_error"])
                    if existing_run_meta is not None
                    else ""
                )
            )
            conn.execute(
                """\
                INSERT INTO transcription_runs
                    (
                        run_id, bvid, title, author, pubdate, created_at,
                        has_summary, file_count, record_type, fancy_html_status, fancy_html_error
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    bvid        = excluded.bvid,
                    title       = excluded.title,
                    author      = excluded.author,
                    pubdate     = excluded.pubdate,
                    created_at  = excluded.created_at,
                    has_summary = excluded.has_summary,
                    file_count  = excluded.file_count,
                    record_type = excluded.record_type,
                    fancy_html_status = excluded.fancy_html_status,
                    fancy_html_error = excluded.fancy_html_error
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
                    record_type,
                    persisted_fancy_html_status,
                    persisted_fancy_html_error,
                ),
            )
            conn.execute(
                "DELETE FROM transcription_artifacts WHERE run_id = ?",
                (run_id,),
            )
            conn.executemany(
                """\
                INSERT INTO transcription_artifacts
                    (
                        run_id,
                        kind,
                        filename,
                        storage_key,
                        backend,
                        summary_preset,
                        summary_profile
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        a.kind,
                        a.filename,
                        a.storage_key,
                        a.backend,
                        (
                            a.summary_preset.strip()
                            or existing_artifact_meta.get(a.storage_key, ("", ""))[0]
                        ),
                        (
                            a.summary_profile.strip()
                            or existing_artifact_meta.get(a.storage_key, ("", ""))[1]
                        ),
                    )
                    for a in artifact_list
                ],
            )

    def list_runs(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str = "",
        record_type: str = "",
    ) -> HistoryPage:
        """Paginated listing with optional search on title/bvid/author."""
        conn = self._conn()

        conditions: list[str] = []
        params: list[str] = []
        query = search.strip()
        if query:
            conditions.append("(title LIKE ? OR bvid LIKE ? OR author LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        if record_type.strip():
            conditions.append("record_type = ?")
            params.append(record_type.strip())

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM transcription_runs {where}",
            params,
        ).fetchone()
        total: int = row["cnt"] if row else 0

        offset = (max(1, page) - 1) * page_size
        rows = conn.execute(
            f"""\
            SELECT run_id, bvid, title, author, pubdate, created_at, has_summary, file_count, record_type
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
                record_type=r["record_type"] or "transcription",
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
            SELECT
                run_id, bvid, title, author, pubdate, created_at, has_summary,
                record_type, fancy_html_status, fancy_html_error
            FROM transcription_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None

        artifact_rows = conn.execute(
            """\
            SELECT kind, filename, storage_key, backend, summary_preset, summary_profile
            FROM transcription_artifacts
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()

        artifacts = [
            HistoryArtifact(
                kind=self._normalize_artifact_kind(r["kind"], r["filename"]),
                filename=r["filename"],
                storage_key=r["storage_key"],
                backend=r["backend"],
                summary_preset=r["summary_preset"],
                summary_profile=r["summary_profile"],
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
            record_type=run_row["record_type"] or "transcription",
            fancy_html_status=run_row["fancy_html_status"] or "idle",
            fancy_html_error=run_row["fancy_html_error"] or "",
        )

    def update_run_fancy_html_status(
        self,
        run_id: str,
        *,
        status: str,
        error: str = "",
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """\
                UPDATE transcription_runs
                SET fancy_html_status = ?, fancy_html_error = ?
                WHERE run_id = ?
                """,
                (status.strip() or "idle", error.strip(), run_id),
            )

    def list_authors(self) -> list[str]:
        """Return distinct non-empty author names, sorted alphabetically."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT author FROM transcription_runs WHERE author != '' ORDER BY author"
        ).fetchall()
        return [str(r["author"]) for r in rows]

    def get_run_ids_for_authors(self, authors: list[str]) -> list[str]:
        """Return all run_ids whose author is in the given list."""
        if not authors:
            return []
        placeholders = ",".join("?" * len(authors))
        conn = self._conn()
        rows = conn.execute(
            f"SELECT run_id FROM transcription_runs WHERE author IN ({placeholders})",
            authors,
        ).fetchall()
        return [str(r["run_id"]) for r in rows]

    def count_runs(self, *, record_type: str = "") -> int:
        """Return total run count, optionally filtered by record type."""
        conn = self._conn()
        params: list[str] = []
        where = ""
        if record_type.strip():
            where = "WHERE record_type = ?"
            params.append(record_type.strip())
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM transcription_runs {where}",
            params,
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def has_summary_for_bvid(self, bvid: str) -> bool:
        """Return whether the given BV already has a summarized run."""
        normalized_bvid = bvid.strip()
        if not normalized_bvid:
            return False

        conn = self._conn()
        row = conn.execute(
            """\
            SELECT 1
            FROM transcription_runs
            WHERE bvid = ? AND has_summary = 1
            LIMIT 1
            """,
            (normalized_bvid,),
        ).fetchone()
        return row is not None

    def delete_run(self, run_id: str) -> list[HistoryArtifact]:
        """Delete a transcription run and return its artifacts for file cleanup."""
        conn = self._conn()

        # Get artifacts before deleting
        artifact_rows = conn.execute(
            """\
            SELECT kind, filename, storage_key, backend, summary_preset, summary_profile
            FROM transcription_artifacts
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

        artifacts = [
            HistoryArtifact(
                kind=self._normalize_artifact_kind(r["kind"], r["filename"]),
                filename=r["filename"],
                storage_key=r["storage_key"],
                backend=r["backend"],
                summary_preset=r["summary_preset"],
                summary_profile=r["summary_profile"],
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


def record_rag_query(
    *,
    db: "HistoryDB",
    question: str,
    answer_artifact: "HistoryArtifact",
    created_at: str | None = None,
) -> str:
    """Persist a RAG query + answer to the history DB. Returns run_id."""
    from uuid import uuid4  # noqa: PLC0415

    run_id = uuid4().hex
    title = question[:200]
    db.record_run(
        run_id=run_id,
        bvid="",
        title=title,
        created_at=created_at,
        has_summary=False,
        artifacts=[answer_artifact],
        record_type="rag_query",
    )
    return run_id


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
    *,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
) -> list[HistoryArtifact]:
    """Convert stored artifacts to history rows."""
    summary_kinds = {
        "summary",
        "summary_text",
        "summary_fancy_html",
        "summary_png",
        "summary_no_table_png",
        "summary_table_md",
        "summary_table_png",
        "summary_table_pdf",
    }
    cleaned_preset = (summary_preset or "").strip()
    cleaned_profile = (summary_profile or "").strip()

    return [
        HistoryArtifact(
            kind=kind,
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
            summary_preset=cleaned_preset if kind in summary_kinds else "",
            summary_profile=cleaned_profile if kind in summary_kinds else "",
        )
        for artifact in results.values()
        for kind in [classify_artifact_filename(artifact.filename) or "file"]
    ]


def record_pipeline_run(
    *,
    db: HistoryDB,
    bvid: str,
    results: Mapping[str, StoredArtifact],
    author: str = "",
    pubdate: str = "",
    created_at: str | None = None,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
    merge_existing_artifacts: bool = False,
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
    file_results = {k: v for k, v in results.items() if not k.startswith("_")}

    markdown = file_results.get("markdown")
    if markdown is None:
        return None

    run_id = infer_run_id(markdown.storage_key, bvid=bvid)
    title = infer_title(markdown.filename, bvid=bvid)
    artifacts = build_history_artifacts(
        file_results,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
    )
    if merge_existing_artifacts:
        existing = db.get_run_detail(run_id)
        if existing is not None:
            merged_artifacts: list[HistoryArtifact] = list(existing.artifacts)
            merged_artifacts.extend(artifacts)
            deduped_artifacts: list[HistoryArtifact] = []
            seen_storage_keys: set[str] = set()
            for artifact in merged_artifacts:
                if artifact.storage_key in seen_storage_keys:
                    continue
                seen_storage_keys.add(artifact.storage_key)
                deduped_artifacts.append(artifact)
            artifacts = deduped_artifacts
    has_summary = any(
        artifact.kind
        in {
            "summary",
            "summary_text",
            "summary_fancy_html",
            "summary_png",
            "summary_no_table_png",
            "summary_table_md",
            "summary_table_png",
            "summary_table_pdf",
        }
        for artifact in artifacts
    )

    db.record_run(
        run_id=run_id,
        bvid=bvid,
        title=title,
        author=author,
        pubdate=pubdate,
        created_at=created_at,
        has_summary=has_summary,
        artifacts=artifacts,
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
