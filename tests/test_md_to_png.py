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
