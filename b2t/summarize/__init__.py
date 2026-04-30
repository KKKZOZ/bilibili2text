"""LLM summarization subpackage."""

from b2t.summarize.fancy_html import generate_fancy_summary_html
from b2t.summarize.llm import extract_markdown_table_block, summarize

__all__ = [
    "extract_markdown_table_block",
    "generate_fancy_summary_html",
    "summarize",
]
