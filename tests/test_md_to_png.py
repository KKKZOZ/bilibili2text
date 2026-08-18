from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

import b2t.converter.md_to_png as md_to_png_module
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


def test_convert_mixed_markdown_enhances_stock_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    md_path = tmp_path / "summary.md"
    png_path = tmp_path / "summary.png"
    md_path.write_text(
        "# AI Summary\n\n"
        "开头正文。\n\n"
        "| 股票代码 | 股票名称 | 逻辑 |\n"
        "| --- | --- | --- |\n"
        "| 600000.SH | 浦发银行 | 示例 |\n\n"
        "结尾正文。\n",
        encoding="utf-8",
    )

    converter = MarkdownToPngConverter()
    monkeypatch.setattr(converter, "_resolve_css_href", lambda css_url: "fallback.css")

    pandoc_inputs: list[str] = []

    def fake_run_pandoc_markdown(markdown, *, cwd):
        pandoc_inputs.append(markdown)
        compact = markdown.strip().replace("\n", " ")
        return f"<section>{compact}</section>" if compact else ""

    captured = {}

    def fake_build_stock_table_cards_html(markdown, as_of_date=None):
        captured["table_markdown"] = markdown
        captured["as_of_date"] = as_of_date
        return '<section class="stock-table-cards">cards</section>'

    def fake_render(html_path, output_path, **kwargs):
        captured["html"] = html_path.read_text(encoding="utf-8")
        output_path.write_bytes(b"png")

    monkeypatch.setattr(converter, "_run_pandoc_markdown", fake_run_pandoc_markdown)
    monkeypatch.setattr(
        "b2t.converter.md_to_png.build_stock_table_cards_html",
        fake_build_stock_table_cards_html,
    )
    monkeypatch.setattr(converter, "_render_html_to_png", fake_render)

    converter.convert(
        md_path,
        png_path,
        is_table=False,
        keep_html=True,
        enhance_stock_tables=True,
        as_of_date="2026-02-05 21:00:00",
    )

    assert png_path.exists()
    assert captured["as_of_date"] == "2026-02-05 21:00:00"
    assert "| 600000.SH | 浦发银行 | 示例 |" in captured["table_markdown"]
    assert len(pandoc_inputs) == 2
    assert "开头正文。" in pandoc_inputs[0]
    assert "结尾正文。" in pandoc_inputs[1]
    assert 'class="stock-table-cards"' in captured["html"]


def test_convert_mixed_markdown_skips_non_stock_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    md_path = tmp_path / "summary.md"
    png_path = tmp_path / "summary.png"
    md_path.write_text(
        "# AI Summary\n\n| 列1 | 列2 |\n| --- | --- |\n| A | B |\n",
        encoding="utf-8",
    )

    converter = MarkdownToPngConverter()
    monkeypatch.setattr(converter, "_resolve_css_href", lambda css_url: "fallback.css")
    captured = {}

    def fake_run_pandoc_markdown(markdown, *, cwd):
        captured["markdown"] = markdown
        return "<section>plain</section>"

    def fake_render(html_path, output_path, **kwargs):
        captured["html"] = html_path.read_text(encoding="utf-8")
        output_path.write_bytes(b"png")

    monkeypatch.setattr(converter, "_run_pandoc_markdown", fake_run_pandoc_markdown)
    monkeypatch.setattr(
        "b2t.converter.md_to_png.build_stock_table_cards_html",
        lambda markdown, as_of_date=None: (
            '<section class="stock-table-cards">cards</section>'
        ),
    )
    monkeypatch.setattr(converter, "_render_html_to_png", fake_render)

    converter.convert(
        md_path,
        png_path,
        is_table=False,
        keep_html=True,
        enhance_stock_tables=True,
    )

    assert png_path.exists()
    assert "| A | B |" in captured["markdown"]
    assert 'class="stock-table-cards"' not in captured["html"]


def test_render_uses_tiling_for_css_and_physical_height_limits(
    tmp_path: Path, monkeypatch
) -> None:
    class FakePage:
        def __init__(self, full_height: int) -> None:
            self.full_height = full_height
            self.full_page_screenshots = 0

        def goto(self, *args, **kwargs) -> None:
            return None

        def set_default_timeout(self, timeout: int) -> None:
            return None

        def evaluate(self, expression: str) -> int:
            return self.full_height

        def screenshot(self, **kwargs) -> None:
            self.full_page_screenshots += 1

    class FakeContext:
        def __init__(self, page: FakePage) -> None:
            self.page = page

        def new_page(self) -> FakePage:
            return self.page

        def close(self) -> None:
            return None

    class FakeBrowser:
        def __init__(self, full_height: int) -> None:
            self.page = FakePage(full_height)

        def new_context(self, **kwargs) -> FakeContext:
            return FakeContext(self.page)

    converter = MarkdownToPngConverter()
    captures: list[dict[str, object]] = []

    def fake_capture(**kwargs) -> None:
        captures.append(kwargs)

    monkeypatch.setattr(converter, "_capture_tiled_png", fake_capture)

    css_limited_browser = FakeBrowser(full_height=100)
    converter._render_with_browser(
        css_limited_browser,
        html_path=tmp_path / "input.html",
        png_path=tmp_path / "css-limit.png",
        width=390,
        height=20,
        dpr=1,
        max_full_page_height=50,
        tile_height=17,
    )

    physical_limited_browser = FakeBrowser(full_height=6000)
    converter._render_with_browser(
        physical_limited_browser,
        html_path=tmp_path / "input.html",
        png_path=tmp_path / "physical-limit.png",
        width=390,
        height=844,
        dpr=3,
        max_full_page_height=10000,
        tile_height=500,
    )

    assert [capture["tile_height"] for capture in captures] == [17, 500]
    assert css_limited_browser.page.full_page_screenshots == 0
    assert physical_limited_browser.page.full_page_screenshots == 0


def test_capture_tiled_png_preserves_every_row_once(tmp_path: Path) -> None:
    class FakePage:
        viewport_size = {"width": 2, "height": 4}

        def __init__(self) -> None:
            self.scroll_y = 0
            self.scroll_positions: list[int] = []

        def evaluate(self, expression: str, offset: int) -> None:
            self.scroll_y = offset
            self.scroll_positions.append(offset)

        def wait_for_timeout(self, timeout: int) -> None:
            return None

        def screenshot(self, *, path: str, full_page: bool, **kwargs) -> None:
            assert full_page is False
            image = Image.new("RGB", (4, 8), "white")
            for physical_y in range(image.height):
                page_y = self.scroll_y + physical_y // 2
                for x in range(image.width):
                    image.putpixel((x, physical_y), (page_y, 0, 0))
            image.save(path)
            image.close()

    output_path = tmp_path / "stitched.png"
    page = FakePage()

    MarkdownToPngConverter()._capture_tiled_png(
        page=page,
        output_path=output_path,
        dpr=2,
        full_height=10,
        tile_height=3,
    )

    with Image.open(output_path) as stitched:
        assert stitched.size == (4, 20)
        assert [stitched.getpixel((0, y))[0] for y in range(20)] == [
            value for value in range(10) for _ in range(2)
        ]
    assert page.scroll_positions == [0, 3, 6]


def test_non_reused_renderer_launches_playwright_chromium_without_overrides(
    tmp_path: Path, monkeypatch
) -> None:
    launch_options: list[dict[str, object]] = []

    class FakeBrowser:
        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self

        def launch(self, **kwargs) -> FakeBrowser:
            launch_options.append(kwargs)
            return FakeBrowser()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    converter = MarkdownToPngConverter()
    monkeypatch.delenv("B2T_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(md_to_png_module, "sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(converter, "_render_with_browser", lambda *args, **kwargs: None)

    converter._render_html_to_png(
        tmp_path / "input.html",
        tmp_path / "output.png",
        width=390,
        height=844,
        dpr=3,
        max_full_page_height=5000,
        tile_height=1800,
        reuse_browser=False,
    )

    assert launch_options == [{}]


def test_non_reused_renderer_uses_configured_chromium_executable(
    tmp_path: Path, monkeypatch
) -> None:
    executable_path = tmp_path / "chrome"
    executable_path.write_bytes(b"chrome")
    executable_path.chmod(executable_path.stat().st_mode | 0o100)
    launch_options: list[dict[str, object]] = []

    class FakeBrowser:
        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self

        def launch(self, **kwargs) -> FakeBrowser:
            launch_options.append(kwargs)
            return FakeBrowser()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    converter = MarkdownToPngConverter()
    monkeypatch.setenv("B2T_CHROMIUM_EXECUTABLE_PATH", str(executable_path))
    monkeypatch.setattr(md_to_png_module, "sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(converter, "_render_with_browser", lambda *args, **kwargs: None)

    converter._render_html_to_png(
        tmp_path / "input.html",
        tmp_path / "output.png",
        width=390,
        height=844,
        dpr=3,
        max_full_page_height=5000,
        tile_height=1800,
        reuse_browser=False,
    )

    assert launch_options == [{"executable_path": str(executable_path.resolve())}]
