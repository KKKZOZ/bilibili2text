"""Markdown 转 PNG（通过 Pandoc + Playwright）"""

import logging
from pathlib import Path
import shutil
import subprocess

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

GITHUB_CSS_URL = "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown.min.css"

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
      display: block;
      overflow-x: auto;
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

        Returns:
            输出 PNG 文件路径
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Markdown 文件不存在: {input_path}")

        if output_path is None:
            output_path = input_path.with_suffix(".png")

        # 提取选项
        width = 1200 if is_table else options.get("width", self.width)
        height = options.get("height", self.height)
        dpr = options.get("dpr", self.dpr)
        css_url = options.get("css_url", self.css_url)
        keep_html = options.get("keep_html", False)

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

        try:
            proc = subprocess.run(
                ["pandoc", str(md_path), "-f", "markdown", "-t", "html"],
                check=True,
                capture_output=True,
                text=True,
            )
            return proc.stdout
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc 转换失败: {detail}") from exc

    def _render_html_to_png(
        self,
        html_path: Path,
        png_path: Path,
        *,
        width: int,
        height: int,
        dpr: int,
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
                page.screenshot(path=str(png_path), full_page=True)

                browser.close()
        except Exception as exc:
            raise RuntimeError(f"Playwright 渲染失败: {exc}") from exc
