"""LLM 总结"""

import logging
from pathlib import Path
import re

from b2t.config import (
    SummarizeConfig,
    SummaryPresetsConfig,
    resolve_summarize_api_base,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.markdown_formatter import format_markdown_with_markdownlint
from b2t.converter.md_table_to_pdf import markdown_table_to_pdf
from b2t.summarize.litellm_client import (
    collect_stream_result,
    stream_summary_completion,
)

logger = logging.getLogger(__name__)

TABLE_ROW_RE = re.compile(r"^\s*\|?.*\|.*\|?\s*$")
TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$"
)

def _extract_markdown_table_blocks(content: str) -> list[str]:
    """Extract markdown table blocks from mixed markdown content."""
    lines = content.splitlines()
    blocks: list[str] = []
    in_fence = False
    i = 0

    while i < len(lines) - 1:
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            i += 1
            continue

        if in_fence:
            i += 1
            continue

        header = lines[i]
        separator = lines[i + 1]
        if TABLE_ROW_RE.match(header) and TABLE_SEPARATOR_RE.match(separator):
            start = i
            end = i + 1
            j = i + 2
            while j < len(lines):
                row = lines[j]
                if not row.strip() or not TABLE_ROW_RE.match(row):
                    break
                end = j
                j += 1

            if end >= start + 2:
                blocks.append("\n".join(lines[start : end + 1]).strip() + "\n")

            i = j
            continue

        i += 1

    return blocks


def extract_markdown_table_block(
    content: str,
    *,
    which: str = "first",
) -> str | None:
    """Extract one markdown table block from content."""
    if which not in {"first", "last"}:
        raise ValueError("which must be 'first' or 'last'")
    blocks = _extract_markdown_table_blocks(content)
    if not blocks:
        return None
    if which == "last":
        return blocks[-1]
    return blocks[0]


def export_summary_table_markdown(
    summary_path: Path | str,
    *,
    which: str = "last",
) -> Path | None:
    """Extract one markdown table from summary and save it as *_table.md."""
    summary_path = Path(summary_path)
    content = summary_path.read_text(encoding="utf-8")
    table_block = extract_markdown_table_block(content, which=which)
    if table_block is None:
        logger.info("总结中未检测到 Markdown 表格，跳过表格 Markdown 导出")
        return None

    table_md_path = summary_path.with_name(f"{summary_path.stem}_table.md")
    table_md_path.write_text(table_block, encoding="utf-8")
    format_markdown_with_markdownlint(table_md_path)
    logger.info("总结表格 Markdown 已生成: %s", table_md_path)
    return table_md_path


def export_summary_table_pdf(
    summary_path: Path | str,
    *,
    which: str = "last",
) -> Path | None:
    """Extract one markdown table from summary and export it as a styled PDF."""
    table_md_path = export_summary_table_markdown(summary_path, which=which)
    if table_md_path is None:
        return None

    summary_path = Path(summary_path)
    table_pdf_path = summary_path.with_name(f"{summary_path.stem}_table.pdf")
    markdown_table_to_pdf(table_md_path, table_pdf_path, title="总结表格")
    logger.info("总结表格 PDF 已生成: %s", table_pdf_path)
    return table_pdf_path


def summarize(
    md_path: Path | str,
    config: SummarizeConfig,
    summary_presets: SummaryPresetsConfig,
    preset: str | None = None,
    profile: str | None = None,
) -> Path:
    """使用 LLM 对 Markdown 文件进行总结

    Args:
        md_path: Markdown 文件路径
        config: 总结配置
        summary_presets: 总结 preset 配置
        preset: 可选，覆盖默认 preset 名称
        profile: 可选，覆盖默认 summarize profile 名称

    Returns:
        生成的总结文件路径

    Raises:
        Exception: API 调用失败时抛出
    """
    md_path = Path(md_path)
    content = md_path.read_text(encoding="utf-8")

    preset_name = resolve_summary_preset_name(
        summarize=config,
        summary_presets=summary_presets,
        override=preset,
    )
    template = summary_presets.presets[preset_name].prompt_template
    prompt = template.format(content=content)
    selected_profile = (profile or config.profile).strip()
    model_profile = resolve_summarize_model_profile(config, override=selected_profile)

    logger.info(
        "正在使用 %s 模型进行总结（profile: %s, provider: %s, api_base: %s, preset: %s）...",
        model_profile.model,
        selected_profile,
        model_profile.provider,
        resolve_summarize_api_base(model_profile),
        preset_name,
    )

    if not model_profile.api_key:
        raise ValueError(
            f"summarize.profiles.{selected_profile}.api_key 为空，请先在配置文件中设置"
        )

    stream = stream_summary_completion(
        prompt=prompt,
        summarize_config=config,
        model_profile=model_profile,
        include_usage=True,
    )
    reasoning_content, content = collect_stream_result(stream)

    print("\n=== reasoning_content (reason_content) ===")
    if reasoning_content:
        print(reasoning_content)
        logger.info("模型返回 reasoning_content，长度: %d", len(reasoning_content))
    else:
        print("(empty)")
        logger.info("模型未返回 reasoning_content")
    print("=== /reasoning_content ===\n")

    if not content.strip():
        raise ValueError("LLM 未返回 content 字段，无法生成总结")
    summary = content

    summary_path = md_path.parent / f"{md_path.stem}_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    format_markdown_with_markdownlint(summary_path)

    logger.info("总结已保存到: %s", summary_path)
    return summary_path
