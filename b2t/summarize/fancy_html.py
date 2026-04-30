"""Generate a styled summary HTML page from summary Markdown via LLM."""

from __future__ import annotations

import html
from html.parser import HTMLParser
import logging
from pathlib import Path
import re

from b2t.config import AppConfig, resolve_summarize_api_base, resolve_summarize_model_profile
from b2t.summarize.litellm_client import collect_stream_result, stream_summary_completion

logger = logging.getLogger(__name__)

_HTML_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)

_ALLOWED_TAGS = {
    "div",
    "section",
    "h1",
    "h2",
    "h3",
    "p",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "blockquote",
    "span",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "br",
}

_ALLOWED_CLASSES = {
    "hero",
    "hero-kicker",
    "hero-title",
    "hero-dek",
    "section",
    "section-title",
    "section-body",
    "lead",
    "callout",
    "callout-title",
    "callout-body",
    "callout-insight",
    "callout-warning",
    "callout-neutral",
    "cards",
    "card",
    "card-title",
    "card-body",
    "quote",
    "quote-source",
    "table-wrap",
    "eyebrow",
}

_DROP_CONTENT_TAGS = {"script", "style", "iframe", "object", "embed"}

FANCY_HTML_PROMPT = """Please rewrite the following summary Markdown as a "restricted HTML fragment" to be injected into a fixed template for display as a well-formatted article page.

=== Hard Rules ===
1. Only output an HTML fragment. Do NOT include ```, <!doctype>, <html>, <head>, <body>, <script>, or <style>.
2. Only use these tags:
   div, section, h1, h2, h3, p, ul, ol, li, strong, em, blockquote, span,
   table, thead, tbody, tr, th, td, hr, br
3. Only use these classes (all others are invalid and will be filtered):
   hero, hero-kicker, hero-title, hero-dek,
   section, section-title, section-body,
   lead, eyebrow,
   callout, callout-title, callout-body, callout-insight, callout-warning, callout-neutral,
   cards, card, card-title, card-body,
   quote, quote-source,
   table-wrap
4. Do NOT use inline styles, event attributes, external resources, or custom attributes.
5. Do NOT fabricate facts. Do NOT introduce information not present in the Markdown.

=== Component Specification ===

[hero] - Must have exactly one, placed at the very top
Structure:
  <div class="hero">
    <span class="hero-kicker">Theme tag (e.g. "Technical Analysis - AI Model")</span>
    <h1 class="hero-title">Core conclusion or main title (extracted from the source)</h1>
    <p class="hero-dek">1-2 sentence introduction summarizing the article's key points</p>
  </div>

[section] - Main content container. Each Markdown H1/H2 heading corresponds to one section.
Structure:
  <section class="section">
    <h2 class="section-title">Title</h2>
    <div class="section-body">
      <p>Body paragraph...</p>
    </div>
  </section>

[callout] - Used for "core conclusions / risk alerts / action items / key reminders". At least 1 per document.
- callout-insight: Technical insight, core conclusion (blue left border)
- callout-warning: Risk reminder, caution (orange left border)
- callout-neutral: Supplementary info, background (gray left border)
Structure:
  <div class="callout callout-insight">
    <p class="callout-title">Title (short, optional)</p>
    <div class="callout-body"><p>Content...</p></div>
  </div>

[cards] - Only for 2-4 short parallel items (e.g., comparisons, category lists)
- Text within a single card must be very short, no more than 3 lines
- Use at most 1-2 cards containers per document
Structure:
  <div class="cards">
    <div class="card"><p class="card-title">Title</p><div class="card-body"><p>Brief description</p></div></div>
    ...
  </div>

[quote] - Only for a single remarkable statement worth highlighting
[table] - Preserve tables from the source; wrap with <div class="table-wrap">

=== Layout Principles ===
- Paragraph-first: Continuous analysis, reasoning, and plans must use section + p, not be forced into cards
- Lists: ul/ol for 4+ parallel short items; use sentence descriptions for 3 or fewer
- Ordered list ol for sequential or step-by-step content; unordered list ul for non-sequential parallel items
- No global cardification: Most sections should NOT be cards. At least 2+ sections should be paragraph-based.
- Overall style: Professional article feel, well-structured, not like a card dashboard

Summary Markdown follows:

{content}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #F1F5F9;
      --paper: #FFFFFF;
      --ink: #111827;
      --ink-soft: #6B7280;
      --ink-muted: #9CA3AF;
      --line: #E5E7EB;
      --accent: #F97316;
      --accent-soft: rgba(249, 115, 22, 0.09);
      --blue: #3B82F6;
      --blue-soft: rgba(59, 130, 246, 0.07);
      --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 8px 28px rgba(0,0,0,0.07);
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      margin: 0;
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", sans-serif;
      font-size: 15.5px;
      line-height: 1.8;
      color: var(--ink);
      background: var(--bg);
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }}
    .page {{
      max-width: 1120px;
      margin: 0 auto;
      padding: clamp(14px, 3vw, 40px) clamp(12px, 2.5vw, 24px) clamp(24px, 5vw, 60px);
    }}
    .frame {{
      background: var(--paper);
      border-radius: 18px;
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      padding: clamp(18px, 4vw, 40px) clamp(16px, 4.5vw, 44px) clamp(24px, 5vw, 48px);
      overflow: hidden;
    }}
    .content {{
      counter-reset: section-counter;
      overflow-wrap: anywhere;
    }}
    /* ── Hero ─────────────────────────────── */
    .hero {{
      padding-bottom: clamp(20px, 3vw, 32px);
      border-bottom: 1.5px solid var(--line);
      margin-bottom: 4px;
    }}
    .hero-kicker, .eyebrow {{
      display: inline-block;
      margin-bottom: 10px;
      color: var(--accent);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.13em;
      text-transform: uppercase;
    }}
    .hero-title {{
      font-size: clamp(26px, 3.8vw, 40px);
      font-weight: 800;
      line-height: 1.2;
      letter-spacing: -0.025em;
      color: var(--ink);
    }}
    .hero-dek, .lead {{
      margin-top: 12px;
      font-size: clamp(15px, 2.6vw, 16px);
      line-height: 1.75;
      color: var(--ink-soft);
      max-width: 72ch;
    }}
    /* ── Section ──────────────────────────── */
    .section {{
      padding: clamp(18px, 3vw, 28px) 0;
      border-bottom: 1px solid var(--line);
    }}
    .section:last-child {{
      border-bottom: none;
      padding-bottom: 0;
    }}
    .section-title {{
      counter-increment: section-counter;
      font-size: 18.5px;
      font-weight: 700;
      line-height: 1.35;
      color: var(--ink);
      margin-bottom: 16px;
      display: flex;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .section-title::before {{
      content: counter(section-counter, decimal-leading-zero);
      flex-shrink: 0;
      width: 26px;
      height: 26px;
      min-width: 26px;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      font-size: 10.5px;
      font-weight: 700;
      line-height: 26px;
      text-align: center;
      margin-top: 2px;
    }}
    .section-body > *:first-child {{ margin-top: 0 !important; }}
    .section-body > *:last-child {{ margin-bottom: 0 !important; }}
    /* ── Prose ────────────────────────────── */
    p {{
      margin-bottom: 14px;
      color: var(--ink);
    }}
    p:last-child {{ margin-bottom: 0; }}
    strong {{ font-weight: 700; }}
    em {{ font-style: italic; color: var(--ink-soft); }}
    /* ── Lists ────────────────────────────── */
    ul, ol {{
      margin-bottom: 14px;
      padding-left: 0;
      list-style: none;
    }}
    ul:last-child, ol:last-child {{ margin-bottom: 0; }}
    ul > li, ol > li {{
      padding-left: 22px;
      position: relative;
      margin-bottom: 7px;
      color: var(--ink);
    }}
    ul > li::before {{
      content: "";
      position: absolute;
      left: 3px;
      top: 9px;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
    }}
    ol {{
      counter-reset: ol-counter;
    }}
    ol > li {{
      counter-increment: ol-counter;
      padding-left: 26px;
    }}
    ol > li::before {{
      content: counter(ol-counter);
      position: absolute;
      left: 0;
      top: 3px;
      width: 17px;
      height: 17px;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      font-size: 10px;
      font-weight: 700;
      text-align: center;
      line-height: 17px;
    }}
    /* ── Callout ──────────────────────────── */
    .callout {{
      padding: clamp(12px, 2.8vw, 16px) clamp(14px, 3vw, 18px);
      border-radius: 10px;
      border-left: 3px solid var(--line);
      background: #F9FAFB;
      margin-bottom: 14px;
    }}
    .callout:last-child {{ margin-bottom: 0; }}
    .callout-insight {{
      border-left-color: var(--blue);
      background: var(--blue-soft);
    }}
    .callout-warning {{
      border-left-color: var(--accent);
      background: var(--accent-soft);
    }}
    .callout-neutral {{
      border-left-color: var(--ink-muted);
      background: #F9FAFB;
    }}
    .callout-title {{
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: 0.01em;
      margin-bottom: 6px;
    }}
    .callout-body > *:first-child {{ margin-top: 0 !important; }}
    .callout-body > *:last-child {{ margin-bottom: 0 !important; }}
    /* ── Cards ────────────────────────────── */
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .cards:last-child {{ margin-bottom: 0; }}
    .card {{
      padding: clamp(14px, 3vw, 18px);
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--paper);
    }}
    .card-title {{
      font-size: clamp(15px, 2.4vw, 17px);
      font-weight: 800;
      line-height: 1.35;
      letter-spacing: -0.015em;
      color: #0F172A;
      margin-bottom: 8px;
    }}
    .card-body {{
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.7;
    }}
    .card-body > *:first-child {{ margin-top: 0 !important; }}
    .card-body > *:last-child {{ margin-bottom: 0 !important; }}
    /* ── Quote ────────────────────────────── */
    .quote {{
      padding: 14px 20px;
      border-left: 3px solid var(--accent);
      background: var(--accent-soft);
      border-radius: 0 6px 6px 0;
      font-size: 16px;
      line-height: 1.7;
      font-style: italic;
      color: var(--ink);
      margin-bottom: 14px;
    }}
    .quote:last-child {{ margin-bottom: 0; }}
    .quote-source {{
      display: block;
      margin-top: 8px;
      font-size: 13px;
      color: var(--ink-soft);
      font-style: normal;
    }}
    /* ── Table ────────────────────────────── */
    .table-wrap {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      border-radius: 12px;
      border: 1px solid var(--line);
      margin-bottom: 14px;
    }}
    .table-wrap:last-child {{ margin-bottom: 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 560px;
    }}
    th, td {{
      padding: 10px 14px;
      font-size: 14px;
      line-height: 1.6;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      font-weight: 700;
      font-size: 12px;
      letter-spacing: 0.04em;
      color: var(--ink-soft);
      background: #F9FAFB;
    }}
    tbody tr:last-child td {{ border-bottom: none; }}
    hr {{
      border: 0;
      border-top: 1px solid var(--line);
      margin: 14px 0;
    }}
    @media (max-width: 860px) {{
      body {{
        font-size: 15px;
      }}
      .frame {{
        border-radius: 14px;
      }}
      .section-title {{
        font-size: 17px;
      }}
      th, td {{
        padding: 9px 12px;
      }}
    }}
    @media (max-width: 680px) {{
      body {{
        font-size: 14.5px;
        line-height: 1.72;
      }}
      .page {{
        padding-top: max(12px, env(safe-area-inset-top));
        padding-right: max(12px, env(safe-area-inset-right));
        padding-bottom: max(24px, env(safe-area-inset-bottom));
        padding-left: max(12px, env(safe-area-inset-left));
      }}
      .frame {{
        padding: 18px 16px 22px;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 4px 18px rgba(0,0,0,0.06);
      }}
      .hero-title {{
        font-size: 24px;
        line-height: 1.22;
      }}
      .hero-kicker, .eyebrow {{
        letter-spacing: 0.1em;
      }}
      .section-title {{
        gap: 8px;
        margin-bottom: 12px;
      }}
      .section-title::before {{
        width: 24px;
        height: 24px;
        min-width: 24px;
        line-height: 24px;
        font-size: 10px;
      }}
      .cards {{
        grid-template-columns: 1fr;
        gap: 10px;
      }}
      .card-title {{
        font-size: 15px;
      }}
      .card-body {{
        font-size: 13.5px;
      }}
      .quote {{
        padding: 12px 14px 12px 16px;
        font-size: 15px;
      }}
      .table-wrap {{
        margin-left: -4px;
        margin-right: -4px;
        border-radius: 10px;
      }}
      table {{
        min-width: 480px;
      }}
      th, td {{
        font-size: 13px;
        padding: 8px 10px;
      }}
    }}
    @media (max-width: 420px) {{
      .hero-title {{
        font-size: 22px;
      }}
      .hero-dek, .lead {{
        font-size: 14px;
      }}
      .section-title {{
        font-size: 16px;
      }}
      ul > li, ol > li {{
        padding-left: 20px;
      }}
      ol > li {{
        padding-left: 24px;
      }}
      .callout {{
        border-radius: 8px;
      }}
      .card-title {{
        font-size: 14.5px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="frame">
      <div class="content">
        {body_html}
      </div>
    </div>
  </main>
</body>
</html>
"""


class _SafeFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.allowed_stack: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in _DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth > 0 or lowered not in _ALLOWED_TAGS:
            return

        rendered_attrs = self._sanitize_attrs(lowered, attrs)
        self.parts.append(f"<{lowered}{rendered_attrs}>")
        if lowered not in {"br", "hr"}:
            self.allowed_stack.append(lowered)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.lower()
        if self.drop_depth > 0 or lowered not in _ALLOWED_TAGS:
            return
        rendered_attrs = self._sanitize_attrs(lowered, attrs)
        self.parts.append(f"<{lowered}{rendered_attrs} />")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _DROP_CONTENT_TAGS:
            if self.drop_depth > 0:
                self.drop_depth -= 1
            return
        if self.drop_depth > 0 or lowered not in _ALLOWED_TAGS:
            return
        if lowered in {"br", "hr"}:
            return
        for index in range(len(self.allowed_stack) - 1, -1, -1):
            candidate = self.allowed_stack[index]
            self.parts.append(f"</{candidate}>")
            self.allowed_stack.pop()
            if candidate == lowered:
                break

    def handle_data(self, data: str) -> None:
        if self.drop_depth > 0:
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if self.drop_depth > 0:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.drop_depth > 0:
            return
        self.parts.append(f"&#{name};")

    def close(self) -> str:
        super().close()
        while self.allowed_stack:
            self.parts.append(f"</{self.allowed_stack.pop()}>")
        return "".join(self.parts)

    @staticmethod
    def _sanitize_attrs(
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> str:
        rendered: list[str] = []
        for key, value in attrs:
            lowered_key = key.lower()
            if lowered_key.startswith("on") or lowered_key == "style":
                continue
            if lowered_key == "class":
                class_names = [
                    item for item in (value or "").split() if item in _ALLOWED_CLASSES
                ]
                if class_names:
                    rendered.append(
                        f' class="{html.escape(" ".join(class_names), quote=True)}"'
                    )
                continue
            if lowered_key in {"colspan", "rowspan"} and tag in {"td", "th"}:
                numeric = (value or "").strip()
                if numeric.isdigit():
                    rendered.append(f' {lowered_key}="{numeric}"')
        return "".join(rendered)


def _strip_code_fence(content: str) -> str:
    return _HTML_FENCE_RE.sub("", content).strip()


def sanitize_fragment(raw_fragment: str) -> str:
    parser = _SafeFragmentParser()
    parser.feed(_strip_code_fence(raw_fragment))
    return parser.close().strip()


def _fallback_fragment(summary_markdown: str) -> str:
    paragraphs = [block.strip() for block in summary_markdown.split("\n\n") if block.strip()]
    rendered = "\n".join(
        (
            '<section class="section"><div class="section-body"><p>'
            + "<br />".join(html.escape(line) for line in item.splitlines() if line.strip())
            + "</p></div></section>"
        )
        for item in paragraphs[:12]
    )
    return rendered or (
        '<section class="section"><div class="section-body">'
        "<p>The summary could not generate fancy HTML; falling back to plain text excerpt.</p>"
        "</div></section>"
    )


def _extract_title(summary_markdown: str, fallback_title: str) -> str:
    for line in summary_markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback_title
    return fallback_title


def generate_fancy_summary_html(
    summary_path: Path | str,
    config: AppConfig,
    *,
    profile: str | None = None,
) -> Path:
    summary_path = Path(summary_path)
    summary_markdown = summary_path.read_text(encoding="utf-8")

    selected_profile = (profile or config.fancy_html.profile).strip()
    model_profile = resolve_summarize_model_profile(
        config.summarize,
        override=selected_profile,
    )
    if not model_profile.api_key:
        raise ValueError(
            f"summarize.profiles.{selected_profile}.api_key is empty, please set it in the config file"
        )

    prompt = FANCY_HTML_PROMPT.format(content=summary_markdown)
    logger.info(
        "Generating fancy HTML from summary (profile: %s, provider: %s, model: %s, api_base: %s)",
        selected_profile,
        model_profile.provider,
        model_profile.model,
        resolve_summarize_api_base(model_profile),
    )
    stream = stream_summary_completion(
        prompt=prompt,
        summarize_config=config.summarize,
        model_profile=model_profile,
        include_usage=True,
    )
    _, fragment = collect_stream_result(stream)
    safe_fragment = sanitize_fragment(fragment)
    if not safe_fragment:
        logger.warning("LLM did not return a valid fancy HTML fragment, falling back to plain text layout")
        safe_fragment = _fallback_fragment(summary_markdown)

    title = _extract_title(summary_markdown, fallback_title=summary_path.stem)
    full_html = HTML_TEMPLATE.format(
        title=html.escape(title, quote=True),
        body_html=safe_fragment,
    )
    output_path = summary_path.with_name(f"{summary_path.stem}_fancy.html")
    output_path.write_text(full_html, encoding="utf-8")
    logger.info("Fancy HTML saved to: %s", output_path)
    return output_path
