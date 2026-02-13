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


def _resolve_openrouter_max_tokens(model: str) -> int | None:
    normalized = model.strip().lower()
    if "qwen3-max-thinking" in normalized:
        return 32768
    if "qwen3-max" in normalized:
        return 32768
    return None


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


def _extract_reasoning_text(delta: object) -> str:
    reasoning_content = _get_message_field(delta, "reasoning_content")
    reasoning_content_text = _to_text(reasoning_content)
    if reasoning_content_text:
        return reasoning_content_text

    reasoning_alias = _get_message_field(delta, "reasoning")
    reasoning_alias_text = _to_text(reasoning_alias)
    if reasoning_alias_text:
        return reasoning_alias_text

    reasoning_details = _get_message_field(delta, "reasoning_details")
    parts: list[str] = []
    if isinstance(reasoning_details, list):
        for item in reasoning_details:
            detail_text = _to_text(_get_message_field(item, "text"))
            if detail_text:
                if not parts or parts[-1] != detail_text:
                    parts.append(detail_text)
                continue

            summary = _get_message_field(item, "summary")
            summary_text = _to_text(summary)
            if summary_text:
                if not parts or parts[-1] != summary_text:
                    parts.append(summary_text)

    return "".join(parts)


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

        reasoning_piece = _extract_reasoning_text(delta)
        content_piece = _to_text(_get_message_field(delta, "content"))

        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
        if content_piece:
            content_parts.append(content_piece)

    return "".join(reasoning_parts), "".join(content_parts)


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
        "正在使用 %s 模型进行总结（profile: %s, preset: %s）...",
        model_profile.model,
        selected_profile,
        preset_name,
    )

    client = OpenAI(
        base_url=model_profile.endpoint,
        api_key=model_profile.api_key,
    )

    is_openrouter = _is_openrouter_endpoint(model_profile.endpoint)
    extra_body: dict[str, object]
    if is_openrouter:
        if config.enable_thinking:
            extra_body = {
                "reasoning": {"enabled": True},
                # Legacy fallback accepted by OpenRouter.
                "include_reasoning": True,
            }
        else:
            extra_body = {
                "reasoning": {"effort": "none", "exclude": True},
                "include_reasoning": False,
            }
    else:
        extra_body = {"enable_thinking": config.enable_thinking}

    request_kwargs = {
        "model": model_profile.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "extra_body": extra_body,
    }
    if is_openrouter:
        max_tokens = _resolve_openrouter_max_tokens(model_profile.model)
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
    if is_openrouter and model_profile.providers:
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
