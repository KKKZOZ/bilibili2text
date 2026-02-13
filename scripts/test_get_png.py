#!/usr/bin/env python3
"""
md -> html -> png (mobile long screenshot) using Pandoc + Playwright

Requirements:
  - pandoc installed (e.g. brew install pandoc)
  - pip install playwright
  - playwright install chromium

Usage:
  python md2png.py input.md
  python md2png.py input.md -o out.png --width 390 --dpr 3
"""

import argparse
import sys
import subprocess
from pathlib import Path

# 允许在 scripts 目录直接运行时也能导入项目内的 b2t 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright


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


def run_pandoc(md_path: Path) -> str:
    """Return HTML body converted from markdown via pandoc."""
    # -f/-t make intent explicit; output goes to stdout
    proc = subprocess.run(
        ["pandoc", str(md_path), "-f", "markdown", "-t", "html"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("md", type=str, help="Input markdown file")
    parser.add_argument(
        "-o", "--out", type=str, default="output.png", help="Output PNG path"
    )
    parser.add_argument(
        "--html-out",
        type=str,
        default="output.html",
        help="Output HTML path (for debugging)",
    )
    parser.add_argument("--width", type=int, default=390, help="Viewport width")
    parser.add_argument(
        "--height",
        type=int,
        default=844,
        help="Viewport height (only affects initial viewport)",
    )
    parser.add_argument(
        "--dpr", type=int, default=3, help="Device scale factor (retina)"
    )
    parser.add_argument(
        "--css", type=str, default=GITHUB_CSS_URL, help="CSS href (URL or local path)"
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        help="Use secure=True (https). Usually keep False for file://",
    )
    args = parser.parse_args()

    md_path = Path(args.md).expanduser().resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_png = Path(args.out).expanduser().resolve()
    out_html = Path(args.html_out).expanduser().resolve()

    # Convert md -> HTML fragment (body)
    body_html = run_pandoc(md_path)

    # CSS href handling: if user provides a local css path, convert to file:// URI
    css_href = args.css
    css_path = Path(args.css).expanduser()
    if css_path.exists():
        css_href = css_path.resolve().as_uri()

    # Wrap into a full HTML document
    full_html = HTML_TEMPLATE.format(css_href=css_href, body_html=body_html)
    out_html.write_text(full_html, encoding="utf-8")

    # Render html -> png (mobile long screenshot)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=args.dpr,
            is_mobile=True,
            has_touch=True,
        )

        page = context.new_page()
        page.goto(out_html.as_uri(), wait_until="networkidle")
        page.screenshot(path=str(out_png), full_page=True)

        browser.close()

    print(f"HTML written: {out_html}")
    print(f"PNG written : {out_png}")


if __name__ == "__main__":
    main()
