"""Markdown 移除最后一个表格"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _parse_table_cells(line: str) -> list[str]:
    """将一行 Markdown 表格拆分为单元格。"""
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
    """判断是否为 Markdown 表格分隔线（如 | --- | :---: |）。"""
    cells = _parse_table_cells(line)
    if not cells:
        return False
    return all(TABLE_DELIMITER_CELL_RE.match(cell) for cell in cells)


def _is_table_content_line(line: str) -> bool:
    """判断是否为 Markdown 表格内容行（表头/数据行）。"""
    cells = _parse_table_cells(line)
    if not cells:
        return False
    return not _is_table_delimiter_line(line)


class MarkdownRemoveTableConverter:
    """Markdown 移除最后一个表格转换器。"""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        从 Markdown 中移除最后一个表格。

        Args:
            input_path: Markdown 文件路径
            output_path: 输出路径（可选）
            **options: 额外选项（暂未使用）

        Returns:
            输出文件路径
        """
        if output_path is None:
            output_path = input_path.with_stem(f"{input_path.stem}_no_table")

        content = input_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # 通过“表头行 + 分隔线”识别所有表格块，最后移除末尾那一个完整表格块
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
            # 没有表格，直接复制
            logger.info("文件中没有找到表格，直接复制")
            output_path.write_text(content, encoding="utf-8")
            return output_path

        table_start, table_end = table_blocks[-1]

        # 向前查找表格标题（可能有）
        actual_start = table_start
        for i in range(table_start - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            if line.startswith("#"):
                actual_start = i
            break

        # 仅移除最后一个完整表格块（以及紧邻其上的标题）
        result_lines = lines[:actual_start] + lines[table_end:]
        result_content = "".join(result_lines)
        if result_content and not result_content.endswith("\n"):
            result_content += "\n"

        output_path.write_text(result_content, encoding="utf-8")
        logger.info("已移除最后一个表格，输出: %s", output_path)
        return output_path
