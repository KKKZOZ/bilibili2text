"""Author-specific summary context resolution and prompt rendering."""

from __future__ import annotations

from dataclasses import dataclass

from b2t.config import SummaryContextAuthor, SummaryContextConfig, SummaryContextStock
from b2t.download.metadata import VideoMetadata


@dataclass(frozen=True)
class ResolvedSummaryContext:
    author: SummaryContextAuthor
    stocks: tuple[SummaryContextStock, ...]
    alias_map: dict[str, str]
    theme_terms: tuple[str, ...]
    matched_by: str


def _normalize_text(value: str) -> str:
    return value.strip().casefold()


def resolve_author_summary_context(
    context_config: SummaryContextConfig | None,
    metadata: VideoMetadata | None,
) -> ResolvedSummaryContext | None:
    if context_config is None or metadata is None:
        return None

    author_name = (metadata.author or "").strip()
    normalized_author_name = _normalize_text(author_name)
    author_uid = int(getattr(metadata, "author_uid", 0) or 0)

    for author in context_config.authors:
        if author_uid > 0 and author_uid in author.match_author_uids:
            return _build_resolved_summary_context(
                context_config=context_config,
                author=author,
                matched_by=f"author_uid={author_uid}",
            )

        if normalized_author_name and any(
            _normalize_text(candidate) == normalized_author_name
            for candidate in author.match_author_names
        ):
            return _build_resolved_summary_context(
                context_config=context_config,
                author=author,
                matched_by=f"author={author_name}",
            )

    return None


def _build_resolved_summary_context(
    *,
    context_config: SummaryContextConfig,
    author: SummaryContextAuthor,
    matched_by: str,
) -> ResolvedSummaryContext:
    stocks = tuple(context_config.stocks[name] for name in author.portfolio_stocks)

    alias_map: dict[str, str] = {}
    for stock in stocks:
        for alias in stock.common_aliases:
            alias_map.setdefault(alias, stock.name)
        for name_variant in stock.common_misrecognitions:
            alias_map.setdefault(name_variant, stock.name)
    for alias, target_name in author.alias_overrides.items():
        alias_map[alias] = target_name

    return ResolvedSummaryContext(
        author=author,
        stocks=stocks,
        alias_map=alias_map,
        theme_terms=author.theme_terms,
        matched_by=matched_by,
    )


def render_summary_context_block(context: ResolvedSummaryContext | None) -> str:
    if context is None:
        return ""

    lines = [
        "以下是该 UP 主相关的术语纠错上下文，仅用于纠正转录中的股票名称、简称、黑话和音近错误：",
    ]
    if context.author.prompt_note:
        lines.append(f"- UP 主备注：{context.author.prompt_note}")

    if context.stocks:
        stock_descriptions: list[str] = []
        for stock in context.stocks:
            segments = [stock.name]
            if stock.code:
                segments.append(f"({stock.code})")
            details: list[str] = []
            if stock.sector:
                details.append(stock.sector)
            if stock.description:
                details.append(stock.description)
            if details:
                segments.append(f": {'; '.join(details)}")
            stock_descriptions.append("".join(segments))
        lines.append(f"- 常提标的/股票池：{'；'.join(stock_descriptions)}")

    if context.alias_map:
        alias_items = [f"{alias} -> {target}" for alias, target in context.alias_map.items()]
        lines.append(f"- 常见别名或转录错误：{'；'.join(alias_items)}")

    if context.theme_terms:
        lines.append(
            f"- 常讨论的泛主题词或组合黑话：{'；'.join(context.theme_terms)}"
        )
        lines.append(
            "- 这些词只能作为题材、方向或组合语义的辅助提示，不能直接等同于某一只股票。"
        )

    lines.extend(
        [
            "- 只有当上下文与转录内容高度吻合时，才可以据此纠正名称。",
            "- 不要因为上下文存在就臆造原文未提及的股票、观点、仓位或交易动作。",
            "- 如果仍然不确定，请保留原始称呼，或在无法确认代码时输出 `-`。",
        ]
    )
    return "\n".join(lines).strip()
