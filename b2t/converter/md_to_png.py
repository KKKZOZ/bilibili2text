"""Markdown 转 PNG（通过 Pandoc + Playwright）"""

import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

GITHUB_CSS_URL = "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown.min.css"
TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
TABLE_DASH_TRANSLATION = str.maketrans(
    {
        "－": "-",
        "—": "-",
        "–": "-",
        "−": "-",
        "﹣": "-",
        "‒": "-",
        "：": ":",
        "\u00A0": " ",
    }
)

HTML_TEMPLATE = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- GitHub markdown css (requires .markdown-body wrapper) -->
  <link rel="stylesheet" href="{css_href}">

  <style>
    /* Make it look good on phone screenshots */
    body {{
      margin: 0;
      padding: 16px;
      background: #fff;
    }}
    .markdown-body {{
      box-sizing: border-box;
      width: 100%;
      max-width: 100%;
      margin: 0 auto;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 16px;
      line-height: 1.6;
    }}

    /* Extra table polish (in case theme doesn't cover everything) */
    .markdown-body table {{
      width: 100%;
      border-collapse: collapse;
      border-spacing: 0;
      display: table;
      table-layout: fixed;
    }}
    .markdown-body th,
    .markdown-body td {{
      border: 1px solid #d0d7de;
      padding: 6px 10px;
      vertical-align: top;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .markdown-body thead th {{
      background: #f6f8fa;
    }}
  </style>
</head>
<body>
  <div class="markdown-body">
  {body_html}
  </div>
</body>
</html>
"""


class MarkdownToPngConverter:
    """Markdown 转 PNG 转换器（生成移动端长截图）。"""

    def __init__(
        self,
        width: int = 390,
        height: int = 844,
        dpr: int = 3,
        css_url: str = GITHUB_CSS_URL,
    ):
        """
        初始化转换器。

        Args:
            width: 视口宽度（像素）
            height: 视口高度（像素）
            dpr: 设备像素比（用于 retina 显示）
            css_url: CSS 样式表 URL
        """
        self.width = width
        self.height = height
        self.dpr = dpr
        self.css_url = css_url

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        is_table: bool = False,
        **options,
    ) -> Path:
        """
        将 Markdown 转换为 PNG 长截图。

        Args:
            input_path: Markdown 文件路径
            output_path: 输出 PNG 路径（可选）
            is_table: 是否为表格 Markdown（为 True 时使用更宽画布）
            **options: 额外选项
                - width: 视口宽度
                - height: 视口高度
                - dpr: 设备像素比
                - css_url: CSS 样式表 URL
                - keep_html: 是否保留中间 HTML 文件
                - max_full_page_height: 单次 full_page 截图最大 CSS 高度
                - tile_height: 分片截图时每片 CSS 高度

        Returns:
            输出 PNG 文件路径
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Markdown 文件不存在: {input_path}")

        input_path = input_path.expanduser().resolve()
        if output_path is None:
            output_path = input_path.with_suffix(".png")
        else:
            output_path = output_path.expanduser().resolve()

        # 提取选项
        width = 1200 if is_table else options.get("width", self.width)
        height = options.get("height", self.height)
        dpr = options.get("dpr", self.dpr)
        css_url = options.get("css_url", self.css_url)
        keep_html = options.get("keep_html", False)
        max_full_page_height = options.get("max_full_page_height", 12000)
        tile_height = options.get("tile_height", 1800)

        # 生成中间 HTML
        html_path = output_path.with_suffix(".html")
        body_html = self._run_pandoc(input_path)

        # 处理 CSS href
        css_href = css_url
        css_path = Path(css_url)
        if css_path.exists():
            css_href = css_path.resolve().as_uri()

        # 生成完整 HTML
        full_html = HTML_TEMPLATE.format(css_href=css_href, body_html=body_html)
        html_path.write_text(full_html, encoding="utf-8")

        try:
            # 渲染 HTML -> PNG
            self._render_html_to_png(
                html_path,
                output_path,
                width=width,
                height=height,
                dpr=dpr,
                max_full_page_height=max_full_page_height,
                tile_height=tile_height,
            )

            logger.info("PNG 文件已生成: %s", output_path)
            return output_path
        finally:
            # 清理中间 HTML 文件（除非要求保留）
            if not keep_html and html_path.exists():
                html_path.unlink()

    def _run_pandoc(self, md_path: Path) -> str:
        """使用 pandoc 将 Markdown 转换为 HTML fragment。"""
        if shutil.which("pandoc") is None:
            raise RuntimeError("未找到 pandoc，请先安装 pandoc 后再试")

        markdown_content = md_path.read_text(encoding="utf-8")
        normalized_content = self._normalize_markdown_for_tables(markdown_content)

        try:
            proc = subprocess.run(
                ["pandoc", "-f", "markdown+pipe_tables", "-t", "html"],
                check=True,
                capture_output=True,
                text=True,
                input=normalized_content,
                cwd=str(md_path.parent),
            )
            return proc.stdout
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc 转换失败: {detail}") from exc

    def _normalize_markdown_for_tables(self, content: str) -> str:
        """Normalize common full-width table characters before pandoc parsing."""
        trailing_newline = content.endswith("\n")
        lines = content.splitlines()
        normalized_lines: list[str] = []

        for line in lines:
            normalized = line.replace("｜", "|").replace("\u00A0", " ")
            if self._looks_like_table_delimiter_line(normalized):
                normalized = normalized.translate(TABLE_DASH_TRANSLATION)
            normalized_lines.append(normalized)

        normalized_content = "\n".join(normalized_lines)
        if trailing_newline:
            normalized_content += "\n"
        return normalized_content

    def _looks_like_table_delimiter_line(self, line: str) -> bool:
        text = line.strip()
        if "|" not in text:
            return False
        if text.startswith("|"):
            text = text[1:]
        if text.endswith("|"):
            text = text[:-1]

        cells = [cell.strip().translate(TABLE_DASH_TRANSLATION) for cell in text.split("|")]
        if not cells:
            return False
        return all(TABLE_DELIMITER_CELL_RE.match(cell) for cell in cells)

    def _render_html_to_png(
        self,
        html_path: Path,
        png_path: Path,
        *,
        width: int,
        height: int,
        dpr: int,
        max_full_page_height: int,
        tile_height: int,
    ) -> None:
        """使用 Playwright 渲染 HTML 为 PNG。"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=dpr,
                    is_mobile=True,
                    has_touch=True,
                )

                page = context.new_page()
                page.goto(html_path.as_uri(), wait_until="networkidle")
                full_height = int(
                    page.evaluate("Math.ceil(document.documentElement.scrollHeight)")
                )

                if full_height <= max_full_page_height or Image is None:
                    page.screenshot(path=str(png_path), full_page=True)
                else:
                    self._capture_tiled_png(
                        page=page,
                        output_path=png_path,
                        viewport_height=height,
                        dpr=dpr,
                        full_height=full_height,
                        tile_height=tile_height,
                    )

                browser.close()
        except Exception as exc:
            raise RuntimeError(f"Playwright 渲染失败: {exc}") from exc

    def _capture_tiled_png(
        self,
        *,
        page,
        output_path: Path,
        viewport_height: int,
        dpr: int,
        full_height: int,
        tile_height: int,
    ) -> None:
        """Capture very long pages in tiles and stitch them to avoid blur."""
        if Image is None:
            page.screenshot(path=str(output_path), full_page=True)
            return

        step_height = max(256, min(tile_height, viewport_height))
        scroll_positions: list[int] = list(range(0, full_height, step_height))

        tile_paths: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="b2t-png-tiles-") as temp_dir:
            temp_root = Path(temp_dir)
            for idx, y in enumerate(scroll_positions):
                tile_path = temp_root / f"tile-{idx:04d}.png"
                page.evaluate("(offset) => window.scrollTo(0, offset)", y)
                page.wait_for_timeout(30)
                page.screenshot(
                    path=str(tile_path),
                    full_page=False,
                )
                tile_paths.append(tile_path)

            tile_target_heights: list[int] = []
            for y in scroll_positions:
                css_height = min(step_height, full_height - y)
                pixel_height = max(1, int(round(css_height * dpr)))
                tile_target_heights.append(pixel_height)

            with Image.open(tile_paths[0]) as first_img:
                merged_width = first_img.width

            merged_height = 0
            for tile_path, target_height in zip(tile_paths, tile_target_heights, strict=True):
                with Image.open(tile_path) as img:
                    merged_height += min(target_height, img.height)

            merged = Image.new("RGB", (merged_width, merged_height), "white")
            try:
                offset_y = 0
                for tile_path, target_height in zip(
                    tile_paths, tile_target_heights, strict=True
                ):
                    with Image.open(tile_path) as img:
                        crop_height = min(target_height, img.height)
                        if crop_height <= 0:
                            continue
                        segment = img.crop((0, 0, img.width, crop_height))
                        try:
                            merged.paste(segment, (0, offset_y))
                        finally:
                            segment.close()
                        offset_y += crop_height
                merged.save(output_path)
            finally:
                merged.close()
