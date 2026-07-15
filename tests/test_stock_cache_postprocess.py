from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.config import create_app_config
from b2t.storage import StoredArtifact
from backend.postprocess import PostProcessScheduler
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
        refresh_stock_statuses=True,
        include_no_table=False,
    )

    assert set(generated) == {"summary_png"}
    assert captured_options[0]["stock_statuses"] == {"600000.SH": stock_status}


def test_stock_refresh_is_submitted_without_blocking(monkeypatch) -> None:
    submitted = []
    captured = {}
    summary_artifact = StoredArtifact(
        filename="BV123_summary.md",
        storage_key="runs/BV123_summary.md",
        backend="local",
    )
    config = object()
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
    assert captured["include_no_table"] is False
    assert captured["config"] is config
    assert captured["storage_backend"] is storage
