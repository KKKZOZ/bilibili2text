"""LLM Summarization"""

import logging
from datetime import datetime
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
from b2t.download.metadata import VideoMetadata
from b2t.summarize.litellm_client import (
    collect_stream_result,
    stream_summary_completion,
)
from b2t.summary_context import (
    render_summary_context_block,
    resolve_author_summary_context,
)

logger = logging.getLogger(__name__)

TABLE_ROW_RE = re.compile(r"^\s*\|?.*\|.*\|?\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_BVID_PREFIX_RE = re.compile(r"^(BV[0-9A-Za-z]{10})[_-]?", re.IGNORECASE)


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


def _format_publish_age(
    metadata: VideoMetadata | None,
    *,
    now: datetime | None = None,
) -> str:
    if metadata is None:
        return "Unknown"

    pubdate = (metadata.pubdate or "").strip()
    published_at: datetime | None = None
    if metadata.pubdate_timestamp > 0:
        published_at = datetime.fromtimestamp(metadata.pubdate_timestamp)
        if not pubdate:
            pubdate = published_at.strftime("%Y-%m-%d %H:%M:%S")
    else:
        published_at = _parse_pubdate_datetime(pubdate)

    if published_at is None:
        return pubdate or "Unknown"

    current = now or datetime.now()
    delta_seconds = max(0, int((current - published_at).total_seconds()))
    if delta_seconds < 60:
        relative = "just now"
    elif delta_seconds < 3600:
        relative = f"{delta_seconds // 60} minutes ago"
    elif delta_seconds < 86400:
        relative = f"{delta_seconds // 3600} hours ago"
    elif delta_seconds < 86400 * 45:
        relative = f"{delta_seconds // 86400} days ago"
    elif delta_seconds < 86400 * 365:
        relative = f"{delta_seconds // (86400 * 30)} months ago"
    else:
        relative = f"{delta_seconds // (86400 * 365)} years ago"

    return f"{pubdate or published_at.strftime('%Y-%m-%d %H:%M:%S')} ({relative})"


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
    publish_age = _format_publish_age(metadata, now=now)
    body = _demote_top_level_headings(summary.strip())

    parts = [
        f"# {title}",
        "",
        "## Key Information",
        "",
        f"- Creator: {author}",
        f"- Published: {publish_age}",
    ]
    if body:
        parts.extend(["", body])
    return "\n".join(parts).rstrip() + "\n"


def summarize(
    md_path: Path | str,
    config: SummarizeConfig,
    summary_presets: SummaryPresetsConfig,
    summary_context_config=None,
    preset: str | None = None,
    profile: str | None = None,
    prompt_template_override: str | None = None,
    metadata: VideoMetadata | None = None,
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

    preset_name = resolve_summary_preset_name(
        summarize=config,
        summary_presets=summary_presets,
        override=preset,
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
