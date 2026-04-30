"""Markdown - remove the last table"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _parse_table_cells(line: str) -> list[str]:
    """Split a Markdown table row into cells."""
    text = line.strip()
    if "|" not in text:
        return []

    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]

    cells = [cell.strip() for cell in text.split("|")]
    return cells if cells else []


def _is_table_delimiter_line(line: str) -> bool:
    """Check if a line is a Markdown table separator (e.g., | --- | :---: |)."""
    cells = _parse_table_cells(line)
    if not cells:
        return False
    return all(TABLE_DELIMITER_CELL_RE.match(cell) for cell in cells)


def _is_table_content_line(line: str) -> bool:
    """Check if a line is a Markdown table content line (header/data row)."""
    cells = _parse_table_cells(line)
    if not cells:
        return False
    return not _is_table_delimiter_line(line)


class MarkdownRemoveTableConverter:
    """Markdown converter that removes the last table."""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        Remove the last table from Markdown.

        Args:
            input_path: Markdown file path
            output_path: Output path (optional)
            **options: Extra options (currently unused)

        Returns:
            Output file path
        """
        if output_path is None:
            output_path = input_path.with_stem(f"{input_path.stem}_no_table")

        content = input_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # Identify all table blocks via “header row + separator line”, then remove the last complete block
        table_blocks: list[tuple[int, int]] = []
        for i in range(len(lines) - 1):
            if not _is_table_content_line(lines[i]):
                continue
            if not _is_table_delimiter_line(lines[i + 1]):
                continue

            end = i + 2
            while end < len(lines) and _is_table_content_line(lines[end]):
                end += 1
            table_blocks.append((i, end))

        if not table_blocks:
            # No table found, copy directly
            logger.info("No table found in file, copying directly")
            output_path.write_text(content, encoding="utf-8")
            return output_path

        table_start, table_end = table_blocks[-1]

        # Look backwards for a table heading (if any)
        actual_start = table_start
        for i in range(table_start - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            if line.startswith("#"):
                actual_start = i
            break

        # Only remove the last complete table block (and any heading directly above it)
        result_lines = lines[:actual_start] + lines[table_end:]
        result_content = "".join(result_lines)
        if result_content and not result_content.endswith("\n"):
            result_content += "\n"

        output_path.write_text(result_content, encoding="utf-8")
        logger.info("Removed last table, output: %s", output_path)
        return output_path
