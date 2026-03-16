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

FANCY_HTML_PROMPT = """请将下面的总结 Markdown 改写为一个"受限 HTML fragment"，注入到固定模板中展示为精排文章页面。

═══ 硬性规则 ═══
1. 只输出 HTML fragment，不得包含 ```、<!doctype>、<html>、<head>、<body>、<script>、<style>。
2. 只能使用这些标签：
   div, section, h1, h2, h3, p, ul, ol, li, strong, em, blockquote, span,
   table, thead, tbody, tr, th, td, hr, br
3. 只能使用这些 class（其余全部无效，会被过滤）：
   hero, hero-kicker, hero-title, hero-dek,
   section, section-title, section-body,
   lead, eyebrow,
   callout, callout-title, callout-body, callout-insight, callout-warning, callout-neutral,
   cards, card, card-title, card-body,
   quote, quote-source,
   table-wrap
4. 禁止内联样式、事件属性、外链资源、自定义属性。
5. 不得补造事实，不得引入 Markdown 中没有的信息。

═══ 组件规范 ═══

【hero】—— 必须有且只有一个，置于最顶部
结构：
  <div class="hero">
    <span class="hero-kicker">主题标签（如"技术分析 · AI模型"）</span>
    <h1 class="hero-title">核心结论或主标题（从原文提炼）</h1>
    <p class="hero-dek">1-2 句概括全文要点的导言</p>
  </div>

【section】—— 主要正文容器，每个 Markdown 一级/二级标题对应一个 section
结构：
  <section class="section">
    <h2 class="section-title">标题</h2>
    <div class="section-body">
      <p>正文段落……</p>
    </div>
  </section>

【callout】—— 用于"核心结论 / 风险提示 / 操作要点 / 关键提醒"，每份内容至少 1 个
- callout-insight：技术洞察、核心结论（蓝色左边框）
- callout-warning：风险提醒、注意事项（橙色左边框）
- callout-neutral：补充说明、背景信息（灰色左边框）
结构：
  <div class="callout callout-insight">
    <p class="callout-title">标题（简短，可选）</p>
    <div class="callout-body"><p>内容……</p></div>
  </div>

【cards】—— 只用于 2-4 个并列短项目（如对比项、分类列表）
- 单个 card 内文字要极短，不超过 3 行
- 全文最多出现 1-2 次 cards 容器
结构：
  <div class="cards">
    <div class="card"><p class="card-title">标题</p><div class="card-body"><p>简短说明</p></div></div>
    ...
  </div>

【quote】—— 只用于值得单独突出的一句精彩判断
【table】—— 原文有表格时保留，外层加 <div class="table-wrap">

═══ 排版原则 ═══
- 段落优先：连续分析、推理、计划必须用 section + p，不要强行转成卡片
- 列表使用：ul/ol 适合 4 个以上并列短项；3 个以内用句子描述
- 有序列表 ol 用于有先后顺序或步骤的内容；无序列表 ul 用于无顺序要求的并列项
- 禁止全局卡片化：多数 section 不能是 cards，至少 2 个以上 section 以段落为主
- 整体风格：专业文章感，层次分明，不像卡片看板

总结 Markdown 如下：

{content}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
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
    }}
    .page {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 40px 16px 60px;
    }}
    .frame {{
      background: var(--paper);
      border-radius: 12px;
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      padding: 40px 44px 48px;
    }}
    .content {{
      counter-reset: section-counter;
    }}
    /* ── Hero ─────────────────────────────── */
    .hero {{
      padding-bottom: 32px;
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
      font-size: 16px;
      line-height: 1.75;
      color: var(--ink-soft);
    }}
    /* ── Section ──────────────────────────── */
    .section {{
      padding: 28px 0;
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
      padding: 14px 18px;
      border-radius: 6px;
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
      padding: 16px 18px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--paper);
    }}
    .card-title {{
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 6px;
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
      border-radius: 8px;
      border: 1px solid var(--line);
      margin-bottom: 14px;
    }}
    .table-wrap:last-child {{ margin-bottom: 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
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
    @media (max-width: 680px) {{
      .frame {{
        padding: 24px 20px 28px;
        border-radius: 10px;
      }}
      .hero-title {{ font-size: 24px; }}
      .cards {{ grid-template-columns: 1fr; }}
      .section {{ padding: 20px 0; }}
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
        "<p>该总结未能生成 fancy HTML，已回退为纯文本摘要。</p>"
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
            f"summarize.profiles.{selected_profile}.api_key 为空，请先在配置文件中设置"
        )

    prompt = FANCY_HTML_PROMPT.format(content=summary_markdown)
    logger.info(
        "正在为总结生成 fancy HTML（profile: %s, provider: %s, model: %s, api_base: %s）",
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
        logger.warning("LLM 未返回合法 fancy HTML fragment，回退为纯文本布局")
        safe_fragment = _fallback_fragment(summary_markdown)

    title = _extract_title(summary_markdown, fallback_title=summary_path.stem)
    full_html = HTML_TEMPLATE.format(
        title=html.escape(title, quote=True),
        body_html=safe_fragment,
    )
    output_path = summary_path.with_name(f"{summary_path.stem}_fancy.html")
    output_path.write_text(full_html, encoding="utf-8")
    logger.info("Fancy HTML 已保存到: %s", output_path)
    return output_path
