"""Extract timestamped timelines from summary tables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from b2t.converter.markdown_formatter import format_markdown_with_markdownlint
from b2t.summarize.llm import extract_markdown_table_block

VIDEO_TIME_COLUMN = "视频时间"
TIMELINE_LABEL_COLUMNS = ("股票名称", "主题", "学习主题")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,4}):([0-5]\d)(?!\d)")
_INLINE_MARKER_RE = re.compile(r"(\*\*|__|`|~~)")


@dataclass(frozen=True)
class TimelineEntry:
    seconds: int
    timestamp: str
    stock_name: str
    stock_code: str


def _split_table_row(line: str) -> list[str]:
    text = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in text.split("|")]


def _clean_cell(value: str) -> str:
    text = _INLINE_MARKER_RE.sub("", value.strip())
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]+", " ", text).strip()


def _parse_table(table_markdown: str) -> tuple[list[str], list[list[str]]]:
    lines = [line for line in table_markdown.splitlines() if "|" in line]
    if len(lines) < 2:
        return [], []
    headers = [_clean_cell(cell) for cell in _split_table_row(lines[0])]
    rows = [_split_table_row(line) for line in lines[2:]]
    return headers, rows


def remove_video_time_column(table_markdown: str) -> str:
    """Remove the video-time column from a Markdown table."""
    lines = [line for line in table_markdown.splitlines() if "|" in line]
    if len(lines) < 2:
        return table_markdown
    headers = [_clean_cell(cell) for cell in _split_table_row(lines[0])]
    try:
        time_index = headers.index(VIDEO_TIME_COLUMN)
    except ValueError:
        return table_markdown

    rendered_rows: list[str] = []
    for line in lines:
        cells = _split_table_row(line)
        if time_index < len(cells):
            del cells[time_index]
        rendered_rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rendered_rows).strip() + "\n"


def _timeline_label_index(headers: list[str]) -> int:
    for column in TIMELINE_LABEL_COLUMNS:
        if column in headers:
            return headers.index(column)
    return next(
        (
            index
            for index, header in enumerate(headers)
            if header not in {VIDEO_TIME_COLUMN, "股票代码"}
        ),
        -1,
    )


def extract_timeline_entries(table_markdown: str) -> list[TimelineEntry]:
    """Return timestamped summary topics sorted by video time."""
    headers, rows = _parse_table(table_markdown)
    if VIDEO_TIME_COLUMN not in headers:
        return []

    time_index = headers.index(VIDEO_TIME_COLUMN)
    name_index = _timeline_label_index(headers)
    code_index = headers.index("股票代码") if "股票代码" in headers else -1
    entries: list[TimelineEntry] = []
    seen: set[tuple[int, str, str]] = set()

    for row in rows:
        if time_index >= len(row):
            continue
        stock_name = _clean_cell(row[name_index]) if 0 <= name_index < len(row) else "-"
        stock_code = _clean_cell(row[code_index]) if 0 <= code_index < len(row) else "-"
        for match in _TIME_RE.finditer(_clean_cell(row[time_index])):
            minutes = int(match.group(1))
            seconds_part = int(match.group(2))
            seconds = minutes * 60 + seconds_part
            timestamp = f"{minutes:02d}:{seconds_part:02d}"
            key = (seconds, stock_name, stock_code)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                TimelineEntry(
                    seconds=seconds,
                    timestamp=timestamp,
                    stock_name=stock_name or "-",
                    stock_code=stock_code or "-",
                )
            )

    return sorted(entries, key=lambda entry: (entry.seconds, entry.stock_name))


def export_summary_table_without_video_time(summary_path: Path | str) -> Path | None:
    """Export the last summary table without its video-time column."""
    summary_path = Path(summary_path)
    table_block = extract_markdown_table_block(
        summary_path.read_text(encoding="utf-8"), which="last"
    )
    if table_block is None:
        return None
    output_path = summary_path.with_name(f"{summary_path.stem}_table.md")
    output_path.write_text(remove_video_time_column(table_block), encoding="utf-8")
    format_markdown_with_markdownlint(output_path)
    return output_path


def export_summary_timeline_text(summary_path: Path | str) -> Path | None:
    """Export a Bilibili-comment-compatible timeline from the last summary table."""
    summary_path = Path(summary_path)
    table_block = extract_markdown_table_block(
        summary_path.read_text(encoding="utf-8"), which="last"
    )
    if table_block is None:
        return None
    entries = extract_timeline_entries(table_block)
    if not entries:
        return None

    output_path = summary_path.with_name(f"{summary_path.stem}_timeline.txt")
    lines = [
        (
            f"{entry.timestamp} {entry.stock_name}（{entry.stock_code}）"
            if entry.stock_code != "-"
            else f"{entry.timestamp} {entry.stock_name}"
        )
        for entry in entries
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
