import tomllib
from pathlib import Path

import pytest

from b2t.summarize.timeline import (
    export_summary_table_without_video_time,
    export_summary_timeline_text,
    extract_timeline_entries,
    remove_video_time_column,
)

SUMMARY_TABLE = """# 金融总结

| 股票名称 | 股票代码 | 视频时间 | 投资逻辑 |
| --- | --- | --- | --- |
| 海吉亚 | 06078.HK | 01:46<br>02:03 | 医疗服务恢复 |
| 新易盛 | 300502.SZ | **01:08**<br />01:08 | 光模块景气 |
| 威高股份 | 01066.HK | 01:45 | 医疗器械增长 |
"""

GENERAL_TIMELINE_TABLE = """# 通用总结

| 主题 | 视频时间 | 内容摘要 |
| --- | --- | --- |
| 环境配置 | 00:42 | 安装依赖并检查版本 |
| 核心流程 | 03:15<br>08:09 | 介绍主要处理步骤 |
"""

STUDY_TIMELINE_TABLE = """# 学习笔记

| 学习主题 | 视频时间 | 核心知识点 |
| --- | --- | --- |
| 基础概念 | 01:07 | 定义与适用范围 |
| 实践方法 | 05:30 | 操作步骤和注意事项 |
"""


def test_extract_timeline_entries_sorts_and_deduplicates_mentions() -> None:
    entries = extract_timeline_entries(SUMMARY_TABLE)

    assert [
        (entry.timestamp, entry.stock_name, entry.stock_code) for entry in entries
    ] == [
        ("01:08", "新易盛", "300502.SZ"),
        ("01:45", "威高股份", "01066.HK"),
        ("01:46", "海吉亚", "06078.HK"),
        ("02:03", "海吉亚", "06078.HK"),
    ]


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (
            GENERAL_TIMELINE_TABLE,
            [
                ("00:42", "环境配置", "-"),
                ("03:15", "核心流程", "-"),
                ("08:09", "核心流程", "-"),
            ],
        ),
        (
            STUDY_TIMELINE_TABLE,
            [
                ("01:07", "基础概念", "-"),
                ("05:30", "实践方法", "-"),
            ],
        ),
    ],
)
def test_extract_timeline_entries_supports_general_topics(
    table: str,
    expected: list[tuple[str, str, str]],
) -> None:
    entries = extract_timeline_entries(table)

    assert [
        (entry.timestamp, entry.stock_name, entry.stock_code) for entry in entries
    ] == expected


def test_general_presets_request_timestamped_timeline_tables() -> None:
    presets_path = Path(__file__).parents[1] / "summary_presets.toml"
    presets = tomllib.loads(presets_path.read_text(encoding="utf-8"))["presets"]

    for preset_name in ("summary", "study_notes"):
        template = presets[preset_name]["prompt_template"]
        assert "视频时间" in template
        assert "Speaker MM:SS" in template
        assert "<br>" in template


def test_remove_video_time_column_only_changes_exported_table() -> None:
    exported = remove_video_time_column(SUMMARY_TABLE)

    assert "视频时间" not in exported
    assert "01:08" not in exported
    assert "股票名称" in exported
    assert "投资逻辑" in exported
    assert "视频时间" in SUMMARY_TABLE


def test_export_summary_artifacts_separates_table_and_timeline(tmp_path: Path) -> None:
    summary_path = tmp_path / "BV1gm3v67EEf_summary.md"
    summary_path.write_text(SUMMARY_TABLE, encoding="utf-8")

    table_path = export_summary_table_without_video_time(summary_path)
    timeline_path = export_summary_timeline_text(summary_path)

    assert table_path is not None
    assert table_path.name == "BV1gm3v67EEf_summary_table.md"
    assert "视频时间" not in table_path.read_text(encoding="utf-8")
    assert timeline_path is not None
    assert timeline_path.name == "BV1gm3v67EEf_summary_timeline.txt"
    assert timeline_path.read_text(encoding="utf-8") == (
        "01:08 新易盛（300502.SZ）\n"
        "01:45 威高股份（01066.HK）\n"
        "01:46 海吉亚（06078.HK）\n"
        "02:03 海吉亚（06078.HK）\n"
    )
    assert "视频时间" in summary_path.read_text(encoding="utf-8")
