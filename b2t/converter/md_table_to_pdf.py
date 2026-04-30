"""Convert a Markdown file containing one table into a styled PDF table."""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as exc:  # pragma: no cover - handled in CLI usage
    raise SystemExit(
        "reportlab is not installed. Please run: uv add reportlab or pip install reportlab"
    ) from exc


ALIGNMENT_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


def _display_width(text: str) -> int:
    """Rough visual width estimation (CJK chars count as 2)."""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return max(width, 1)


def _split_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells = [cell.strip() for cell in line.split("|")]
    return cells


def parse_markdown_table(md_text: str) -> list[list[str]]:
    """Parse markdown table text into rows."""
    lines = [line.rstrip() for line in md_text.splitlines() if line.strip()]
    table_lines = [line for line in lines if "|" in line]

    if len(table_lines) < 2:
        raise ValueError("No valid Markdown table detected")

    rows = [_split_table_row(line) for line in table_lines]
    if len(rows[0]) < 1:
        raise ValueError("Header is empty")

    align_index = (
        1 if len(rows) > 1 and all(ALIGNMENT_RE.match(c) for c in rows[1]) else -1
    )
    if align_index == 1:
        rows.pop(1)

    col_count = len(rows[0])
    normalized: list[list[str]] = []
    for row in rows:
        if len(row) < col_count:
            row = row + [""] * (col_count - len(row))
        elif len(row) > col_count:
            row = row[:col_count]
        normalized.append(row)

    if len(normalized) < 2:
        raise ValueError("Table needs at least a header and one data row")

    return normalized


def _build_col_widths(rows: list[list[str]], available_width: float) -> list[float]:
    col_count = len(rows[0])
    weights = []
    for col_idx in range(col_count):
        max_w = max(_display_width(row[col_idx]) for row in rows)
        weights.append(max(max_w, 6))

    total_weight = sum(weights)
    raw_widths = [available_width * (w / total_weight) for w in weights]

    min_col_width = 56.0
    widths = [max(w, min_col_width) for w in raw_widths]
    total = sum(widths)
    if total > available_width:
        scale = available_width / total
        widths = [w * scale for w in widths]

    return widths


def markdown_table_to_pdf(
    md_path: Path, output_path: Path, title: str | None = None
) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    rows = parse_markdown_table(md_text)

    # Use a built-in CJK CID font name available in reportlab.
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    pagesize = landscape(A4)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=pagesize,
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )
    available_width = pagesize[0] - doc.leftMargin - doc.rightMargin

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN",
        parent=styles["Heading2"],
        fontName="STSong-Light",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=10,
    )
    header_style = ParagraphStyle(
        "HeaderCN",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=13,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "CellCN",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )

    table_data: list[list[Paragraph]] = []
    for row_index, row in enumerate(rows):
        p_style = header_style if row_index == 0 else cell_style
        table_data.append(
            [Paragraph(cell.replace("\n", "<br/>"), p_style) for cell in row]
        )

    col_widths = _build_col_widths(rows, available_width)
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F6FEB")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F6F8FA")],
                ),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#8C959F")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story = []
    if title:
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 6))
    story.append(table)

    doc.build(story)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a .md file containing a single Markdown table to a styled PDF table (reportlab)"
    )
    parser.add_argument("input", help="输入 Markdown 文件路径")
    parser.add_argument(
        "-o",
        "--output",
        help="Output PDF path (defaults to same name as input with .pdf)",
        default=None,
    )
    parser.add_argument("--title", help="PDF title (optional)", default=None)
    args = parser.parse_args()

    md_path = Path(args.input).expanduser().resolve()
    if not md_path.exists():
        raise SystemExit(f"Input file does not exist: {md_path}")
    if md_path.suffix.lower() != ".md":
        raise SystemExit("Input file must be .md")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else md_path.with_suffix(".pdf")
    )

    result = markdown_table_to_pdf(md_path, output_path, title=args.title)
    print(f"PDF generated: {result}")


if __name__ == "__main__":
    main()
