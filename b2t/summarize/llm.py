"""LLM 总结"""

import logging
from pathlib import Path
import re

from openai import OpenAI

from b2t.config import (
    SummarizeConfig,
    SummaryPresetsConfig,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.md_table_to_pdf import markdown_table_to_pdf

logger = logging.getLogger(__name__)

TABLE_ROW_RE = re.compile(r"^\s*\|?.*\|.*\|?\s*$")
TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$"
)


def _is_openrouter_endpoint(endpoint: str) -> bool:
    return "openrouter.ai" in endpoint.lower()


def _get_message_field(message: object, field: str) -> object | None:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _to_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                parts.append(str(item))
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def _collect_stream_result(stream: object) -> tuple[str, str]:
    reasoning_parts: list[str] = []
    content_parts: list[str] = []

    for chunk in stream:
        choices = _get_message_field(chunk, "choices")
        if not isinstance(choices, list) or not choices:
            continue

        choice = choices[0]
        delta = _get_message_field(choice, "delta")
        if delta is None:
            continue

        reasoning_piece = _to_text(_get_message_field(delta, "reasoning_content"))
        content_piece = _to_text(_get_message_field(delta, "content"))

        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
        if content_piece:
            content_parts.append(content_piece)

    return "".join(reasoning_parts), "".join(content_parts)


def _extract_first_markdown_table_block(content: str) -> str | None:
    """Extract the first markdown table block from mixed markdown content."""
    lines = content.splitlines()
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
                return "\n".join(lines[start : end + 1]).strip() + "\n"

            i = j
            continue

        i += 1

    return None


def export_summary_table_pdf(summary_path: Path | str) -> Path | None:
    """Extract first markdown table from summary and export it as a styled PDF."""
    summary_path = Path(summary_path)
    content = summary_path.read_text(encoding="utf-8")
    table_block = _extract_first_markdown_table_block(content)
    if table_block is None:
        logger.info("总结中未检测到 Markdown 表格，跳过 PDF 表格导出")
        return None

    table_md_path = summary_path.with_name(f"{summary_path.stem}_table.md")
    table_pdf_path = summary_path.with_name(f"{summary_path.stem}_table.pdf")
    table_md_path.write_text(table_block, encoding="utf-8")
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
        "正在使用 %s 模型进行总结（profile: %s, preset: %s）...",
        model_profile.model,
        selected_profile,
        preset_name,
    )

    client = OpenAI(
        base_url=model_profile.endpoint,
        api_key=model_profile.api_key,
    )

    request_kwargs = {
        "model": model_profile.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "extra_body": {"enable_thinking": config.enable_thinking},
    }
    if _is_openrouter_endpoint(model_profile.endpoint) and model_profile.providers:
        request_kwargs["extra_body"]["provider"] = {
            "order": list(model_profile.providers),
        }
        logger.info(
            "OpenRouter provider 已指定: %s",
            ", ".join(model_profile.providers),
        )

    stream = client.chat.completions.create(**request_kwargs)
    reasoning_content, content = _collect_stream_result(stream)

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

    logger.info("总结已保存到: %s", summary_path)
    return summary_path
