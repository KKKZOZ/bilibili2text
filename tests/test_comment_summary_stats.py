from pathlib import Path

import b2t.summarize.llm as llm_module
from b2t.config import SummarizeConfig, SummarizeModelProfile


def _summarize_config() -> SummarizeConfig:
    return SummarizeConfig(
        profile="default",
        profiles={
            "default": SummarizeModelProfile(
                provider="openrouter",
                model="qwen/qwen3-max",
                api_key="dummy-test-key",
                api_base="https://example.com/v1",
                providers=(),
            )
        },
        enable_thinking=False,
        preset="default",
        presets_file="summary_presets.toml",
    )


def test_append_comment_summary_adds_fixed_comment_stats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("# 原总结\n", encoding="utf-8")
    comments_markdown = "\n".join(
        (
            "# B 站 精选评论",
            "",
            "- 已抓取主评论: 2",
            "- 已抓取子评论: 3",
            "- 评论区总数: 353",
            "",
            "## 1. 观众A",
            "评论内容",
            "",
            "子评论：",
            "- **UP主回复** UP主（点赞 9）：**补充观点**",
        )
    )

    monkeypatch.setattr(
        llm_module,
        "stream_summary_completion",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        llm_module,
        "collect_stream_result",
        lambda stream: ("", "## 精选评论观点\n\n- 评论观点"),
    )
    monkeypatch.setattr(
        llm_module,
        "format_markdown_with_markdownlint",
        lambda path: None,
    )

    changed = llm_module.append_comment_summary_to_markdown(
        summary_path,
        comments_markdown,
        _summarize_config(),
    )

    assert changed is True
    output = summary_path.read_text(encoding="utf-8")
    assert "- 视频总评论数: 353" in output
    assert "- 本次总结评论数: 5（主评论 2，子评论 3）" in output
    assert "- UP主回复评论数: 1" in output
    assert "- 评论观点" in output
