import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.artifacts import summary_artifact_group_ids

from b2t.history import HistoryArtifact


def artifact(
    kind: str,
    storage_key: str,
    *,
    filename: str = "video_summary.md",
    derived_from: str = "",
    preset: str = "default",
    profile: str = "deepseek",
) -> HistoryArtifact:
    return HistoryArtifact(
        kind=kind,
        filename=filename,
        storage_key=storage_key,
        backend="local",
        derived_from=derived_from,
        summary_preset=preset,
        summary_profile=profile,
    )


def test_summary_groups_follow_explicit_relationship_chains() -> None:
    artifacts = [
        artifact("summary", "run/summary.md"),
        artifact(
            "summary_table_png",
            "run/table.png",
            filename="video_summary_table.png",
            derived_from="run/table.md",
        ),
        artifact(
            "summary_table_md",
            "run/table.md",
            filename="video_summary_table.md",
            derived_from="run/summary.md",
        ),
        artifact("markdown", "run/transcription.md", preset="", profile=""),
    ]

    assert summary_artifact_group_ids(artifacts) == {
        "run/summary.md": "summary-1",
        "run/table.png": "summary-1",
        "run/table.md": "summary-1",
    }


def test_summary_groups_separate_same_filenames_by_config() -> None:
    artifacts = [
        artifact("summary", "run/a-summary.md", preset="timeline"),
        artifact(
            "summary_timeline",
            "run/a-timeline.txt",
            filename="video_summary_timeline.txt",
            preset="timeline",
        ),
        artifact("summary", "run/b-summary.md", preset="general", profile="qwen"),
        artifact(
            "summary_timeline",
            "run/b-timeline.txt",
            filename="video_summary_timeline.txt",
            preset="general",
            profile="qwen",
        ),
    ]

    assert summary_artifact_group_ids(artifacts) == {
        "run/a-summary.md": "summary-1",
        "run/a-timeline.txt": "summary-1",
        "run/b-summary.md": "summary-2",
        "run/b-timeline.txt": "summary-2",
    }


def test_legacy_duplicate_summary_groups_use_closest_preceding_root() -> None:
    artifacts = [
        artifact("summary", "run/first-summary.md"),
        artifact(
            "summary_table_md",
            "run/first-table.md",
            filename="video_summary_table.md",
        ),
        artifact("summary", "run/second-summary.md"),
        artifact(
            "summary_table_md",
            "run/second-table.md",
            filename="video_summary_table.md",
        ),
    ]

    assert summary_artifact_group_ids(artifacts) == {
        "run/first-summary.md": "summary-1",
        "run/first-table.md": "summary-1",
        "run/second-summary.md": "summary-2",
        "run/second-table.md": "summary-2",
    }
