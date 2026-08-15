#!/usr/bin/env -S uv run python
"""Backfill missing Bilibili partition IDs in the history database."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from b2t.config import load_config  # noqa: E402
from b2t.download.metadata import VideoMetadata, get_video_metadata  # noqa: E402
from b2t.history import HistoryDB  # noqa: E402


@dataclass(frozen=True)
class BackfillResult:
    videos_found: int
    videos_updated: int
    rows_updated: int
    failures: int


def backfill_missing_categories(
    history_db: HistoryDB,
    *,
    dry_run: bool = False,
    metadata_fetcher: Callable[[str], VideoMetadata] = get_video_metadata,
) -> BackfillResult:
    """Fetch and persist tids for Bilibili history rows that do not have one."""
    bvids = history_db.list_bvids_missing_tid()
    videos_updated = 0
    rows_updated = 0
    failures = 0

    for bvid in bvids:
        try:
            metadata = metadata_fetcher(bvid)
        except Exception as exc:
            failures += 1
            print(f"[FAILED] {bvid}: {exc}", file=sys.stderr)
            continue

        if metadata.tid <= 0:
            failures += 1
            print(f"[FAILED] {bvid}: metadata did not contain a tid", file=sys.stderr)
            continue

        category_path = " / ".join(
            value for value in (metadata.parent_tname, metadata.tname) if value
        )
        category_label = category_path or f"tid={metadata.tid} (unmapped)"
        if dry_run:
            print(f"[DRY RUN] {bvid}: {metadata.tid} {category_label}")
            continue

        updated = history_db.update_tid_for_bvid(bvid, metadata.tid)
        videos_updated += int(updated > 0)
        rows_updated += updated
        print(f"[UPDATED] {bvid}: {metadata.tid} {category_label} ({updated} rows)")

    return BackfillResult(
        videos_found=len(bvids),
        videos_updated=videos_updated,
        rows_updated=rows_updated,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill missing Bilibili partition IDs in history records."
    )
    parser.add_argument(
        "--config",
        help="Path to config.toml. Defaults to B2T_CONFIG or ./config.toml.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print partition information without updating the database.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        history_db = HistoryDB(config.download.db_dir)
        result = backfill_missing_categories(history_db, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    mode = "Dry run" if args.dry_run else "Backfill"
    print(
        f"{mode} complete: {result.videos_found} videos found, "
        f"{result.videos_updated} videos updated, "
        f"{result.rows_updated} rows updated, {result.failures} failures."
    )
    return 1 if result.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
