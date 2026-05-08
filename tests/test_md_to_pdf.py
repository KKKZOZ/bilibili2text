from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import b2t.converter.md_to_pdf as md_to_pdf_module
from b2t.converter.md_to_pdf import MarkdownToPdfConverter


def test_convert_uses_pandoc_html_then_playwright_pdf(
    tmp_path: Path, monkeypatch
) -> None:
    md_path = tmp_path / "input.md"
    md_path.write_text("| 列1 | 列2 |\n| --- | --- |\n| A | B |\n", encoding="utf-8")
    output_path = tmp_path / "output.pdf"

    def fake_which(name: str) -> str | None:
        if name == "pandoc":
            return "/usr/bin/pandoc"
        return None

    monkeypatch.setattr(shutil, "which", fake_which)

    calls: list[tuple[list[str], dict[str, object]]] = []
    pdf_calls: list[dict[str, object]] = []
    content_calls: list[dict[str, object]] = []

    def fake_run(*args, **kwargs):
        cmd = args[0]
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="<table></table>", stderr="")

    class FakePage:
        def set_content(self, html: str, **kwargs) -> None:
            content_calls.append({"html": html, **kwargs})

        def pdf(self, **kwargs) -> None:
            pdf_calls.append(kwargs)

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()
            self.closed = False

        def new_page(self) -> FakePage:
            return self.page

        def close(self) -> None:
            self.closed = True

    class FakePlaywright:
        def __init__(self) -> None:
            self.browser = FakeBrowser()
            self.chromium = self

        def launch(self) -> FakeBrowser:
            return self.browser

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(md_to_pdf_module, "sync_playwright", lambda: FakePlaywright())

    result = MarkdownToPdfConverter().convert(md_path, output_path)

    assert result == output_path
    assert len(calls) == 1
    pandoc_cmd, run_kwargs = calls[0]
    assert pandoc_cmd == [
        "pandoc",
        "-f",
        "markdown+pipe_tables+lists_without_preceding_blankline",
        "-t",
        "html",
    ]
    assert run_kwargs.get("input") == "| 列1 | 列2 |\n| --- | --- |\n| A | B |\n"
    assert run_kwargs.get("cwd") == str(md_path.parent.resolve())
    assert run_kwargs.get("check") is True
    assert len(content_calls) == 1
    assert "wait_until" in content_calls[0]
    assert len(pdf_calls) == 1
    assert pdf_calls[0].get("path") == str(output_path.resolve())
    assert pdf_calls[0].get("format") == "A4"


def test_convert_raises_if_pandoc_not_found(tmp_path: Path, monkeypatch) -> None:
    md_path = tmp_path / "input.md"
    md_path.write_text("test", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _: None)

    try:
        MarkdownToPdfConverter().convert(md_path)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "pandoc not found" in str(exc)


def test_convert_summary_pdf_enhances_stock_tables(
    tmp_path: Path, monkeypatch
) -> None:
    md_path = tmp_path / "summary.md"
    output_path = tmp_path / "summary.pdf"
    md_path.write_text(
        "# Summary\n\n"
        "正文。\n\n"
        "| 股票代码 | 股票名称 |\n"
        "| --- | --- |\n"
        "| 600000.SH | 浦发银行 |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pandoc")

    pandoc_inputs: list[str] = []
    content_calls: list[dict[str, object]] = []

    class FakePage:
        def set_content(self, html: str, **kwargs) -> None:
            content_calls.append({"html": html, **kwargs})

        def pdf(self, **kwargs) -> None:
            output_path.write_bytes(b"pdf")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self

        def launch(self) -> FakeBrowser:
            return FakeBrowser()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_run(*args, **kwargs):
        pandoc_inputs.append(kwargs["input"])
        return subprocess.CompletedProcess(args[0], 0, stdout="<p>text</p>", stderr="")

    captured = {}

    def fake_build_stock_table_cards_html(markdown, as_of_date=None):
        captured["table_markdown"] = markdown
        captured["as_of_date"] = as_of_date
        return '<section class="stock-table-cards">cards</section>'

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(md_to_pdf_module, "sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(
        "b2t.converter.md_to_pdf.build_stock_table_cards_html",
        fake_build_stock_table_cards_html,
    )

    MarkdownToPdfConverter().convert(
        md_path,
        output_path,
        enhance_stock_tables=True,
        as_of_date="2026-02-05 21:00:00",
    )

    assert output_path.exists()
    assert captured["as_of_date"] == "2026-02-05 21:00:00"
    assert "| 600000.SH | 浦发银行 |" in captured["table_markdown"]
    assert len(pandoc_inputs) >= 1
    assert 'class="stock-table-cards"' in content_calls[0]["html"]
    assert ".stock-table-card" in content_calls[0]["html"]
    assert ".stock-status-metrics" in content_calls[0]["html"]


def test_convert_summary_table_pdf_uses_stock_cards(
    tmp_path: Path, monkeypatch
) -> None:
    md_path = tmp_path / "summary_table.md"
    output_path = tmp_path / "summary_table.pdf"
    md_path.write_text(
        "| 股票代码 | 股票名称 |\n| --- | --- |\n| 600000.SH | 浦发银行 |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pandoc")
    content_calls: list[dict[str, object]] = []

    class FakePage:
        def set_content(self, html: str, **kwargs) -> None:
            content_calls.append({"html": html, **kwargs})

        def pdf(self, **kwargs) -> None:
            output_path.write_bytes(b"pdf")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self

        def launch(self) -> FakeBrowser:
            return FakeBrowser()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    captured = {}

    def fake_build_stock_table_cards_html(markdown, as_of_date=None):
        captured["as_of_date"] = as_of_date
        return '<section class="stock-table-cards">cards</section>'

    monkeypatch.setattr(md_to_pdf_module, "sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(
        "b2t.converter.md_to_pdf.build_stock_table_cards_html",
        fake_build_stock_table_cards_html,
    )

    MarkdownToPdfConverter().convert(
        md_path,
        output_path,
        is_table=True,
        as_of_date="2026-02-05 21:00:00",
    )

    assert output_path.exists()
    assert captured["as_of_date"] == "2026-02-05 21:00:00"
    assert 'class="stock-table-cards"' in content_calls[0]["html"]
