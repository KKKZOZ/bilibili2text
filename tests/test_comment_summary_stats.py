from pathlib import Path
from threading import Barrier

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
        lambda stream: (
            "",
            "\n".join(
                (
                    "## 精选评论观点",
                    "",
                    "### 舆情统计",
                    "有效评论：4",
                    "正面：2（50.0%）",
                    "负面：1（25.0%）",
                    "中性：1（25.0%）",
                    "已过滤：1",
                    "",
                    "### 情绪倾向",
                    "评论区整体积极，也有少量不同声音。",
                    "",
                    "### 高频观点",
                    "- 评论观点",
                )
            ),
        ),
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
    assert "- 有效评论数: 4" in output
    assert "- 已过滤评论数: 1" in output
    assert "- 正面评论: 2（50.0%）" in output
    assert "- 负面评论: 1（25.0%）" in output
    assert "- 中性评论: 1（25.0%）" in output
    assert "### 舆情统计" not in output
    assert "- 评论观点" in output
    assert output.index("### 高频观点") < output.index("### 情绪倾向")


def test_transcript_and_comment_summaries_run_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transcript_path = tmp_path / "transcript.md"
    transcript_path.write_text("转录内容", encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    barrier = Barrier(2, timeout=1)

    def fake_summarize(*args, **kwargs):
        assert kwargs["isolated_client"] is True
        barrier.wait()
        summary_path.write_text("# 正文总结\n", encoding="utf-8")
        return summary_path

    def fake_comment_summary(*args, **kwargs):
        assert kwargs["isolated_client"] is True
        barrier.wait()
        return "## 精选评论观点\n\n- 评论观点"

    monkeypatch.setattr(llm_module, "summarize", fake_summarize)
    monkeypatch.setattr(
        llm_module,
        "summarize_comment_viewpoints",
        fake_comment_summary,
    )
    monkeypatch.setattr(
        llm_module,
        "format_markdown_with_markdownlint",
        lambda path: None,
    )

    result = llm_module.summarize_with_comment_viewpoints(
        transcript_path,
        _summarize_config(),
        object(),
        comments_markdown=("- 已抓取主评论: 1\n- 已抓取子评论: 0\n- 评论区总数: 1\n"),
    )

    assert result == summary_path
    output = summary_path.read_text(encoding="utf-8")
    assert "# 正文总结" in output
    assert "## 精选评论观点" in output


def test_comment_summary_failure_keeps_transcript_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transcript_path = tmp_path / "transcript.md"
    transcript_path.write_text("转录内容", encoding="utf-8")
    summary_path = tmp_path / "summary.md"

    def fake_summarize(*args, **kwargs):
        summary_path.write_text("# 正文总结\n", encoding="utf-8")
        return summary_path

    monkeypatch.setattr(llm_module, "summarize", fake_summarize)
    monkeypatch.setattr(
        llm_module,
        "summarize_comment_viewpoints",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("comment failed")),
    )

    result = llm_module.summarize_with_comment_viewpoints(
        transcript_path,
        _summarize_config(),
        object(),
        comments_markdown="评论内容",
    )

    assert result == summary_path
    assert summary_path.read_text(encoding="utf-8") == "# 正文总结\n"
