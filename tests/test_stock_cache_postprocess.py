from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.config import (
    ConverterConfig,
    STOCK_STATUS_MODE_BACKGROUND_HYBRID,
    STOCK_STATUS_MODE_BLOCKING_YFINANCE,
    _load_converter_config,
    create_app_config,
)
from b2t.stock_status import StockDailyStatus
from b2t.storage import StoredArtifact
from backend.postprocess import PostProcessScheduler
from backend.stock_cache import get_or_fetch_stock_statuses
from backend.services import _generate_summary_png_exports


class _FakeStorage:
    backend_name = "local"
    persist_local_outputs = False

    def __init__(self) -> None:
        self.stored: list[StoredArtifact] = []

    @contextmanager
    def open_stream(self, storage_key: str):
        with open(storage_key, "rb") as stream:
            yield stream

    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        artifact = StoredArtifact(
            filename=local_path.name,
            storage_key=object_key,
            backend="local",
        )
        self.stored.append(artifact)
        return artifact


def test_stock_status_mode_defaults_to_blocking_yfinance() -> None:
    config = _load_converter_config({})

    assert config.stock_status_mode == STOCK_STATUS_MODE_BLOCKING_YFINANCE


def test_stock_status_mode_rejects_unknown_value() -> None:
    import pytest

    with pytest.raises(ValueError, match="converter.stock_status_mode"):
        _load_converter_config({"stock_status_mode": "fast"})


def test_background_stock_refresh_fetches_and_replaces_stock_png(
    tmp_path: Path, monkeypatch
) -> None:
    summary_path = tmp_path / "BV123_summary.md"
    summary_path.write_text(
        "| 股票名称 | 股票代码 |\n| --- | --- |\n| 浦发银行 | 600000.SH |\n",
        encoding="utf-8",
    )
    summary_artifact = StoredArtifact(
        filename=summary_path.name,
        storage_key=str(summary_path),
        backend="local",
    )
    results = {
        "summary": summary_artifact,
        "_metadata": SimpleNamespace(
            bvid="BV123",
            pubdate="2026-02-05 21:00:00",
        ),
    }
    storage = _FakeStorage()
    captured_options: list[dict[str, object]] = []
    stock_status = object()

    class _FakePngConverter:
        def convert(self, input_path, output_path, **options):
            Path(output_path).write_bytes(b"png")
            captured_options.append(options)
            return Path(output_path)

    monkeypatch.setattr(
        "backend.services.MarkdownToPngConverter",
        _FakePngConverter,
    )
    monkeypatch.setattr("backend.services.get_history_db", lambda: object())
    monkeypatch.setattr(
        "backend.services.get_cached_stock_statuses",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("background refresh must fetch missing market data")
        ),
    )
    monkeypatch.setattr(
        "backend.services.get_or_fetch_stock_statuses",
        lambda **kwargs: {"600000.SH": stock_status},
    )

    generated = _generate_summary_png_exports(
        results=results,
        storage_backend=storage,
        config=create_app_config(output_dir=tmp_path),
        fetch_stock_statuses=True,
        refresh_stock_statuses=True,
        include_no_table=False,
    )

    assert set(generated) == {"summary_png"}
    assert captured_options[0]["stock_statuses"] == {"600000.SH": stock_status}


def test_sync_stock_wait_fetches_before_generating_png(
    tmp_path: Path, monkeypatch
) -> None:
    summary_path = tmp_path / "BV123_summary.md"
    summary_path.write_text(
        "| 股票名称 | 股票代码 |\n| --- | --- |\n| 浦发银行 | 600000.SH |\n",
        encoding="utf-8",
    )
    summary_artifact = StoredArtifact(
        filename=summary_path.name,
        storage_key=str(summary_path),
        backend="local",
    )
    results = {
        "summary": summary_artifact,
        "_metadata": SimpleNamespace(
            bvid="BV123",
            pubdate="2026-02-05 21:00:00",
        ),
    }
    storage = _FakeStorage()
    captured_fetch: dict[str, object] = {}
    captured_options: list[dict[str, object]] = []
    stock_status = object()

    class _FakePngConverter:
        def convert(self, input_path, output_path, **options):
            Path(output_path).write_bytes(b"png")
            captured_options.append(options)
            return Path(output_path)

    monkeypatch.setattr(
        "backend.services.MarkdownToPngConverter",
        _FakePngConverter,
    )
    monkeypatch.setattr("backend.services.get_history_db", lambda: object())
    monkeypatch.setattr(
        "backend.services.get_cached_stock_statuses",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("sync stock wait should fetch missing market data")
        ),
    )

    def fake_get_or_fetch(**kwargs):
        captured_fetch.update(kwargs)
        return {"600000.SH": stock_status}

    monkeypatch.setattr(
        "backend.services.get_or_fetch_stock_statuses",
        fake_get_or_fetch,
    )

    generated = _generate_summary_png_exports(
        results=results,
        storage_backend=storage,
        config=create_app_config(output_dir=tmp_path),
        fetch_stock_statuses=True,
        stock_status_timeout_seconds=30,
        include_no_table=False,
    )

    assert set(generated) == {"summary_png"}
    assert captured_fetch["timeout_seconds"] == 30
    assert captured_options[0]["stock_statuses"] == {"600000.SH": stock_status}


def test_stock_refresh_is_submitted_without_blocking(monkeypatch) -> None:
    submitted = []
    captured = {}
    summary_artifact = StoredArtifact(
        filename="BV123_summary.md",
        storage_key="runs/BV123_summary.md",
        backend="local",
    )
    config = SimpleNamespace(
        converter=ConverterConfig(stock_status_mode=STOCK_STATUS_MODE_BACKGROUND_HYBRID)
    )
    storage = object()

    monkeypatch.setattr(
        "backend.postprocess.submit_postprocess",
        lambda fn: submitted.append(fn),
    )

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {"summary_png": summary_artifact}

    monkeypatch.setattr(
        "backend.postprocess._generate_summary_png_exports",
        fake_generate,
    )

    PostProcessScheduler().trigger_stock_status_refresh(
        bvid="BV123",
        results={"summary": summary_artifact},
        config=config,
        storage_backend=storage,
    )

    assert len(submitted) == 1
    assert captured == {}

    submitted[0]()

    assert captured["refresh_stock_statuses"] is True
    assert captured["fetch_stock_statuses"] is True
    assert captured["prefer_baostock_for_a_shares"] is True
    assert captured["include_no_table"] is False
    assert captured["config"] is config
    assert captured["storage_backend"] is storage


def test_blocking_yfinance_mode_does_not_submit_background_refresh(monkeypatch) -> None:
    submitted = []
    summary_artifact = StoredArtifact(
        filename="BV123_summary.md",
        storage_key="runs/BV123_summary.md",
        backend="local",
    )
    config = SimpleNamespace(converter=ConverterConfig())

    monkeypatch.setattr(
        "backend.postprocess.submit_postprocess",
        lambda fn: submitted.append(fn),
    )

    PostProcessScheduler().trigger_stock_status_refresh(
        bvid="BV123",
        results={"summary": summary_artifact},
        config=config,
        storage_backend=object(),
    )

    assert submitted == []


def test_timed_stock_fetch_returns_partial_results(tmp_path: Path, monkeypatch) -> None:
    summary_path = tmp_path / "summary.md"
    summary_path.write_text(
        "| 股票名称 | 股票代码 |\n"
        "| --- | --- |\n"
        "| 浦发银行 | 600000.SH |\n"
        "| 平安银行 | 000001.SZ |\n",
        encoding="utf-8",
    )
    fast_status = StockDailyStatus(
        symbol="600000.SH",
        name="浦发银行",
        trade_date="2026-02-05",
        close="10.00",
        change="+1.00",
        pct_change="+10.00%",
        market_cap="100.00亿",
        pe="10.00",
        volume="1.00亿",
        amount="10.00亿",
        direction="up",
    )
    upserted: dict[str, object] = {}

    class FakeDB:
        def get_stock_statuses(self, **kwargs):
            return {}

        def upsert_stock_statuses(self, **kwargs):
            upserted.update(kwargs)

    def fake_fetch(symbols, *, as_of_date):
        if symbols == ["000001.SZ"]:
            import time

            time.sleep(0.5)
            return []
        return [fast_status]

    monkeypatch.setattr("backend.stock_cache.fetch_stock_daily_status", fake_fetch)

    statuses = get_or_fetch_stock_statuses(
        db=FakeDB(),
        bvid="BV123",
        as_of_date="2026-02-05 21:00:00",
        markdown_paths=[summary_path],
        timeout_seconds=0.2,
        max_workers=4,
    )

    assert statuses == {"600000.SH": fast_status}
    assert upserted["statuses"] == {"600000.SH": fast_status}
