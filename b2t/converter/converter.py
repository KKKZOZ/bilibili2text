"""统一的文件转换接口。"""

from enum import Enum
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class ConversionFormat(str, Enum):
    """支持的转换格式。"""

    TXT = "txt"
    PDF = "pdf"
    PNG = "png"
    HTML = "html"
    MD_NO_TABLE = "md_no_table"  # Markdown 移除表格


class Converter(Protocol):
    """转换器协议。"""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """执行转换并返回输出文件路径。"""
        ...


def get_converter(
    source_format: str,
    target_format: ConversionFormat,
) -> Converter:
    """根据源格式和目标格式返回对应的转换器。"""
    source = source_format.lower().lstrip(".")

    if target_format == ConversionFormat.TXT:
        if source in ("md", "markdown"):
            from b2t.converter.md_to_txt import MarkdownToTextConverter

            return MarkdownToTextConverter()

    if target_format == ConversionFormat.PDF:
        if source in ("md", "markdown"):
            from b2t.converter.md_to_pdf import MarkdownToPdfConverter

            return MarkdownToPdfConverter()

    if target_format == ConversionFormat.PNG:
        if source in ("md", "markdown"):
            from b2t.converter.md_to_png import MarkdownToPngConverter

            return MarkdownToPngConverter()
        if source == "html":
            from b2t.converter.md_to_png import HtmlToPngConverter

            return HtmlToPngConverter()

    if target_format == ConversionFormat.HTML:
        if source in ("md", "markdown"):
            from b2t.converter.md_to_html import MarkdownToHtmlConverter

            return MarkdownToHtmlConverter()

    if target_format == ConversionFormat.MD_NO_TABLE:
        if source in ("md", "markdown"):
            from b2t.converter.md_remove_table import MarkdownRemoveTableConverter

            return MarkdownRemoveTableConverter()

    raise ValueError(
        f"不支持的转换: {source} -> {target_format.value}"
    )


def convert_file(
    input_path: Path | str,
    target_format: ConversionFormat,
    output_path: Path | str | None = None,
    **options,
) -> Path:
    """
    通用文件转换函数。

    Args:
        input_path: 输入文件路径
        target_format: 目标格式
        output_path: 输出文件路径（可选，默认自动生成）
        **options: 传递给转换器的额外选项

    Returns:
        输出文件路径
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    source_format = input_path.suffix
    converter = get_converter(source_format, target_format)

    if output_path is not None:
        output_path = Path(output_path)

    return converter.convert(input_path, output_path, **options)
