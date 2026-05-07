"""Render stock summary tables with market status data."""

from __future__ import annotations

from dataclasses import dataclass
import html
import logging
import math
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_STOCK_CODE_RE = re.compile(
    r"(?<![A-Z0-9])((?:(?:[03468]\d{5})(?:\.(?:SH|SZ|BJ))?)|(?:\d{5}\.HK))(?![A-Z0-9])",
    re.IGNORECASE,
)

_SUPPORTED_SUFFIXES = {"SH", "SZ", "BJ", "HK"}
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
_MARKDOWN_INLINE_MARKER_RE = re.compile(r"(\*\*|__|`|~~)")

@dataclass(frozen=True)
class StockDailyStatus:
    symbol: str
    name: str
    trade_date: str
    close: str
    change: str
    pct_change: str
    market_cap: str
    pe: str
    volume: str
    amount: str
    direction: str


def extract_stock_symbols(markdown: str) -> list[str]:
    """Extract unique A-share stock symbols from Markdown table lines."""
    symbols: list[str] = []
    seen: set[str] = set()

    for table_match in _TABLE_LINE_RE.finditer(markdown):
        for code_match in _STOCK_CODE_RE.finditer(table_match.group(0)):
            symbol = _normalize_symbol(code_match.group(1))
            if symbol is None or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)

    return symbols


def build_stock_table_cards_html(
    markdown: str,
    *,
    as_of_date: date | datetime | str | None = None,
) -> str:
    """Render a Markdown stock table as compact HTML cards with baostock data."""
    rows = _parse_markdown_table(markdown)
    if not rows:
        return ""

    symbols = extract_stock_symbols(markdown)
    statuses: list[StockDailyStatus] = []
    if symbols:
        try:
            statuses = fetch_stock_daily_status(symbols, as_of_date=as_of_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch stock status data: %s", exc)
    status_by_symbol = {status.symbol: status for status in statuses}

    cards = "\n".join(
        _render_table_card(row, _find_status_for_table_row(row.raw, status_by_symbol))
        for row in rows
    )
    return f"""
<section class="stock-table-cards">
{cards}
</section>
""".strip()


@dataclass(frozen=True)
class StockTableRow:
    raw: str
    values: dict[str, str]


def fetch_stock_daily_status(
    symbols: list[str],
    *,
    count: int = 1,
    as_of_date: date | datetime | str | None = None,
) -> list[StockDailyStatus]:
    """Fetch daily K-line and valuation data at or before the video publish date."""
    if not symbols:
        return []

    effective_datetime = _parse_as_of_datetime(as_of_date)
    effective_date = (
        effective_datetime.date()
        if effective_datetime is not None
        else (_parse_as_of_date(as_of_date) or date.today())
    )
    statuses: list[StockDailyStatus] = []
    for symbol in symbols:
        try:
            status = _fetch_status_for_symbol(symbol, effective_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock status fetch failed for %s: %s", symbol, exc)
            continue
        if status is not None and not _is_stale_after_market_close(
            symbol,
            status,
            effective_datetime,
        ):
            statuses.append(status)
    return statuses


def _fetch_status_for_symbol(
    symbol: str,
    as_of_date: date,
) -> StockDailyStatus | None:
    return _fetch_yfinance_status_for_symbol(symbol, as_of_date)


def _fetch_yfinance_status_for_symbol(
    symbol: str,
    as_of_date: date,
) -> StockDailyStatus | None:
    yahoo_symbol = _to_yfinance_symbol(symbol)
    if not yahoo_symbol:
        return None
    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance unavailable: %s", exc)
        return None

    try:
        ticker = yf.Ticker(yahoo_symbol)
        history = ticker.history(
            period="60d",
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        if history.empty:
            return None

        selected_position = None
        for position, index in enumerate(history.index):
            trade_date = _yfinance_index_to_date(index)
            if trade_date is not None and trade_date <= as_of_date:
                selected_position = position
        if selected_position is None:
            return None

        row = history.iloc[selected_position]
        previous_row = (
            history.iloc[selected_position - 1] if selected_position > 0 else None
        )
        info = ticker.info or {}
        return _yfinance_row_to_status(
            symbol,
            row,
            previous_row,
            info,
            _yfinance_index_to_date(history.index[selected_position]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance query failed for %s: %s", symbol, exc)
        return None


def _to_yfinance_symbol(symbol: str) -> str:
    code, _, suffix = symbol.upper().partition(".")
    if not code or suffix not in _SUPPORTED_SUFFIXES:
        return ""
    if suffix == "SH":
        return f"{code}.SS"
    if suffix == "SZ":
        return f"{code}.SZ"
    if suffix == "HK":
        return f"{code[-4:]}.HK"
    return ""


def _yfinance_index_to_date(value: Any) -> date | None:
    try:
        if hasattr(value, "date"):
            return value.date()
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def _fetch_baostock_status_for_symbol(
    symbol: str,
    as_of_date: date,
) -> StockDailyStatus | None:
    try:
        import baostock as bs
    except Exception as exc:  # noqa: BLE001
        logger.warning("baostock unavailable: %s", exc)
        return None

    login_result = bs.login()
    if getattr(login_result, "error_code", "") != "0":
        logger.warning("baostock login failed: %s", getattr(login_result, "error_msg", ""))
        return None

    try:
        row = _fetch_baostock_daily_row(bs, symbol, as_of_date)
        if not row:
            return None
        basic = _fetch_baostock_basic_row(bs, symbol)
        profit = _fetch_baostock_profit_row(bs, symbol, row)
        return _baostock_row_to_status(symbol, row, basic, profit)
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


@lru_cache(maxsize=1)
def _tickflow_client():
    from tickflow import TickFlow

    return TickFlow.free()


def _fetch_tickflow_hk_status_for_symbol(
    symbol: str,
    as_of_date: date,
) -> StockDailyStatus | None:
    try:
        client = _tickflow_client()
        row = _fetch_tickflow_daily_row(client, symbol, as_of_date)
        if not row:
            return None
        instrument = _fetch_tickflow_instrument(client, symbol)
        return _tickflow_row_to_status(symbol, row, instrument)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tickflow query failed for %s: %s", symbol, exc)
        return None


def _fetch_tickflow_daily_row(
    client: Any,
    symbol: str,
    as_of_date: date,
) -> dict[str, Any]:
    end_time = _tickflow_end_timestamp_ms(as_of_date)
    data = client.klines.get(
        symbol,
        period="1d",
        count=45,
        end_time=end_time,
        adjust="none",
    )
    timestamps = list(data.get("timestamp") or [])
    if not timestamps:
        return {}

    selected_index = len(timestamps) - 1
    for index, timestamp in enumerate(timestamps):
        trade_date = _tickflow_timestamp_to_date(timestamp)
        if trade_date is not None and trade_date <= as_of_date:
            selected_index = index

    def at(key: str) -> Any:
        values = data.get(key) or []
        return values[selected_index] if selected_index < len(values) else None

    return {
        "date": _tickflow_timestamp_to_date(timestamps[selected_index]),
        "close": at("close"),
        "preclose": at("prev_close") or _previous_tickflow_close(data, selected_index),
        "volume": at("volume"),
        "amount": at("amount"),
    }


def _fetch_tickflow_instrument(client: Any, symbol: str) -> dict[str, Any]:
    instrument = client.instruments.get(symbol)
    return instrument if isinstance(instrument, dict) else {}


def _tickflow_timestamp_to_date(timestamp: Any) -> date | None:
    try:
        return datetime.fromtimestamp(
            float(timestamp) / 1000,
            ZoneInfo("Asia/Hong_Kong"),
        ).date()
    except (TypeError, ValueError, OSError):
        return None


def _tickflow_end_timestamp_ms(as_of_date: date) -> int:
    dt = datetime.combine(
        as_of_date + timedelta(days=1),
        time.min,
        tzinfo=ZoneInfo("Asia/Hong_Kong"),
    )
    return int(dt.timestamp() * 1000)


def _previous_tickflow_close(data: dict[str, Any], selected_index: int) -> Any:
    close_values = data.get("close") or []
    previous_index = selected_index - 1
    if previous_index < 0 or previous_index >= len(close_values):
        return None
    return close_values[previous_index]


def _normalize_symbol(raw: str) -> str | None:
    value = raw.strip().upper()
    if "." in value:
        code, suffix = value.split(".", 1)
        if suffix in _SUPPORTED_SUFFIXES:
            return f"{code}.{suffix}"
        return None

    if len(value) != 6 or not value.isdigit():
        return None
    if value.startswith("6"):
        return f"{value}.SH"
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    if value.startswith(("4", "8")):
        return f"{value}.BJ"
    return None


def _baostock_row_to_status(
    symbol: str,
    row: dict[str, Any],
    basic: dict[str, Any],
    profit: dict[str, Any],
) -> StockDailyStatus:
    close = _first_value(row, "close")
    previous_close = _first_value(row, "preclose")
    change = _first_value(row, "change", "chg", "涨跌")
    pct_change = _first_value(row, "pctChg")
    pe = _first_value(row, "peTTM")

    if _is_blank(change) and not _is_blank(close) and not _is_blank(previous_close):
        change = _to_float(close) - _to_float(previous_close)
    if _is_blank(pct_change) and not _is_blank(change) and not _is_blank(previous_close):
        previous = _to_float(previous_close)
        if previous:
            pct_change = _to_float(change) / previous * 100
    total_shares = _first_value(profit, "totalShare")
    market_cap = None
    if not _is_blank(close) and not _is_blank(total_shares):
        market_cap = _to_float(close) * _to_float(total_shares)
    direction = _direction(change)

    return StockDailyStatus(
        symbol=symbol,
        name=str(_first_value(basic, "code_name") or symbol),
        trade_date=_format_date(_first_value(row, "date")),
        close=_format_number(close),
        change=_format_signed_number(change),
        pct_change=_format_pct(pct_change),
        market_cap=_format_large_number(market_cap),
        pe=_format_number(pe),
        volume=_format_large_number(_first_value(row, "volume")),
        amount=_format_large_number(_first_value(row, "amount")),
        direction=direction,
    )


def _tickflow_row_to_status(
    symbol: str,
    row: dict[str, Any],
    instrument: dict[str, Any],
) -> StockDailyStatus:
    close = _first_value(row, "close")
    previous_close = _first_value(row, "preclose", "prev_close")
    change = None
    pct_change = None
    if not _is_blank(close) and not _is_blank(previous_close):
        change = _to_float(close) - _to_float(previous_close)
        previous = _to_float(previous_close)
        if previous:
            pct_change = change / previous * 100

    total_shares = _first_value(
        instrument.get("ext", {}) if isinstance(instrument.get("ext"), dict) else {},
        "total_shares",
        "totalShare",
    )
    market_cap = None
    if not _is_blank(close) and not _is_blank(total_shares):
        market_cap = _to_float(close) * _to_float(total_shares)

    # TickFlow free exposes HK daily K-lines and instrument share count, but not
    # financial metrics. Keep PE blank unless we switch to a permitted data source.
    return StockDailyStatus(
        symbol=symbol,
        name=str(_first_value(instrument, "name") or symbol),
        trade_date=_format_date(_first_value(row, "date")),
        close=_format_number(close),
        change=_format_signed_number(change),
        pct_change=_format_pct(pct_change),
        market_cap=_format_large_number(market_cap),
        pe="-",
        volume=_format_large_number(_first_value(row, "volume")),
        amount=_format_large_number(_first_value(row, "amount")),
        direction=_direction(change),
    )


def _yfinance_row_to_status(
    symbol: str,
    row: Any,
    previous_row: Any,
    info: dict[str, Any],
    trade_date: date | None,
) -> StockDailyStatus:
    close = _first_value(row.to_dict(), "Close", "close")
    previous_close = (
        _first_value(previous_row.to_dict(), "Close", "close")
        if previous_row is not None
        else None
    )
    change = None
    pct_change = None
    if not _is_blank(close) and not _is_blank(previous_close):
        change = _to_float(close) - _to_float(previous_close)
        previous = _to_float(previous_close)
        if previous:
            pct_change = change / previous * 100

    amount = None
    volume = _first_value(row.to_dict(), "Volume", "volume")
    if not _is_blank(close) and not _is_blank(volume):
        amount = _to_float(close) * _to_float(volume)

    name = (
        _first_value(info, "shortName", "longName", "displayName", "symbol")
        or symbol
    )
    pe = _first_value(info, "trailingPE", "forwardPE")

    return StockDailyStatus(
        symbol=symbol,
        name=str(name),
        trade_date=trade_date.isoformat() if trade_date is not None else "-",
        close=_format_number(close),
        change=_format_signed_number(change),
        pct_change=_format_pct(pct_change),
        market_cap=_format_large_number(_first_value(info, "marketCap")),
        pe=_format_number(pe),
        volume=_format_large_number(volume),
        amount=_format_large_number(amount),
        direction=_direction(change),
    )


def _parse_as_of_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _parse_as_of_datetime(value: date | datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None or isinstance(value, date):
        return None

    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.time() != time.min else None


def _is_stale_after_market_close(
    symbol: str,
    status: StockDailyStatus,
    as_of_datetime: datetime | None,
) -> bool:
    if as_of_datetime is None or as_of_datetime.weekday() >= 5:
        return False

    close_time = time(16, 0) if symbol.upper().endswith(".HK") else time(15, 0)
    if as_of_datetime.time() < close_time:
        return False

    try:
        trade_date = datetime.strptime(status.trade_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return trade_date < as_of_datetime.date()


def _fetch_baostock_daily_row(
    bs: Any,
    symbol: str,
    as_of_date: date,
) -> dict[str, Any]:
    code = _to_baostock_code(symbol)
    if not code:
        return {}

    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
        "turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    )
    end_date = as_of_date
    start_date = end_date - timedelta(days=45)

    try:
        rs = bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        if getattr(rs, "error_code", "") != "0":
            logger.warning(
                "baostock history query failed for %s: %s",
                symbol,
                getattr(rs, "error_msg", ""),
            )
            return {}
        rows: list[list[str]] = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        return dict(zip(rs.fields, rows[-1], strict=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("baostock daily query failed for %s: %s", symbol, exc)
        return {}


def _fetch_baostock_basic_row(bs: Any, symbol: str) -> dict[str, Any]:
    code = _to_baostock_code(symbol)
    if not code:
        return {}
    try:
        rs = bs.query_stock_basic(code=code)
        if getattr(rs, "error_code", "") != "0":
            logger.warning(
                "baostock basic query failed for %s: %s",
                symbol,
                getattr(rs, "error_msg", ""),
            )
            return {}
        rows: list[list[str]] = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        return dict(zip(rs.fields, rows[-1], strict=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("baostock basic query failed for %s: %s", symbol, exc)
        return {}


def _fetch_baostock_profit_row(
    bs: Any,
    symbol: str,
    daily_row: dict[str, Any],
) -> dict[str, Any]:
    code = _to_baostock_code(symbol)
    trade_date = _format_date(_first_value(daily_row, "date"))
    year = _profit_query_year(trade_date)
    if not code or year is None:
        return {}
    for query_year, quarter in _profit_query_quarters(year):
        try:
            rs = bs.query_profit_data(code=code, year=query_year, quarter=quarter)
            if getattr(rs, "error_code", "") != "0":
                continue
            rows: list[list[str]] = []
            while rs.next():
                rows.append(rs.get_row_data())
            if rows:
                return dict(zip(rs.fields, rows[-1], strict=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "baostock profit query failed for %s %sQ%s: %s",
                symbol,
                query_year,
                quarter,
                exc,
            )
    return {}


def _profit_query_year(trade_date: str) -> int | None:
    if not trade_date or trade_date == "-":
        return date.today().year
    try:
        return int(trade_date[:4])
    except ValueError:
        return None


def _profit_query_quarters(year: int) -> list[tuple[int, int]]:
    quarters: list[tuple[int, int]] = []
    for query_year in (year, year - 1):
        for quarter in (4, 3, 2, 1):
            quarters.append((query_year, quarter))
    return quarters


def _to_baostock_code(symbol: str) -> str:
    code, _, suffix = symbol.upper().partition(".")
    if not code or suffix not in _SUPPORTED_SUFFIXES:
        return ""
    return f"{suffix.lower()}.{code}"


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _looks_like_table_separator(line: str) -> bool:
    if not _looks_like_table_row(line):
        return False
    cells = _split_table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _find_status_for_table_row(
    line: str,
    status_by_symbol: dict[str, StockDailyStatus],
) -> StockDailyStatus | None:
    for code_match in _STOCK_CODE_RE.finditer(line):
        symbol = _normalize_symbol(code_match.group(1))
        if symbol is not None and symbol in status_by_symbol:
            return status_by_symbol[symbol]
    return None


def _parse_markdown_table(markdown: str) -> list[StockTableRow]:
    lines = [line for line in markdown.splitlines() if _looks_like_table_row(line)]
    if len(lines) < 3:
        return []

    header_line = lines[0]
    separator_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if _looks_like_table_separator(line)),
        -1,
    )
    if separator_index < 1:
        return []

    headers = [_clean_markdown_inline(cell) for cell in _split_table_cells(header_line)]
    rows: list[StockTableRow] = []
    for line in lines[separator_index + 1 :]:
        if _looks_like_table_separator(line):
            continue
        cells = [_clean_markdown_inline(cell) for cell in _split_table_cells(line)]
        if not cells:
            continue
        values = {
            headers[index]: cells[index] if index < len(cells) else ""
            for index in range(len(headers))
        }
        rows.append(StockTableRow(raw=line, values=values))
    return rows


def _render_table_card(row: StockTableRow, status: StockDailyStatus | None) -> str:
    table_name = (
        _first_matching_value(row.values, ("股票名称", "名称", "标的", "公司"))
        or ""
    )
    effective_status = status
    title = (
        table_name
        or (effective_status.name if effective_status is not None else "")
        or "未命名标的"
    )
    symbol = (
        _first_matching_value(row.values, ("股票代码", "代码", "证券代码"))
        or (effective_status.symbol if effective_status else "")
    )
    body_items = [
        (key, value)
        for key, value in row.values.items()
        if key not in {"股票名称", "名称", "标的", "公司", "股票代码", "代码", "证券代码"}
        and value.strip()
    ]

    status_class = effective_status.direction if effective_status is not None else "flat"
    status_html = ""
    if effective_status is not None:
        status_html = _render_status_metrics(effective_status)
    pct_change_html = (
        f"\n          <strong>{html.escape(effective_status.pct_change)}</strong>"
        if effective_status is not None
        else ""
    )

    body_html = "\n".join(
        (
            '      <div class="stock-table-field">'
            f"<span>{html.escape(label)}</span><p>{html.escape(value)}</p>"
            "</div>"
        )
        for label, value in body_items
    )
    fields_html = (
        f"""    <div class="stock-table-fields">
{body_html}
    </div>"""
        if body_html
        else ""
    )
    return f"""  <article class="stock-table-card stock-status-{html.escape(status_class)}">
    <div class="stock-table-head">
      <div>
        <h3>
          <span>{html.escape(title)}</span>{pct_change_html}
        </h3>
        <p>{html.escape(symbol)}</p>
      </div>
    </div>
{fields_html}
{status_html}
  </article>"""


def _clean_markdown_inline(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _MARKDOWN_INLINE_MARKER_RE.sub("", text)
    text = text.replace(r"\|", "|")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]+", " ", text).strip()


def _first_matching_value(values: dict[str, str], candidates: tuple[str, ...]) -> str:
    normalized = {key.strip().lower(): value.strip() for key, value in values.items()}
    for candidate in candidates:
        value = normalized.get(candidate.lower())
        if value:
            return value
    return ""


def _normalize_stock_name(name: str) -> str:
    return re.sub(r"[\s　（）()\\-—–_]+", "", name).lower()


def _render_status_metrics(status: StockDailyStatus) -> str:
    fields = (
        ("收盘", status.close, "close"),
        ("涨跌", status.change, "change"),
        ("市值", status.market_cap, "market-cap"),
        ("PE", status.pe, "pe"),
        ("成交额", status.amount, "amount"),
    )
    rendered = "\n".join(
        (
            f'      <div class="stock-status-metric stock-metric-{css_class}">'
            f"<span>{html.escape(label)}</span><strong>{html.escape(value)}</strong>"
            "</div>"
        )
        for label, value, css_class in fields
    )
    return f"""    <div class="stock-status-metrics">
{rendered}
    </div>"""


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    lower_map = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and not _is_blank(row[key]):
            return row[key]
        value = lower_map.get(key.lower())
        if not _is_blank(value):
            return value
    return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_date(value: Any) -> str:
    if _is_blank(value):
        return "-"
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _format_number(value: Any) -> str:
    if _is_blank(value):
        return "-"
    number = _to_float(value)
    return f"{number:.2f}"


def _format_signed_number(value: Any) -> str:
    if _is_blank(value):
        return "-"
    number = _to_float(value)
    return f"{number:+.2f}"


def _format_pct(value: Any) -> str:
    if _is_blank(value):
        return "-"
    number = _to_float(value)
    return f"{number:+.2f}%"


def _format_large_number(value: Any) -> str:
    if _is_blank(value):
        return "-"
    number = _to_float(value)
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.2f}万"
    return f"{number:.0f}"


def _direction(value: Any) -> str:
    if _is_blank(value):
        return "flat"
    number = _to_float(value)
    if number > 0:
        return "up"
    if number < 0:
        return "down"
    return "flat"
