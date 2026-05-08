from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from b2t.converter.md_to_png import MarkdownToPngConverter


def test_normalize_markdown_for_tables_rewrites_fullwidth_table_chars() -> None:
    converter = MarkdownToPngConverter()
    source = "｜ 列1 ｜ 列2 ｜\n｜ －－－－ ｜ ：———： ｜\n｜ 值A ｜ 值B ｜\n"

    normalized = converter._normalize_markdown_for_tables(source)

    assert "｜" not in normalized
    assert "| 列1 | 列2 |" in normalized
    assert "| ---- | :---: |" in normalized


def test_run_pandoc_uses_pipe_tables_and_parent_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    md_path = tmp_path / "input.md"
    md_path.write_text(
        "｜ 列1 ｜ 列2 ｜\n｜ --- ｜ --- ｜\n｜ A ｜ B ｜\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/pandoc" if name == "pandoc" else None
    )

    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(*args, **kwargs):
        cmd = args[0]
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="<table></table>", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = MarkdownToPngConverter()._run_pandoc(md_path)

    assert result == "<table></table>"
    assert len(calls) == 1

    cmd, kwargs = calls[0]
    assert cmd == [
        "pandoc",
        "-f",
        "markdown+pipe_tables+lists_without_preceding_blankline",
        "-t",
        "html",
    ]
    assert kwargs.get("cwd") == str(md_path.parent)
    assert kwargs.get("input") == "| 列1 | 列2 |\n| --- | --- |\n| A | B |\n"


def test_convert_table_markdown_uses_stock_card_renderer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    md_path = tmp_path / "summary_table.md"
    png_path = tmp_path / "summary_table.png"
    md_path.write_text(
        "| 股票代码 | 股票名称 |\n| --- | --- |\n| 600000.SH | 浦发银行 |\n",
        encoding="utf-8",
    )

    converter = MarkdownToPngConverter()

    monkeypatch.setattr(converter, "_resolve_css_href", lambda css_url: "fallback.css")
    captured = {}

    def fake_build_stock_table_cards_html(markdown, as_of_date=None):
        captured["as_of_date"] = as_of_date
        return '<section class="stock-table-cards">cards</section>'

    monkeypatch.setattr(
        "b2t.converter.md_to_png.build_stock_table_cards_html",
        fake_build_stock_table_cards_html,
    )

    def fake_render(html_path, output_path, **kwargs):
        assert 'class="stock-table-cards"' in html_path.read_text(encoding="utf-8")
        captured["width"] = kwargs["width"]
        output_path.write_bytes(b"png")

    monkeypatch.setattr(converter, "_render_html_to_png", fake_render)

    result = converter.convert(
        md_path,
        png_path,
        is_table=True,
        keep_html=True,
        as_of_date="2026-02-05 21:00:00",
    )

    assert result == png_path.resolve()
    assert png_path.exists()
    assert captured["as_of_date"] == "2026-02-05 21:00:00"
    assert captured["width"] == 720


def test_convert_plain_table_markdown_keeps_wide_table_viewport(
    tmp_path: Path,
    monkeypatch,
) -> None:
    md_path = tmp_path / "summary_table.md"
    png_path = tmp_path / "summary_table.png"
    md_path.write_text(
        "| 列1 | 列2 |\n| --- | --- |\n| A | B |\n",
        encoding="utf-8",
    )

    converter = MarkdownToPngConverter()
    captured = {}

    monkeypatch.setattr(
        converter,
        "_resolve_css_href",
        lambda css_url: "fallback.css",
    )
    monkeypatch.setattr(
        "b2t.converter.md_to_png.build_stock_table_cards_html",
        lambda markdown, as_of_date=None: "",
    )
    monkeypatch.setattr(
        converter,
        "_run_pandoc",
        lambda path: "<table><tbody><tr><td>A</td><td>B</td></tr></tbody></table>",
    )

    def fake_render(html_path, output_path, **kwargs):
        captured["width"] = kwargs["width"]
        output_path.write_bytes(b"png")

    monkeypatch.setattr(converter, "_render_html_to_png", fake_render)

    converter.convert(
        md_path,
        png_path,
        is_table=True,
        keep_html=True,
    )

    assert captured["width"] == 1200
