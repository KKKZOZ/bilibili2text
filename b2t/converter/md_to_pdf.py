"""Markdown to PDF conversion (via Pandoc + Playwright, avoids LaTeX)"""

import logging
from pathlib import Path
import re
import shutil
import subprocess

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

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
        "\u00a0": " ",
    }
)
PANDOC_MARKDOWN_FORMAT = (
    "markdown+pipe_tables+lists_without_preceding_blankline"
)

HTML_TEMPLATE = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{css_href}">
  <style>
    body {{
      margin: 0;
      padding: 28px;
      background: #fff;
    }}
    .markdown-body {{
      box-sizing: border-box;
      width: 100%;
      max-width: 100%;
      margin: 0 auto;
            font-family: "Noto Sans CJK SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 15px;
      line-height: 1.65;
      color: #24292f;
    }}
    .markdown-body table {{
      width: 100%;
      border-collapse: collapse;
      border-spacing: 0;
      display: table;
      table-layout: fixed;
      margin: 14px 0;
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


class MarkdownToPdfConverter:
    """Markdown to PDF converter."""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        Convert Markdown to HTML using pandoc, then generate a PDF with Playwright.

        Args:
            input_path: Markdown file path
            output_path: Output PDF path (optional)
            **options: Extra options

        Returns:
            Output PDF file path
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Markdown file does not exist: {input_path}")

        input_path = input_path.expanduser().resolve()
        if output_path is None:
            output_path = input_path.with_suffix(".pdf")
        else:
            output_path = output_path.expanduser().resolve()

        if shutil.which("pandoc") is None:
            raise RuntimeError("pandoc not found, please install pandoc first")

        css_url = options.get("css_url", GITHUB_CSS_URL)

        body_html = self._run_pandoc(input_path)
        css_href = css_url
        css_path = Path(css_url)
        if css_path.exists():
            css_href = css_path.resolve().as_uri()

        full_html = HTML_TEMPLATE.format(css_href=css_href, body_html=body_html)

        self._render_html_to_pdf(
            html_content=full_html,
            output_path=output_path,
        )
        logger.info("PDF file generated: %s", output_path)
        return output_path

    def _run_pandoc(self, md_path: Path) -> str:
        markdown_content = md_path.read_text(encoding="utf-8")
        normalized_content = self._normalize_markdown_for_tables(markdown_content)

        try:
            proc = subprocess.run(
                ["pandoc", "-f", PANDOC_MARKDOWN_FORMAT, "-t", "html"],
                check=True,
                capture_output=True,
                text=True,
                input=normalized_content,
                cwd=str(md_path.parent),
            )
            return proc.stdout
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc PDF conversion failed: {detail}") from exc

    def _normalize_markdown_for_tables(self, content: str) -> str:
        trailing_newline = content.endswith("\n")
        lines = content.splitlines()
        normalized_lines: list[str] = []

        for line in lines:
            normalized = line.replace("｜", "|").replace("\u00a0", " ")
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
        cells = [
            cell.strip().translate(TABLE_DASH_TRANSLATION) for cell in text.split("|")
        ]
        if not cells:
            return False
        return all(TABLE_DELIMITER_CELL_RE.match(cell) for cell in cells)

    def _render_html_to_pdf(self, *, html_content: str, output_path: Path) -> None:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.set_content(html_content, wait_until="networkidle")
                page.pdf(
                    path=str(output_path),
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "16mm",
                        "right": "12mm",
                        "bottom": "16mm",
                        "left": "12mm",
                    },
                )
                browser.close()
        except Exception as exc:
            raise RuntimeError(f"Playwright PDF rendering failed: {exc}") from exc
