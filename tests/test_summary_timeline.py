from pathlib import Path

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
