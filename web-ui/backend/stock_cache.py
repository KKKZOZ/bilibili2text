"""Stock status cache helpers for rendered summary artifacts."""

from __future__ import annotations

import logging
from pathlib import Path

from b2t.history import HistoryDB
from b2t.stock_status import (
    StockDailyStatus,
    extract_stock_symbols,
    fetch_stock_daily_status,
)

logger = logging.getLogger(__name__)


def normalize_stock_cache_date(as_of_date: str | None) -> str:
    text = (as_of_date or "").strip()
    return text[:10] if text else "latest"


def get_or_fetch_stock_statuses(
    *,
    db: HistoryDB,
    bvid: str,
    as_of_date: str | None,
    markdown_paths: list[Path],
) -> dict[str, StockDailyStatus]:
    symbols = _extract_symbols_from_paths(markdown_paths)
    if not symbols:
        return {}

    cache_date = normalize_stock_cache_date(as_of_date)
    cached = db.get_stock_statuses(
        bvid=bvid,
        as_of_date=cache_date,
        symbols=symbols,
    )
    missing_symbols = [symbol for symbol in symbols if symbol not in cached]
    if not missing_symbols:
        return cached

    try:
        fetched_list = fetch_stock_daily_status(
            missing_symbols,
            as_of_date=as_of_date,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch stock status cache for %s: %s", bvid, exc)
        return cached

    fetched = {status.symbol: status for status in fetched_list}
    if fetched:
        db.upsert_stock_statuses(
            bvid=bvid,
            as_of_date=cache_date,
            statuses=fetched,
        )
    return {**cached, **fetched}


def get_cached_stock_statuses(
    *,
    db: HistoryDB,
    bvid: str,
    as_of_date: str | None,
    markdown_paths: list[Path],
) -> dict[str, StockDailyStatus]:
    symbols = _extract_symbols_from_paths(markdown_paths)
    if not symbols:
        return {}
    return db.get_stock_statuses(
        bvid=bvid,
        as_of_date=normalize_stock_cache_date(as_of_date),
        symbols=symbols,
    )


def _extract_symbols_from_paths(paths: list[Path]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        for symbol in extract_stock_symbols(content):
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return symbols
