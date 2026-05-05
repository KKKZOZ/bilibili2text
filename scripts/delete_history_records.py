#!/usr/bin/env python3
"""Delete local system records by Bilibili BV id or history run_id."""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from b2t.config import load_config  # noqa: E402
from b2t.history import HistoryDB  # noqa: E402
from b2t.storage import StoredArtifact, create_storage_backend  # noqa: E402

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_HISTORY_FRAGMENT_RE = re.compile(r"(?:^|[#/])history/([^/?#]+)", re.IGNORECASE)
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$|^BV[0-9A-Za-z]{10}-[0-9a-f]{8}$")
_DB_FILENAME = "b2t_history.db"


@dataclass
class CleanupPlan:
    target: str
    target_type: str
    bvid: str = ""
    run_ids: list[str] = field(default_factory=list)
    artifacts: list[StoredArtifact] = field(default_factory=list)
    local_dirs: list[Path] = field(default_factory=list)


def _parse_target(raw: str) -> tuple[str, str]:
    value = raw.strip()
    if not value:
        raise ValueError("Target cannot be empty")

    history_match = _HISTORY_FRAGMENT_RE.search(value)
    if history_match:
        return "run_id", history_match.group(1)

    if _RUN_ID_RE.fullmatch(value):
        return "run_id", value

    bvid_match = _BVID_RE.fullmatch(value)
    if bvid_match:
        return "bvid", bvid_match.group(1)

    url_bvid_match = _BVID_RE.search(value)
    if url_bvid_match:
        return "bvid", url_bvid_match.group(1)

    raise ValueError(f"Invalid BV id, history run_id, or history URL: {raw}")


def _history_db_path(db_dir: str | Path) -> Path:
    return Path(db_dir).expanduser().resolve() / _DB_FILENAME


def _find_run_ids(db_path: Path, bvid: str) -> list[str]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT run_id
            FROM transcription_runs
            WHERE lower(bvid) = lower(?)
            ORDER BY created_at DESC
            """,
            (bvid,),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["run_id"]) for row in rows]


def _history_detail_artifacts(history_db: HistoryDB, run_ids: list[str]) -> tuple[str, list[StoredArtifact]]:
    bvid = ""
    artifacts: list[StoredArtifact] = []
    for run_id in run_ids:
        detail = history_db.get_run_detail(run_id)
        if detail is None:
            continue
        if not bvid and detail.bvid:
            bvid = detail.bvid
        artifacts.extend(
            StoredArtifact(
                filename=artifact.filename,
                storage_key=artifact.storage_key,
                backend=artifact.backend,
            )
            for artifact in detail.artifacts
        )
    return bvid, artifacts


def _dedupe_artifacts(artifacts: list[StoredArtifact]) -> list[StoredArtifact]:
    deduped: list[StoredArtifact] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact.backend, artifact.storage_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _find_local_dirs(output_dir: str | Path, bvid: str) -> list[Path]:
    root = Path(output_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []
    bvid_lower = bvid.lower()
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.lower().startswith(bvid_lower)
    )


def _build_plan(
    config_path: str | None,
    *,
    target_type: str,
    target: str,
) -> tuple[CleanupPlan, object]:
    config = load_config(config_path)
    history_db = HistoryDB(config.download.db_dir)

    if target_type == "bvid":
        bvid = target
        run_ids = _find_run_ids(_history_db_path(config.download.db_dir), bvid)
    elif target_type == "run_id":
        detail = history_db.get_run_detail(target)
        run_ids = [target] if detail is not None else []
        bvid = detail.bvid if detail is not None else ""
    else:
        raise ValueError(f"Unsupported target type: {target_type}")

    detail_bvid, artifacts = _history_detail_artifacts(history_db, run_ids)
    bvid = bvid or detail_bvid

    if bvid:
        try:
            storage_backend = create_storage_backend(config)
            artifacts.extend(storage_backend.list_existing_transcription_artifacts(bvid))
        except Exception as exc:
            print(f"Warning: failed to list storage artifacts for {bvid}: {exc}")

    plan = CleanupPlan(
        target=target,
        target_type=target_type,
        bvid=bvid,
        run_ids=run_ids,
        artifacts=_dedupe_artifacts(artifacts),
        local_dirs=_find_local_dirs(config.download.output_dir, bvid) if bvid else [],
    )
    return plan, config


def _delete_rag_runs(config, run_ids: list[str]) -> tuple[int, list[str]]:
    if not run_ids:
        return 0, []
    try:
        from b2t.rag.store import RagStore

        store = RagStore(
            chroma_dir=config.rag.chroma_dir,
            collection_name=config.rag.collection_name,
        )
    except Exception as exc:
        return 0, [f"RAG store init failed: {exc}"]

    deleted = 0
    failures: list[str] = []
    for run_id in run_ids:
        try:
            store.delete_run(run_id)
            deleted += 1
        except Exception as exc:
            failures.append(f"{run_id}: {exc}")
    return deleted, failures


def _print_plan(plan: CleanupPlan, *, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "DELETE"
    print(f"[{mode}] Target: {plan.target_type}={plan.target}")
    if plan.bvid:
        print(f"BV: {plan.bvid}")
    print(f"History runs: {len(plan.run_ids)}")
    for run_id in plan.run_ids:
        print(f"  - {run_id}")
    print(f"Storage artifacts: {len(plan.artifacts)}")
    for artifact in plan.artifacts:
        print(f"  - [{artifact.backend}] {artifact.storage_key}")
    print(f"Local directories: {len(plan.local_dirs)}")
    for directory in plan.local_dirs:
        print(f"  - {directory}")


def _delete_plan(plan: CleanupPlan, config) -> int:
    history_db = HistoryDB(config.download.db_dir)

    deleted_artifacts = 0
    failures: list[str] = []
    try:
        storage_backend = create_storage_backend(config)
    except Exception as exc:
        storage_backend = None
        failures.append(f"storage backend init: {exc}")

    if storage_backend is not None:
        for artifact in plan.artifacts:
            try:
                storage_backend.delete_file(artifact.storage_key)
                deleted_artifacts += 1
            except Exception as exc:
                failures.append(f"artifact {artifact.storage_key}: {exc}")

    deleted_dirs = 0
    for directory in plan.local_dirs:
        try:
            if directory.exists():
                shutil.rmtree(directory)
                deleted_dirs += 1
        except Exception as exc:
            failures.append(f"directory {directory}: {exc}")

    deleted_runs = 0
    for run_id in plan.run_ids:
        try:
            history_db.delete_run(run_id)
            deleted_runs += 1
        except Exception as exc:
            failures.append(f"history run {run_id}: {exc}")

    deleted_rag_runs, rag_failures = _delete_rag_runs(config, plan.run_ids)
    failures.extend(f"rag {failure}" for failure in rag_failures)

    print(
        "Deleted "
        f"{deleted_runs} history runs, "
        f"{deleted_artifacts} storage artifacts, "
        f"{deleted_dirs} local directories, "
        f"{deleted_rag_runs} RAG run indexes."
    )
    if failures:
        print("Failures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete records and files by BV id, history run_id, or history URL."
    )
    parser.add_argument("target", help="BV id, history run_id, or URL containing #/history/<run_id>")
    parser.add_argument(
        "--config",
        help="Path to config.toml. Defaults to B2T_CONFIG or ./config.toml.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag the script only prints a dry run.",
    )
    args = parser.parse_args(argv)

    try:
        target_type, target = _parse_target(args.target)
        plan, config = _build_plan(
            args.config,
            target_type=target_type,
            target=target,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    _print_plan(plan, dry_run=not args.yes)
    if not args.yes:
        print("Run again with --yes to delete these records.")
        return 0

    return _delete_plan(plan, config)


if __name__ == "__main__":
    raise SystemExit(main())
