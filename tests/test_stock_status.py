from b2t.stock_status import (
    _baostock_row_to_status,
    _fetch_status_for_symbol,
    _fetch_tickflow_daily_row,
    _parse_as_of_date,
    _tickflow_row_to_status,
    _to_baostock_code,
    _to_yfinance_symbol,
    build_stock_table_cards_html,
    extract_stock_symbols,
    fetch_stock_daily_status,
)
from datetime import datetime
from zoneinfo import ZoneInfo


def test_extract_stock_symbols_from_markdown_tables_only() -> None:
    markdown = """
正文里提到 600000 不应该被提取。

| 股票代码 | 股票名称 | 逻辑 |
| --- | --- | --- |
| 600000 | 浦发银行 | 示例 |
| 000001.SZ | 平安银行 | 示例 |
| 688001 | 华兴源创 | 示例 |
| 600000.SH | 重复 | 示例 |
| 00700.HK | 腾讯控股 | 示例 |
"""

    assert extract_stock_symbols(markdown) == [
        "600000.SH",
        "000001.SZ",
        "688001.SH",
        "00700.HK",
    ]


def test_to_baostock_code_uses_lowercase_suffix() -> None:
    assert _to_baostock_code("600000.SH") == "sh.600000"
    assert _to_baostock_code("000001.SZ") == "sz.000001"
    assert _to_baostock_code("00700.HK") == "hk.00700"


def test_to_yfinance_symbol_maps_a_share_and_hk_suffixes() -> None:
    assert _to_yfinance_symbol("688041.SH") == "688041.SS"
    assert _to_yfinance_symbol("000001.SZ") == "000001.SZ"
    assert _to_yfinance_symbol("00506.HK") == "0506.HK"
    assert _to_yfinance_symbol("01099.HK") == "1099.HK"


def test_baostock_row_to_status_calculates_fields() -> None:
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-06",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
            "amount": "808632515.1900",
            "volume": "87935791",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )

    assert status.change == "-0.09"
    assert status.pct_change == "-0.97%"
    assert status.market_cap == "3057.48亿"
    assert status.pe == "6.08"
    assert status.direction == "down"


def test_baostock_row_to_status_calculates_missing_pct_change() -> None:
    status = _baostock_row_to_status(
        "000001.SZ",
        {
            "date": "2026-05-06",
            "close": "11.20",
            "preclose": "11.00",
            "peTTM": "5.4321",
        },
        {"code_name": "平安银行"},
        {"totalShare": "19405918198.0"},
    )

    assert status.change == "+0.20"
    assert status.pct_change == "+1.82%"
    assert status.pe == "5.43"
    assert status.market_cap == "2173.46亿"
    assert status.direction == "up"


def test_parse_as_of_date_accepts_video_pubdate_string() -> None:
    assert str(_parse_as_of_date("2026-02-05 21:00:00")) == "2026-02-05"


def test_fetch_stock_daily_status_uses_as_of_date(monkeypatch) -> None:
    captured = {}

    def fake_fetch(symbol, as_of_date):
        captured["symbol"] = symbol
        captured["as_of_date"] = as_of_date
        return None

    monkeypatch.setattr("b2t.stock_status._fetch_yfinance_status_for_symbol", fake_fetch)

    assert fetch_stock_daily_status(["600000.SH"], as_of_date="2026-02-05 21:00:00") == []
    assert captured["symbol"] == "600000.SH"
    assert str(captured["as_of_date"]) == "2026-02-05"


def test_fetch_stock_daily_status_hides_stale_a_share_after_market_close(
    monkeypatch,
) -> None:
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-05",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )

    monkeypatch.setattr(
        "b2t.stock_status._fetch_yfinance_status_for_symbol",
        lambda symbol, as_of_date: status,
    )

    assert fetch_stock_daily_status(["600000.SH"], as_of_date="2026-05-06 16:30:00") == []


def test_fetch_stock_daily_status_keeps_previous_trade_day_before_market_close(
    monkeypatch,
) -> None:
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-05",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )

    monkeypatch.setattr(
        "b2t.stock_status._fetch_yfinance_status_for_symbol",
        lambda symbol, as_of_date: status,
    )

    assert fetch_stock_daily_status(
        ["600000.SH"],
        as_of_date="2026-05-06 14:30:00",
    ) == [status]


def test_fetch_stock_daily_status_keeps_previous_trade_day_on_weekend(
    monkeypatch,
) -> None:
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-08",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )

    monkeypatch.setattr(
        "b2t.stock_status._fetch_yfinance_status_for_symbol",
        lambda symbol, as_of_date: status,
    )

    assert fetch_stock_daily_status(
        ["600000.SH"],
        as_of_date="2026-05-09 16:30:00",
    ) == [status]


def test_fetch_status_uses_yfinance_for_all_markets(monkeypatch) -> None:
    calls = []
    status = _tickflow_row_to_status(
        "00700.HK",
        {
            "date": "2026-05-06",
            "close": 500.0,
            "preclose": 490.0,
            "amount": 123456789.0,
            "volume": 1000000,
        },
        {"name": "腾讯控股", "ext": {"total_shares": 9500000000}},
    )

    def fake_yfinance(symbol, as_of_date):
        calls.append((symbol, str(as_of_date)))
        return status

    monkeypatch.setattr(
        "b2t.stock_status._fetch_yfinance_status_for_symbol",
        fake_yfinance,
    )

    assert _fetch_status_for_symbol("00700.HK", _parse_as_of_date("2026-05-06")) == status
    assert _fetch_status_for_symbol("600000.SH", _parse_as_of_date("2026-05-06")) == status
    assert calls == [
        ("00700.HK", "2026-05-06"),
        ("600000.SH", "2026-05-06"),
    ]


def test_tickflow_daily_row_uses_latest_row_before_as_of_date() -> None:
    def ts(day: int) -> int:
        return int(
            datetime(2026, 5, day, tzinfo=ZoneInfo("Asia/Hong_Kong")).timestamp()
            * 1000
        )

    class FakeClient:
        class Klines:
            def get(self, symbol, **kwargs):
                assert symbol == "00700.HK"
                assert kwargs["period"] == "1d"
                assert kwargs["adjust"] == "none"
                return {
                    "timestamp": [
                        ts(5),
                        ts(6),
                        ts(7),
                    ],
                    "close": [490.0, 500.0, 510.0],
                    "volume": [1, 2, 3],
                    "amount": [10.0, 20.0, 30.0],
                }

        klines = Klines()

    row = _fetch_tickflow_daily_row(
        FakeClient(),
        "00700.HK",
        _parse_as_of_date("2026-05-06"),
    )

    assert row["close"] == 500.0
    assert row["preclose"] == 490.0
    assert row["amount"] == 20.0


def test_tickflow_row_to_status_calculates_hk_fields() -> None:
    status = _tickflow_row_to_status(
        "00700.HK",
        {
            "date": "2026-05-06",
            "close": 500.0,
            "preclose": 490.0,
            "amount": 123456789.0,
            "volume": 1000000,
        },
        {"name": "腾讯控股", "ext": {"total_shares": 9500000000}},
    )

    assert status.name == "腾讯控股"
    assert status.change == "+10.00"
    assert status.pct_change == "+2.04%"
    assert status.market_cap == "47500.00亿"
    assert status.pe == "-"
    assert status.direction == "up"


def test_build_stock_table_cards_html_merges_table_content_and_status(monkeypatch) -> None:
    markdown = """| 股票代码 | 股票名称 | 投资逻辑 |
| --- | --- | --- |
| 600000.SH | 浦发银行 | 银行估值修复 |
"""
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-06",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
            "amount": "808632515.1900",
            "volume": "87935791",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )
    monkeypatch.setattr(
        "b2t.stock_status.fetch_stock_daily_status",
        lambda symbols, as_of_date=None: [status],
    )

    html = build_stock_table_cards_html(markdown, as_of_date="2026-02-05 21:00:00")

    assert 'class="stock-table-card stock-status-down"' in html
    assert 'class="stock-status-metric stock-metric-close"' in html
    assert 'class="stock-status-metric stock-metric-change"' in html
    assert "<span>浦发银行</span>" in html
    assert "<strong>-0.97%</strong>" in html
    assert "银行估值修复" in html
    assert "3057.48亿" in html
    assert "-0.97%" in html


def test_build_stock_table_cards_html_cleans_inline_markdown_for_name_match(
    monkeypatch,
) -> None:
    markdown = """| 股票代码 | 股票名称 | 投资逻辑 |
| --- | --- | --- |
| 600000.SH | **浦发银行** | **银行估值修复** |
"""
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-06",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
            "amount": "808632515.1900",
            "volume": "87935791",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )
    monkeypatch.setattr(
        "b2t.stock_status.fetch_stock_daily_status",
        lambda symbols, as_of_date=None: [status],
    )

    html = build_stock_table_cards_html(markdown, as_of_date="2026-02-05 21:00:00")

    assert "**" not in html
    assert "<span>浦发银行</span>" in html
    assert "银行估值修复" in html
    assert "stock-status-metrics" in html
    assert "<strong>-0.97%</strong>" in html


def test_build_stock_table_cards_html_keeps_status_when_name_mismatches(
    monkeypatch,
) -> None:
    markdown = """| 股票代码 | 股票名称 | 投资逻辑 |
| --- | --- | --- |
| 600000.SH | 幻觉银行 | 银行估值修复 |
"""
    status = _baostock_row_to_status(
        "600000.SH",
        {
            "date": "2026-05-06",
            "close": "9.1800",
            "preclose": "9.2700",
            "pctChg": "-0.970900",
            "peTTM": "6.080899",
            "amount": "808632515.1900",
            "volume": "87935791",
        },
        {"code_name": "浦发银行"},
        {"totalShare": "33305838300.00"},
    )
    monkeypatch.setattr(
        "b2t.stock_status.fetch_stock_daily_status",
        lambda symbols, as_of_date=None: [status],
    )

    html = build_stock_table_cards_html(markdown, as_of_date="2026-02-05 21:00:00")

    assert 'class="stock-table-card stock-status-down"' in html
    assert "<span>幻觉银行</span>" in html
    assert "银行估值修复" in html
    assert "浦发银行" not in html
    assert "3057.48亿" in html
    assert "-0.97%" in html
    assert "<strong>-</strong>" not in html
    assert "stock-status-metrics" in html
