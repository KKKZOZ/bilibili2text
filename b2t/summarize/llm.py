"""LLM Summarization"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from b2t.config import (
    SummarizeConfig,
    SummaryPresetsConfig,
    resolve_summarize_api_base,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.markdown_formatter import format_markdown_with_markdownlint
from b2t.converter.md_table_to_pdf import markdown_table_to_pdf
from b2t.download.metadata import VideoMetadata
from b2t.summarize.litellm_client import (
    collect_stream_result,
    isolated_summary_client,
    stream_summary_completion,
)
from b2t.summary_context import (
    render_summary_context_block,
    resolve_author_summary_context,
)

logger = logging.getLogger(__name__)

CUSTOM_SUMMARY_PRESET_VALUE = "__user_custom__"
TABLE_ROW_RE = re.compile(r"^\s*\|?.*\|.*\|?\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_BVID_PREFIX_RE = re.compile(r"^(BV[0-9A-Za-z]{10})[_-]?", re.IGNORECASE)
_COMMENT_TOTAL_RE = re.compile(r"^- 评论区总数:\s*(\d+)\s*$", re.MULTILINE)
_COMMENT_FETCHED_RE = re.compile(r"^- 已抓取主评论:\s*(\d+)\s*$", re.MULTILINE)
_COMMENT_FETCHED_REPLIES_RE = re.compile(r"^- 已抓取子评论:\s*(\d+)\s*$", re.MULTILINE)


def validate_summary_prompt_template(template: str) -> str:
    """Validate a user-provided summary prompt template."""
    cleaned = template.strip()
    if not cleaned:
        raise ValueError("总结模板不能为空")
    if "{content}" not in cleaned:
        raise ValueError("总结模板必须包含 {content} 占位符")
    return cleaned


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
        logger.info("No table detected in summary, skipping table Markdown export")
        return None

    table_md_path = summary_path.with_name(f"{summary_path.stem}_table.md")
    table_md_path.write_text(table_block, encoding="utf-8")
    format_markdown_with_markdownlint(table_md_path)
    logger.info("Summary table Markdown generated: %s", table_md_path)
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
    markdown_table_to_pdf(table_md_path, table_pdf_path, title="Summary Table")
    logger.info("Summary table PDF generated: %s", table_pdf_path)
    return table_pdf_path


def _infer_video_title_from_markdown_path(md_path: Path) -> str:
    stem = md_path.stem
    if stem.lower().endswith("_transcription"):
        stem = stem[:-14]
    inferred = _BVID_PREFIX_RE.sub("", stem, count=1).strip("_- ")
    return inferred or stem or "Untitled Video"


def _parse_pubdate_datetime(pubdate: str) -> datetime | None:
    cleaned = pubdate.strip()
    if not cleaned:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    normalized = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


def _format_publish_time(metadata: VideoMetadata | None) -> str:
    if metadata is None:
        return "Unknown"

    pubdate = (metadata.pubdate or "").strip()
    if metadata.pubdate_timestamp > 0:
        if not pubdate:
            return datetime.fromtimestamp(metadata.pubdate_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return pubdate

    published_at = _parse_pubdate_datetime(pubdate)
    if published_at is not None:
        return pubdate or published_at.strftime("%Y-%m-%d %H:%M:%S")

    return pubdate or "Unknown"


def _demote_top_level_headings(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized_lines: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            normalized_lines.append(line)
            continue

        if not in_fence and stripped.startswith("# "):
            leading = line[: len(line) - len(stripped)]
            normalized_lines.append(f"{leading}## {stripped[2:].strip()}")
            continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines).strip()


def post_process_summary_markdown(
    summary: str,
    *,
    metadata: VideoMetadata | None = None,
    fallback_title: str,
    now: datetime | None = None,
) -> str:
    title = (
        (metadata.title.strip() if metadata else "")
        or fallback_title.strip()
        or "Untitled Video"
    )
    author = (metadata.author.strip() if metadata else "") or "Unknown"
    publish_time = _format_publish_time(metadata)
    body = _demote_top_level_headings(summary.strip())

    parts = [
        f"# {title}",
        "",
        f"- Creator: {author}",
        f"- Published: {publish_time}",
    ]
    if body:
        parts.extend(["", body])
    return "\n".join(parts).rstrip() + "\n"


def summarize_comment_viewpoints(
    comments_markdown: str,
    config: SummarizeConfig,
    *,
    profile: str | None = None,
    isolated_client: bool = False,
) -> str:
    """Summarize selected platform comments into a Markdown section."""
    content = comments_markdown.strip()
    if not content:
        return ""

    selected_profile = (profile or config.profile).strip()
    model_profile = resolve_summarize_model_profile(config, override=selected_profile)
    if not model_profile.api_key:
        raise ValueError(
            f"summarize.profiles.{selected_profile}.api_key is empty, please set it in the config file"
        )

    prompt = (
        "请基于下面的视频或播客精选评论，提炼观众讨论中的相关观点，"
        "输出 Markdown 片段并以二级标题 `## 精选评论观点` 开头。\n"
        "要求：\n"
        "- 总结高频观点、争议点、补充信息和情绪倾向。\n"
        "- 先过滤无信息量或与视频、播客主题无关的评论，不得将其纳入观点、"
        "情绪倾向或频次判断。\n"
        "- 应过滤的内容包括但不限于：`第一`、`前排` 等抢楼评论；"
        "仅 @ 他人或机器人的评论；`@xxx，请帮我总结一下这个视频` 等求总结、"
        "求解析指令；纯表情、无意义符号、重复刷屏、广告引流和无关闲聊。\n"
        "- 不要仅因观点低频或表达负面就过滤；包含具体事实、论据、纠错、"
        "反例或与主题相关质疑的评论应保留。\n"
        "- 对过滤后的有效评论逐条进行舆情分类。每条主评论和每条子评论各计 1 条，"
        "不得按点赞数加权，也不得把同一条评论重复计数。\n"
        "- 正面、负面判断的是评论者对视频或播客内容、核心观点或创作者表达的态度，"
        "不是评论所讨论事件本身的正负性质。认可、赞同、支持归为正面；反对、批评、"
        "质疑归为负面；提问、事实补充、混合态度或态度不明确归为中性。\n"
        "- 固定输出 `### 舆情统计` 小节，依次列出 `有效评论`、`正面`、`负面`、"
        "`中性`、`已过滤` 的条数；正面、负面、中性同时给出占有效评论的百分比，"
        "保留 1 位小数。必须满足 正面 + 负面 + 中性 = 有效评论。有效评论为 0 时"
        "百分比均写 `0.0%`。\n"
        "- 舆情数量只能依据本次提供的评论逐条统计，不得依据平台显示的评论区总数"
        "推算；无法可靠完成统计时应明确说明，不得编造数量。\n"
        "- 重点关注标记为 `UP主回复` 的内容。\n"
        "- 涉及 UP 主回复的结论或原话必须使用 Markdown 加粗。\n"
        "- 不要输出表格。\n"
        "- 不要编造评论中不存在的观点。\n\n"
        f"{content}"
    )
    client_context = (
        isolated_summary_client(model_profile) if isolated_client else nullcontext(None)
    )
    with client_context as client:
        stream = stream_summary_completion(
            prompt=prompt,
            summarize_config=config,
            model_profile=model_profile,
            include_usage=True,
            client=client,
        )
        _, summary = collect_stream_result(stream)
    return summary.strip()


def _extract_comment_summary_stats(comments_markdown: str) -> str:
    total_match = _COMMENT_TOTAL_RE.search(comments_markdown)
    fetched_match = _COMMENT_FETCHED_RE.search(comments_markdown)
    fetched_replies_match = _COMMENT_FETCHED_REPLIES_RE.search(comments_markdown)
    total_count = total_match.group(1) if total_match else "未知"
    fetched_main_count = fetched_match.group(1) if fetched_match else "未知"
    fetched_reply_count = (
        fetched_replies_match.group(1) if fetched_replies_match else "未知"
    )
    if fetched_match and fetched_replies_match:
        summarized_count = str(int(fetched_main_count) + int(fetched_reply_count))
    else:
        summarized_count = "未知"
    up_reply_count = comments_markdown.count("**UP主回复**")

    return "\n".join(
        (
            "评论统计：",
            "",
            f"- 视频总评论数: {total_count}",
            f"- 本次总结评论数: {summarized_count}（主评论 {fetched_main_count}，子评论 {fetched_reply_count}）",
            f"- UP主回复评论数: {up_reply_count}",
        )
    )


def _prepend_comment_summary_stats(
    comment_summary: str,
    comments_markdown: str,
) -> str:
    stats = _extract_comment_summary_stats(comments_markdown)
    stripped = comment_summary.strip()
    heading = "## 精选评论观点"
    if stripped.startswith(heading):
        return stripped.replace(heading, f"{heading}\n\n{stats}", 1)
    return f"{heading}\n\n{stats}\n\n{stripped}"


def append_comment_summary_to_markdown(
    summary_path: Path | str,
    comments_markdown: str,
    config: SummarizeConfig,
    *,
    profile: str | None = None,
) -> bool:
    """Append summarized comment viewpoints to an existing summary file."""
    comment_summary = summarize_comment_viewpoints(
        comments_markdown,
        config,
        profile=profile,
    )
    return append_comment_summary_text_to_markdown(
        summary_path,
        comment_summary,
        comments_markdown,
    )


def append_comment_summary_text_to_markdown(
    summary_path: Path | str,
    comment_summary: str,
    comments_markdown: str,
) -> bool:
    """Append an already-generated comment summary to a summary file."""
    if not comment_summary.strip():
        return False
    comment_summary = _prepend_comment_summary_stats(
        comment_summary,
        comments_markdown,
    )

    summary_path = Path(summary_path)
    original = summary_path.read_text(encoding="utf-8").rstrip()
    summary_path.write_text(
        f"{original}\n\n{comment_summary}\n",
        encoding="utf-8",
    )
    format_markdown_with_markdownlint(summary_path)
    return True


def summarize_with_comment_viewpoints(
    md_path: Path | str,
    config: SummarizeConfig,
    summary_presets: SummaryPresetsConfig,
    *,
    comments_markdown: str = "",
    summary_context_config=None,
    preset: str | None = None,
    profile: str | None = None,
    prompt_template_override: str | None = None,
    metadata: VideoMetadata | None = None,
) -> Path:
    """Generate transcript and comment summaries concurrently, then combine them."""
    comments_content = comments_markdown.strip()
    if not comments_content:
        return summarize(
            md_path,
            config,
            summary_presets,
            summary_context_config=summary_context_config,
            preset=preset,
            profile=profile,
            prompt_template_override=prompt_template_override,
            metadata=metadata,
        )

    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="b2t-summary"
    ) as executor:
        summary_future = executor.submit(
            summarize,
            md_path,
            config,
            summary_presets,
            summary_context_config=summary_context_config,
            preset=preset,
            profile=profile,
            prompt_template_override=prompt_template_override,
            metadata=metadata,
            isolated_client=True,
        )
        comment_future = executor.submit(
            summarize_comment_viewpoints,
            comments_content,
            config,
            profile=profile,
            isolated_client=True,
        )

        summary_path = summary_future.result()
        try:
            comment_summary = comment_future.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to summarize platform comments: %s", exc)
            return summary_path

    append_comment_summary_text_to_markdown(
        summary_path,
        comment_summary,
        comments_content,
    )
    return summary_path


def summarize(
    md_path: Path | str,
    config: SummarizeConfig,
    summary_presets: SummaryPresetsConfig,
    summary_context_config=None,
    preset: str | None = None,
    profile: str | None = None,
    prompt_template_override: str | None = None,
    metadata: VideoMetadata | None = None,
    isolated_client: bool = False,
) -> Path:
    """Summarize a Markdown file using an LLM

    Args:
        md_path: Markdown file path
        config: Summarization config
        summary_presets: Summary preset config
        summary_context_config: Optional author-specific context config
        preset: Optional, override the default preset name
        profile: Optional, override the default summary profile name
        prompt_template_override: Optional, override the preset prompt template

    Returns:
        Path to the generated summary file

    Raises:
        Exception: Raised when the API call fails
    """
    md_path = Path(md_path)
    content = md_path.read_text(encoding="utf-8")

    cleaned_preset = (preset or "").strip() or None
    if cleaned_preset == CUSTOM_SUMMARY_PRESET_VALUE:
        if prompt_template_override is None:
            raise ValueError("用户自定义总结模板不能为空")
        preset_name = CUSTOM_SUMMARY_PRESET_VALUE
        template = validate_summary_prompt_template(prompt_template_override)
    else:
        preset_name = resolve_summary_preset_name(
            summarize=config,
            summary_presets=summary_presets,
            override=cleaned_preset,
        )
        template = (
            validate_summary_prompt_template(prompt_template_override)
            if prompt_template_override is not None
            else summary_presets.presets[preset_name].prompt_template
        )
    resolved_context = resolve_author_summary_context(summary_context_config, metadata)
    context_block = render_summary_context_block(resolved_context)
    prompt_content = content
    if context_block:
        prompt_content = f"{context_block}\n\n转录正文如下：\n\n{content}"
        logger.info(
            "Injected summary context for author `%s` (%s)",
            resolved_context.author.id,
            resolved_context.matched_by,
        )
    prompt = template.format(content=prompt_content)
    selected_profile = (profile or config.profile).strip()
    model_profile = resolve_summarize_model_profile(config, override=selected_profile)

    logger.info(
        "Summarizing with %s model (profile: %s, provider: %s, api_base: %s, preset: %s)...",
        model_profile.model,
        selected_profile,
        model_profile.provider,
        resolve_summarize_api_base(model_profile),
        preset_name,
    )

    if not model_profile.api_key:
        raise ValueError(
            f"summarize.profiles.{selected_profile}.api_key is empty, please set it in the config file"
        )

    client_context = (
        isolated_summary_client(model_profile) if isolated_client else nullcontext(None)
    )
    with client_context as client:
        stream = stream_summary_completion(
            prompt=prompt,
            summarize_config=config,
            model_profile=model_profile,
            include_usage=True,
            client=client,
        )
        reasoning_content, content = collect_stream_result(stream)

    print("\n=== reasoning_content (reason_content) ===")
    if reasoning_content:
        print(reasoning_content)
        logger.info(
            "Model returned reasoning_content, length: %d", len(reasoning_content)
        )
    else:
        print("(empty)")
        logger.info("Model returned no reasoning_content")
    print("=== /reasoning_content ===\n")

    if not content.strip():
        raise ValueError("LLM did not return a content field, cannot generate summary")
    summary = post_process_summary_markdown(
        content,
        metadata=metadata,
        fallback_title=_infer_video_title_from_markdown_path(md_path),
    )

    summary_path = md_path.parent / f"{md_path.stem}_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    format_markdown_with_markdownlint(summary_path)

    logger.info("Summary saved to: %s", summary_path)
    return summary_path
