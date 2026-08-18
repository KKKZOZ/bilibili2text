"""Stock status cache helpers for rendered summary artifacts."""

from __future__ import annotations

import logging
import queue
import threading
import time
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
    timeout_seconds: float | None = None,
    prefer_baostock_for_a_shares: bool = False,
    max_workers: int = 1,
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
        fetched_list = _fetch_stock_daily_statuses(
            missing_symbols,
            as_of_date=as_of_date,
            timeout_seconds=timeout_seconds,
            prefer_baostock_for_a_shares=prefer_baostock_for_a_shares,
            max_workers=max_workers,
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


def _fetch_stock_daily_statuses(
    symbols: list[str],
    *,
    as_of_date: str | None,
    timeout_seconds: float | None,
    prefer_baostock_for_a_shares: bool,
    max_workers: int,
) -> list[StockDailyStatus]:
    if timeout_seconds is None:
        if prefer_baostock_for_a_shares:
            return fetch_stock_daily_status(
                symbols,
                as_of_date=as_of_date,
                prefer_baostock_for_a_shares=True,
            )
        return fetch_stock_daily_status(symbols, as_of_date=as_of_date)

    timeout = max(0.0, float(timeout_seconds))
    if timeout <= 0:
        return []

    deadline = time.monotonic() + timeout
    work_queue: queue.Queue[str] = queue.Queue()
    result_queue: queue.Queue[tuple[str, list[StockDailyStatus], Exception | None]] = (
        queue.Queue()
    )
    for symbol in symbols:
        work_queue.put(symbol)

    def _worker() -> None:
        while time.monotonic() < deadline:
            try:
                symbol = work_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if prefer_baostock_for_a_shares:
                    statuses = fetch_stock_daily_status(
                        [symbol],
                        as_of_date=as_of_date,
                        prefer_baostock_for_a_shares=True,
                    )
                else:
                    statuses = fetch_stock_daily_status(
                        [symbol],
                        as_of_date=as_of_date,
                    )
                result_queue.put((symbol, statuses, None))
            except Exception as exc:  # noqa: BLE001
                result_queue.put((symbol, [], exc))

    worker_count = min(len(symbols), max(1, int(max_workers)))
    for index in range(worker_count):
        thread = threading.Thread(
            target=_worker,
            name=f"b2t-stock-fetch-{index + 1}",
            daemon=True,
        )
        thread.start()

    pending = set(symbols)
    fetched: list[StockDailyStatus] = []
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            symbol, statuses, error = result_queue.get(timeout=remaining)
        except queue.Empty:
            break
        pending.discard(symbol)
        if error is not None:
            logger.warning("stock status fetch failed for %s: %s", symbol, error)
            continue
        fetched.extend(statuses)

    if pending:
        logger.warning(
            "stock status fetch timed out after %.1fs, pending=%s",
            timeout,
            ",".join(sorted(pending)),
        )
    return fetched


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
