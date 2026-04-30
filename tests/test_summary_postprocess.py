from datetime import datetime
from pathlib import Path

from b2t.config import (
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPreset,
    SummaryPresetsConfig,
)
from b2t.download.metadata import VideoMetadata
import b2t.summarize.llm as llm_module


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


def _summary_presets() -> SummaryPresetsConfig:
    return SummaryPresetsConfig(
        default="default",
        presets={
            "default": SummaryPreset(
                prompt_template="{content}",
                label="Default",
            )
        },
        source_path=Path("summary_presets.toml"),
    )


def test_post_process_summary_markdown_injects_metadata_and_demotes_h1() -> None:
    metadata = VideoMetadata(
        bvid="BV1AB411c7mD",
        title="测试视频标题",
        author="测试UP主",
        author_uid=123,
        pubdate="2026-03-01 08:00:00",
        pubdate_timestamp=0,
        description="",
    )

    processed = llm_module.post_process_summary_markdown(
        "# 核心结论\n\n- 要点一\n",
        metadata=metadata,
        fallback_title="兜底标题",
        now=datetime(2026, 3, 31, 12, 0, 0),
    )

    assert processed.startswith("# 测试视频标题\n\n## Key Information\n")
    assert "- Creator: 测试UP主" in processed
    assert "- Published: 2026-03-01 08:00:00 (30 days ago)" in processed
    assert "\n## 核心结论\n" in processed
    assert "\n# 核心结论\n" not in processed


def test_summarize_writes_post_processed_summary(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "BV1AB411c7mD_示例视频_transcription.md"
    markdown_path.write_text("原始转录内容", encoding="utf-8")

    monkeypatch.setattr(
        llm_module,
        "stream_summary_completion",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        llm_module,
        "collect_stream_result",
        lambda stream: ("", "# 总结\n\n这里是总结正文。\n"),
    )
    monkeypatch.setattr(
        llm_module,
        "format_markdown_with_markdownlint",
        lambda path: None,
    )

    summary_path = llm_module.summarize(
        markdown_path,
        _summarize_config(),
        _summary_presets(),
        metadata=VideoMetadata(
            bvid="BV1AB411c7mD",
            title="示例视频",
            author="示例UP主",
            author_uid=456,
            pubdate="2026-03-20 10:00:00",
            pubdate_timestamp=0,
            description="",
        ),
    )

    content = summary_path.read_text(encoding="utf-8")
    assert content.startswith("# 示例视频\n\n## Key Information\n")
    assert "- Creator: 示例UP主" in content
    assert "\n## 总结\n" in content
