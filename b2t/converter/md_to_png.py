"""Markdown to PNG conversion (via Pandoc + Playwright)"""

import hashlib
import logging
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from urllib.error import URLError
from urllib.request import urlopen

from b2t.stock_status import build_stock_table_cards_html
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

GITHUB_CSS_URL = "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown.min.css"
LOCAL_CSS_CACHE_DIR = Path(tempfile.gettempdir()) / "b2t-assets"
LOCAL_CSS_FALLBACK_NAME = "github-markdown-fallback.css"
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
            font-family: "Noto Sans CJK SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
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
    .markdown-body .stock-table-cards {{
      display: grid;
      grid-template-columns: 1fr;
      justify-items: center;
      gap: 8px;
    }}
    .markdown-body .stock-table-card {{
      box-sizing: border-box;
      width: min(100%, 680px);
      border: 1px solid #d0d7de;
      border-radius: 8px;
      padding: 10px 12px;
      background: #ffffff;
    }}
    .markdown-body .stock-table-head {{
      display: flex;
      justify-content: flex-start;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }}
    .markdown-body .stock-table-head h3 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.25;
    }}
    .markdown-body .stock-table-head h3 span,
    .markdown-body .stock-table-head h3 strong {{
      vertical-align: baseline;
    }}
    .markdown-body .stock-table-head h3 strong {{
      margin-left: 8px;
      font-size: 17px;
      font-weight: 800;
      color: #64748b;
    }}
    .markdown-body .stock-status-up .stock-table-head h3 {{
      color: #cf222e;
    }}
    .markdown-body .stock-status-down .stock-table-head h3 {{
      color: #1a7f37;
    }}
    .markdown-body .stock-status-up .stock-table-head h3 strong {{
      color: #cf222e;
    }}
    .markdown-body .stock-status-down .stock-table-head h3 strong {{
      color: #1a7f37;
    }}
    .markdown-body .stock-status-up .stock-metric-close strong,
    .markdown-body .stock-status-up .stock-metric-change strong {{
      color: #cf222e;
    }}
    .markdown-body .stock-status-down .stock-metric-close strong,
    .markdown-body .stock-status-down .stock-metric-change strong {{
      color: #1a7f37;
    }}
    .markdown-body .stock-table-head p {{
      margin: 0;
      color: #57606a;
      font-size: 14px;
      line-height: 1.3;
    }}
    .markdown-body .stock-table-fields {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px 8px;
      margin-bottom: 6px;
    }}
    .markdown-body .stock-table-field {{
      min-width: 0;
    }}
    .markdown-body .stock-table-field span {{
      display: inline;
      color: #57606a;
      font-size: 14px;
      line-height: 1.2;
      margin: 0 4px 0 0;
    }}
    .markdown-body .stock-table-field p {{
      display: inline;
      margin: 0;
      color: #24292f;
      font-size: 15px;
      line-height: 1.45;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .markdown-body .stock-status-change {{
      flex-shrink: 0;
      color: #0969da;
      font-size: 17px;
      line-height: 1.25;
    }}
    .markdown-body .stock-status-metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 4px 8px;
      padding-top: 6px;
      border-top: 1px solid #eef2f6;
    }}
    .markdown-body .stock-status-metric {{
      min-width: 0;
    }}
    .markdown-body .stock-status-metric span {{
      display: block;
      color: #57606a;
      font-size: 13px;
      line-height: 1.2;
      margin-bottom: 2px;
    }}
    .markdown-body .stock-status-metric strong {{
      display: block;
      color: #24292f;
      font-size: 15px;
      line-height: 1.25;
      white-space: normal;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}

    @media (max-width: 520px) {{
      .markdown-body .mobile-table {{
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin: 16px 0;
      }}
      .markdown-body .mobile-table-row {{
        display: flex;
        flex-direction: column;
        border: 1px solid #d0d7de;
        border-radius: 12px;
        overflow: hidden;
        background: #ffffff;
      }}
      .markdown-body .mobile-table-cell {{
        display: grid;
        grid-template-columns: 72px minmax(0, 1fr);
        gap: 8px;
        border-top: 1px solid #eef2f6;
        padding: 8px 10px;
        font-size: 13px;
        line-height: 1.45;
      }}
      .markdown-body .mobile-table-row .mobile-table-cell:first-child {{
        border-top: 0;
      }}
      .markdown-body .mobile-table-label {{
        font-weight: 700;
        color: #57606a;
      }}
      .markdown-body .mobile-table-value {{
        min-width: 0;
        word-break: break-word;
        overflow-wrap: anywhere;
      }}
      .markdown-body .stock-status-metrics {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 5px 8px;
      }}
      .markdown-body .stock-table-fields {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="markdown-body">
  {body_html}
  </div>
  <script>
    if (window.matchMedia('(max-width: 520px)').matches) {{
      document.querySelectorAll('.markdown-body table').forEach((table) => {{
        const headers = Array.from(table.querySelectorAll('thead th')).map((th) => th.textContent.trim());
        const rows = Array.from(table.querySelectorAll('tbody tr'));
        if (headers.length === 0 || rows.length === 0) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'mobile-table';

        rows.forEach((row) => {{
          const rowEl = document.createElement('div');
          rowEl.className = 'mobile-table-row';

          Array.from(row.children).forEach((cell, index) => {{
            const cellEl = document.createElement('div');
            cellEl.className = 'mobile-table-cell';

            const labelEl = document.createElement('div');
            labelEl.className = 'mobile-table-label';
            labelEl.textContent = headers[index] || `列${{index + 1}}`;

            const valueEl = document.createElement('div');
            valueEl.className = 'mobile-table-value';
            valueEl.innerHTML = cell.innerHTML;

            cellEl.appendChild(labelEl);
            cellEl.appendChild(valueEl);
            rowEl.appendChild(cellEl);
          }});

          wrapper.appendChild(rowEl);
        }});

        table.replaceWith(wrapper);
      }});
    }}
  </script>
</body>
</html>
"""

FALLBACK_MARKDOWN_CSS = """
.markdown-body {
  color: #24292f;
  background-color: #ffffff;
    font-family: "Noto Sans CJK SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin-top: 24px;
  margin-bottom: 12px;
  line-height: 1.25;
}
.markdown-body p,
.markdown-body ul,
.markdown-body ol,
.markdown-body blockquote {
  margin-top: 0;
  margin-bottom: 14px;
}
.markdown-body code {
  background: rgba(175, 184, 193, 0.2);
  border-radius: 6px;
  padding: 0.15em 0.35em;
}
.markdown-body pre {
  background: #f6f8fa;
  padding: 14px;
  border-radius: 8px;
  overflow: auto;
}
.markdown-body pre code {
  background: transparent;
  padding: 0;
}
.markdown-body a {
  color: #0969da;
  text-decoration: none;
}
.markdown-body a:hover {
  text-decoration: underline;
}
.markdown-body hr {
  border: 0;
  border-top: 1px solid #d0d7de;
  margin: 24px 0;
}
"""


class _BrowserTask:
    def __init__(self, fn) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.error: Exception | None = None


class _ChromiumWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: queue.Queue[_BrowserTask | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._run,
                name="b2t-chromium-worker",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            raise RuntimeError(
                f"启动 Chromium 后台实例失败: {self._startup_error}"
            ) from self._startup_error

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._queue.put(None)
        thread.join(timeout=10)
        with self._lock:
            self._thread = None
            self._ready.clear()

    def submit(self, fn) -> None:
        self.start()
        task = _BrowserTask(fn)
        self._queue.put(task)
        task.done.wait()
        if task.error is not None:
            raise RuntimeError(f"Chromium 渲染任务失败: {task.error}") from task.error

    def _run(self) -> None:
        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                self._ready.set()

                while True:
                    task = self._queue.get()
                    if task is None:
                        break
                    try:
                        task.fn(browser)
                    except Exception as exc:  # noqa: BLE001
                        task.error = exc
                    finally:
                        task.done.set()
        except Exception as exc:  # noqa: BLE001
            self._startup_error = exc
            self._ready.set()
            while True:
                try:
                    task = self._queue.get_nowait()
                except queue.Empty:
                    break
                if task is None:
                    continue
                task.error = exc
                task.done.set()
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass


_CHROMIUM_WORKER = _ChromiumWorker()


class MarkdownToPngConverter:
    """Markdown to PNG converter (generates mobile-friendly long screenshots)."""

    def __init__(
        self,
        width: int = 390,
        height: int = 844,
        dpr: int = 3,
        css_url: str = GITHUB_CSS_URL,
    ):
        """
        Initialize the converter.

        Args:
            width: Viewport width (pixels)
            height: Viewport height (pixels)
            dpr: Device pixel ratio (for retina display)
            css_url: CSS stylesheet URL
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
        Convert Markdown to a PNG long screenshot.

        Args:
            input_path: Markdown file path
            output_path: Output PNG path (optional)
            is_table: Whether it is a table Markdown (uses wider canvas when True)
            **options: Extra options
                - width: Viewport width
                - height: Viewport height
                - dpr: Device pixel ratio
                - css_url: CSS stylesheet URL
                - keep_html: Whether to keep the intermediate HTML file
                - max_full_page_height: Max CSS height for single full_page screenshot
                - tile_height: CSS height per tile for tiled screenshots
                - as_of_date: Date for table stock status lookup

        Returns:
            Output PNG file path
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Markdown file does not exist: {input_path}")

        input_path = input_path.expanduser().resolve()
        if output_path is None:
            output_path = input_path.with_suffix(".png")
        else:
            output_path = output_path.expanduser().resolve()

        # Extract options
        width = 1200 if is_table else options.get("width", self.width)
        height = options.get("height", self.height)
        dpr = options.get("dpr", self.dpr)
        css_url = options.get("css_url", self.css_url)
        keep_html = options.get("keep_html", False)
        max_full_page_height = options.get("max_full_page_height", 12000)
        tile_height = options.get("tile_height", 1800)
        reuse_browser = options.get("reuse_browser", True)
        as_of_date = options.get("as_of_date")

        # Generate intermediate HTML
        html_path = output_path.with_suffix(".html")
        body_html = (
            self._run_table_cards(input_path, as_of_date=as_of_date)
            if is_table
            else self._run_pandoc(input_path)
        )

        # Resolve CSS href (prefer local cache to avoid external requests)
        css_href = self._resolve_css_href(css_url)

        # Generate full HTML
        full_html = HTML_TEMPLATE.format(css_href=css_href, body_html=body_html)
        html_path.write_text(full_html, encoding="utf-8")

        try:
            # Render HTML -> PNG
            self._render_html_to_png(
                html_path,
                output_path,
                width=width,
                height=height,
                dpr=dpr,
                max_full_page_height=max_full_page_height,
                tile_height=tile_height,
                reuse_browser=reuse_browser,
            )

            logger.info("PNG file generated: %s", output_path)
            return output_path
        finally:
            # Clean up intermediate HTML file (unless keep_html is set)
            if not keep_html and html_path.exists():
                html_path.unlink()

    def _run_pandoc(self, md_path: Path) -> str:
        """Convert Markdown to an HTML fragment using pandoc."""
        if shutil.which("pandoc") is None:
            raise RuntimeError("pandoc not found, please install pandoc first")

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
            raise RuntimeError(f"pandoc conversion failed: {detail}") from exc

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

    def _normalize_markdown_for_tables(self, content: str) -> str:
        """Normalize common full-width table characters before pandoc parsing."""
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

    def _resolve_css_href(self, css_url: str) -> str:
        requested = (css_url or "").strip()
        if requested:
            candidate = Path(requested)
            if candidate.exists():
                return candidate.resolve().as_uri()
            if requested.startswith(("http://", "https://")):
                cached = self._download_css_to_cache(requested)
                if cached is not None:
                    return cached.resolve().as_uri()
                logger.warning(
                    "Remote CSS unavailable, falling back to built-in local styles"
                )
                return self._ensure_fallback_css().resolve().as_uri()
            return requested
        return self._ensure_fallback_css().resolve().as_uri()

    def _download_css_to_cache(self, css_url: str) -> Path | None:
        LOCAL_CSS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(css_url.encode("utf-8")).hexdigest()[:16]
        target_path = LOCAL_CSS_CACHE_DIR / f"github-markdown-{digest}.css"
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path

        try:
            with urlopen(css_url, timeout=8) as response:
                css_content = response.read()
            if not css_content:
                raise ValueError("CSS file content is empty")
            temp_path = target_path.with_suffix(".tmp")
            temp_path.write_bytes(css_content)
            temp_path.replace(target_path)
            return target_path
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Failed to download Markdown CSS: %s", exc)
            return None

    def _ensure_fallback_css(self) -> Path:
        LOCAL_CSS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fallback_path = LOCAL_CSS_CACHE_DIR / LOCAL_CSS_FALLBACK_NAME
        if not fallback_path.exists() or fallback_path.stat().st_size == 0:
            fallback_path.write_text(FALLBACK_MARKDOWN_CSS, encoding="utf-8")
        return fallback_path

    def _render_with_browser(
        self,
        browser,
        *,
        html_path: Path,
        png_path: Path,
        width: int,
        height: int,
        dpr: int,
        max_full_page_height: int,
        tile_height: int,
    ) -> None:
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=dpr,
            is_mobile=True,
            has_touch=True,
        )
        try:
            page = context.new_page()
            page.goto(html_path.as_uri(), wait_until="domcontentloaded")
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
        finally:
            context.close()

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
        reuse_browser: bool,
    ) -> None:
        """Render HTML to PNG using Playwright."""
        try:
            if reuse_browser:
                _CHROMIUM_WORKER.submit(
                    lambda browser: self._render_with_browser(
                        browser,
                        html_path=html_path,
                        png_path=png_path,
                        width=width,
                        height=height,
                        dpr=dpr,
                        max_full_page_height=max_full_page_height,
                        tile_height=tile_height,
                    )
                )
                return

            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    self._render_with_browser(
                        browser,
                        html_path=html_path,
                        png_path=png_path,
                        width=width,
                        height=height,
                        dpr=dpr,
                        max_full_page_height=max_full_page_height,
                        tile_height=tile_height,
                    )
                finally:
                    browser.close()
        except Exception as exc:
            raise RuntimeError(f"Playwright rendering failed: {exc}") from exc

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
            for tile_path, target_height in zip(
                tile_paths, tile_target_heights, strict=True
            ):
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


class HtmlToPngConverter:
    """Convert pre-rendered HTML files to PNG (desktop view, suitable for fancy HTML pages)."""

    def __init__(
        self,
        width: int = 1280,
        height: int = 900,
        dpr: int = 2,
    ):
        self.width = width
        self.height = height
        self.dpr = dpr

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        if not input_path.exists():
            raise FileNotFoundError(f"HTML file does not exist: {input_path}")

        input_path = input_path.expanduser().resolve()
        if output_path is None:
            output_path = input_path.with_suffix(".png")
        else:
            output_path = output_path.expanduser().resolve()

        width = options.get("width", self.width)
        height = options.get("height", self.height)
        dpr = options.get("dpr", self.dpr)
        is_mobile = options.get("is_mobile", False)
        reuse_browser = options.get("reuse_browser", True)

        try:
            if reuse_browser:
                _CHROMIUM_WORKER.submit(
                    lambda browser: self._render(
                        browser,
                        html_path=input_path,
                        png_path=output_path,
                        width=width,
                        height=height,
                        dpr=dpr,
                        is_mobile=is_mobile,
                    )
                )
            else:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    try:
                        self._render(
                            browser,
                            html_path=input_path,
                            png_path=output_path,
                            width=width,
                            height=height,
                            dpr=dpr,
                            is_mobile=is_mobile,
                        )
                    finally:
                        browser.close()
        except Exception as exc:
            raise RuntimeError(f"Playwright rendering failed: {exc}") from exc

        logger.info("Fancy HTML PNG generated: %s", output_path)
        return output_path

    def _render(
        self,
        browser,
        *,
        html_path: Path,
        png_path: Path,
        width: int,
        height: int,
        dpr: int,
        is_mobile: bool,
    ) -> None:
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=dpr,
            is_mobile=is_mobile,
            has_touch=is_mobile,
        )
        try:
            page = context.new_page()
            page.goto(html_path.as_uri(), wait_until="domcontentloaded")
            if is_mobile:
                self._rewrite_tables_for_mobile(page)
            page.screenshot(path=str(png_path), full_page=True)
        finally:
            context.close()

    def _rewrite_tables_for_mobile(self, page) -> None:
        page.add_style_tag(
            content="""
            .table-wrap {
              overflow: visible !important;
              border: 0 !important;
              margin: 14px 0 !important;
            }
            .mobile-table {
              display: flex;
              flex-direction: column;
              gap: 12px;
              margin: 0;
            }
            .mobile-table-row {
              display: flex;
              flex-direction: column;
              border: 1px solid #E5E7EB;
              border-radius: 14px;
              overflow: hidden;
              background: #FFFFFF;
              box-shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
            }
            .mobile-table-cell {
              display: grid;
              grid-template-columns: 84px minmax(0, 1fr);
              gap: 10px;
              padding: 10px 12px;
              border-top: 1px solid #EEF2F7;
              font-size: 13px;
              line-height: 1.5;
            }
            .mobile-table-row .mobile-table-cell:first-child {
              border-top: 0;
            }
            .mobile-table-label {
              font-weight: 700;
              color: #6B7280;
            }
            .mobile-table-value {
              min-width: 0;
              word-break: break-word;
              overflow-wrap: anywhere;
              color: #111827;
            }
            .mobile-table-value > *:first-child {
              margin-top: 0 !important;
            }
            .mobile-table-value > *:last-child {
              margin-bottom: 0 !important;
            }
            .mobile-table-value p,
            .mobile-table-value ul,
            .mobile-table-value ol {
              margin-bottom: 0;
            }
            """
        )
        page.evaluate(
            """
            () => {
              document.querySelectorAll('table').forEach((table) => {
                const rows = Array.from(table.querySelectorAll('tbody tr'));
                if (rows.length === 0) return;

                const headerCells = Array.from(table.querySelectorAll('thead th'));
                const headers = headerCells.length > 0
                  ? headerCells.map((th) => th.textContent.trim())
                  : Array.from(rows[0]?.children || []).map((_, index) => `列${index + 1}`);

                const wrapper = document.createElement('div');
                wrapper.className = 'mobile-table';

                rows.forEach((row) => {
                  const rowEl = document.createElement('div');
                  rowEl.className = 'mobile-table-row';

                  Array.from(row.children).forEach((cell, index) => {
                    const cellEl = document.createElement('div');
                    cellEl.className = 'mobile-table-cell';

                    const labelEl = document.createElement('div');
                    labelEl.className = 'mobile-table-label';
                    labelEl.textContent = headers[index] || `Column ${index + 1}`;

                    const valueEl = document.createElement('div');
                    valueEl.className = 'mobile-table-value';
                    valueEl.innerHTML = cell.innerHTML;

                    cellEl.appendChild(labelEl);
                    cellEl.appendChild(valueEl);
                    rowEl.appendChild(cellEl);
                  });

                  wrapper.appendChild(rowEl);
                });

                const tableWrap = table.closest('.table-wrap');
                if (tableWrap) {
                  tableWrap.replaceChildren(wrapper);
                } else {
                  table.replaceWith(wrapper);
                }
              });
            }
            """
        )


def warmup_png_renderer() -> None:
    """Warm up the PNG renderer (launches a persistent Chromium instance)."""
    # Pre-download CSS to local cache to avoid waiting for external requests on first conversion.
    try:
        MarkdownToPngConverter()._resolve_css_href(GITHUB_CSS_URL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to warm up local CSS cache: %s", exc)
    _CHROMIUM_WORKER.start()


def shutdown_png_renderer() -> None:
    """Shut down the persistent PNG renderer."""
    _CHROMIUM_WORKER.stop()
