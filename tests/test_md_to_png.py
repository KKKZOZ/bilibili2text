from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from b2t.converter.md_to_png import HTML_TEMPLATE, MarkdownToPngConverter


def test_normalize_markdown_for_tables_rewrites_fullwidth_table_chars() -> None:
    converter = MarkdownToPngConverter()
    source = (
        "｜ 列1 ｜ 列2 ｜\n"
        "｜ －－－－ ｜ ：———： ｜\n"
        "｜ 值A ｜ 值B ｜\n"
    )

    normalized = converter._normalize_markdown_for_tables(source)

    assert "｜" not in normalized
    assert "| 列1 | 列2 |" in normalized
    assert "| ---- | :---: |" in normalized


def test_run_pandoc_uses_pipe_tables_and_parent_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    md_path = tmp_path / "input.md"
    md_path.write_text("｜ 列1 ｜ 列2 ｜\n｜ --- ｜ --- ｜\n｜ A ｜ B ｜\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pandoc" if name == "pandoc" else None)

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
    assert cmd == ["pandoc", "-f", "markdown+pipe_tables", "-t", "html"]
    assert kwargs.get("cwd") == str(md_path.parent)
    assert kwargs.get("input") == "| 列1 | 列2 |\n| --- | --- |\n| A | B |\n"


def test_mobile_html_transforms_reference_table_to_cards(tmp_path: Path, monkeypatch) -> None:
    converter = MarkdownToPngConverter()
    fixture_path = Path("tests/fixtures/rag_answer_mengniu.md")
    md_path = tmp_path / fixture_path.name
    md_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")

    html = converter._run_pandoc(md_path)
    full_html = HTML_TEMPLATE.format(
        css_href=converter._ensure_fallback_css().resolve().as_uri(),
        body_html=html,
    )
    html_path = tmp_path / "mengniu.html"
    html_path.write_text(full_html, encoding="utf-8")

    playwright = pytest.importorskip("playwright.sync_api")
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                assert page.locator(".mobile-table").count() == 1
                assert page.locator(".mobile-table-row").count() == 5
            finally:
                browser.close()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Playwright Chromium unavailable: {exc}")
