"""Markdown to PDF conversion (via Pandoc + Playwright, avoids LaTeX)"""

import logging
from pathlib import Path
import re
import shutil
import subprocess

from b2t.stock_status import build_stock_table_cards_html, extract_stock_symbols
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
PANDOC_MARKDOWN_FORMAT = "markdown+pipe_tables+lists_without_preceding_blankline"

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
    .markdown-body .stock-table-cards {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin: 16px 0;
    }}
    .markdown-body .stock-table-card {{
      box-sizing: border-box;
      width: 100%;
      border: 1px solid #d0d7de;
      border-radius: 10px;
      padding: 12px 14px;
      background: #ffffff;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .markdown-body .stock-table-head {{
      display: flex;
      justify-content: flex-start;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .markdown-body .stock-table-head h3 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.3;
    }}
    .markdown-body .stock-table-head h3 span,
    .markdown-body .stock-table-head h3 strong {{
      vertical-align: baseline;
    }}
    .markdown-body .stock-table-head h3 strong {{
      margin-left: 8px;
      font-size: 16px;
      font-weight: 800;
      color: #64748b;
    }}
    .markdown-body .stock-status-up .stock-table-head h3,
    .markdown-body .stock-status-up .stock-table-head h3 strong,
    .markdown-body .stock-status-up .stock-metric-close strong,
    .markdown-body .stock-status-up .stock-metric-change strong {{
      color: #cf222e;
    }}
    .markdown-body .stock-status-down .stock-table-head h3,
    .markdown-body .stock-status-down .stock-table-head h3 strong,
    .markdown-body .stock-status-down .stock-metric-close strong,
    .markdown-body .stock-status-down .stock-metric-change strong {{
      color: #1a7f37;
    }}
    .markdown-body .stock-table-head p {{
      margin: 0;
      color: #57606a;
      font-size: 13px;
      line-height: 1.35;
    }}
    .markdown-body .stock-table-fields {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px 10px;
      margin-bottom: 8px;
    }}
    .markdown-body .stock-table-field {{
      min-width: 0;
    }}
    .markdown-body .stock-table-field span {{
      display: inline;
      color: #57606a;
      font-size: 13px;
      line-height: 1.2;
      margin: 0 4px 0 0;
      font-weight: 600;
    }}
    .markdown-body .stock-table-field p {{
      display: inline;
      margin: 0;
      color: #24292f;
      font-size: 14px;
      line-height: 1.45;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .markdown-body .stock-status-metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 6px 10px;
      padding-top: 8px;
      border-top: 1px solid #eef2f6;
    }}
    .markdown-body .stock-status-metric {{
      min-width: 0;
    }}
    .markdown-body .stock-status-metric span {{
      display: block;
      color: #57606a;
      font-size: 12px;
      line-height: 1.2;
      margin-bottom: 2px;
    }}
    .markdown-body .stock-status-metric strong {{
      display: block;
      color: #24292f;
      font-size: 14px;
      line-height: 1.3;
      white-space: normal;
      word-break: break-word;
      overflow-wrap: anywhere;
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
        is_table = options.get("is_table", False)
        as_of_date = options.get("as_of_date")
        enhance_stock_tables = options.get("enhance_stock_tables", False)

        body_html = (
            self._run_table_cards(input_path, as_of_date=as_of_date)
            if is_table
            else (
                self._run_markdown_with_stock_table_cards(
                    input_path,
                    as_of_date=as_of_date,
                )
                if enhance_stock_tables
                else self._run_pandoc(input_path)
            )
        )
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
        return self._run_pandoc_markdown(normalized_content, cwd=md_path.parent)

    def _run_pandoc_markdown(self, markdown_content: str, *, cwd: Path) -> str:

        try:
            proc = subprocess.run(
                ["pandoc", "-f", PANDOC_MARKDOWN_FORMAT, "-t", "html"],
                check=True,
                capture_output=True,
                text=True,
                input=markdown_content,
                cwd=str(cwd),
            )
            return proc.stdout
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc PDF conversion failed: {detail}") from exc

    def _run_table_cards(self, md_path: Path, *, as_of_date=None) -> str:
        markdown_content = md_path.read_text(encoding="utf-8")
        normalized_content = self._normalize_markdown_for_tables(markdown_content)
        cards_html = build_stock_table_cards_html(
            normalized_content,
            as_of_date=as_of_date,
        )
        if cards_html:
            return cards_html
        return self._run_pandoc(md_path)

    def _run_markdown_with_stock_table_cards(self, md_path: Path, *, as_of_date=None) -> str:
        markdown_content = md_path.read_text(encoding="utf-8")
        normalized_content = self._normalize_markdown_for_tables(markdown_content)
        lines = normalized_content.splitlines()
        if not lines:
            return self._run_pandoc_markdown(normalized_content, cwd=md_path.parent)

        fragments: list[str] = []
        markdown_buffer: list[str] = []
        index = 0

        while index < len(lines):
            if self._looks_like_markdown_table_start(lines, index):
                end = index + 2
                while end < len(lines) and self._looks_like_markdown_table_row(lines[end]):
                    end += 1
                table_markdown = "\n".join(lines[index:end]).strip()
                if table_markdown and extract_stock_symbols(table_markdown):
                    cards_html = build_stock_table_cards_html(
                        table_markdown,
                        as_of_date=as_of_date,
                    )
                    if cards_html:
                        if markdown_buffer:
                            fragments.append(
                                self._run_pandoc_markdown(
                                    self._join_markdown_lines(markdown_buffer),
                                    cwd=md_path.parent,
                                )
                            )
                            markdown_buffer = []
                        fragments.append(cards_html)
                        index = end
                        continue

            markdown_buffer.append(lines[index])
            index += 1

        if markdown_buffer:
            fragments.append(
                self._run_pandoc_markdown(
                    self._join_markdown_lines(markdown_buffer),
                    cwd=md_path.parent,
                )
            )

        return "\n".join(fragment for fragment in fragments if fragment)

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

    def _join_markdown_lines(self, lines: list[str]) -> str:
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _looks_like_markdown_table_start(self, lines: list[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        return self._looks_like_markdown_table_row(
            lines[index]
        ) and self._looks_like_markdown_table_separator(lines[index + 1])

    def _looks_like_markdown_table_row(self, line: str) -> bool:
        stripped = line.strip()
        if "|" not in stripped:
            return False
        cells = self._split_markdown_table_cells(stripped)
        return len(cells) >= 2 and any(cell for cell in cells)

    def _looks_like_markdown_table_separator(self, line: str) -> bool:
        if not self._looks_like_markdown_table_row(line):
            return False
        cells = self._split_markdown_table_cells(line)
        return bool(cells) and all(TABLE_DELIMITER_CELL_RE.match(cell.strip()) for cell in cells)

    def _split_markdown_table_cells(self, line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

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
