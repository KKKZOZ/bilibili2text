from b2t.history import HistoryDB, record_pipeline_run
from b2t.storage.base import StoredArtifact


def _mock_results(
    *,
    markdown_key: str,
    summary_key: str,
) -> dict[str, StoredArtifact]:
    return {
        "markdown": StoredArtifact(
            filename="BV1AB411c7mD_demo_transcription.md",
            storage_key=markdown_key,
            backend="minio",
        ),
        "json": StoredArtifact(
            filename="BV1AB411c7mD_demo_transcription.json",
            storage_key=markdown_key.replace("_transcription.md", "_transcription.json"),
            backend="minio",
        ),
        "summary": StoredArtifact(
            filename="BV1AB411c7mD_demo_summary.md",
            storage_key=summary_key,
            backend="minio",
        ),
    }


def test_record_pipeline_run_persists_summary_metadata(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    results = _mock_results(
        markdown_key=(
            "BV1AB411c7mD-11111111/BV1AB411c7mD_demo_transcription.md"
        ),
        summary_key="BV1AB411c7mD-22222222/BV1AB411c7mD_demo_summary.md",
    )

    run_id = record_pipeline_run(
        db=db,
        bvid="BV1AB411c7mD",
        results=results,
        summary_preset="key_points",
        summary_profile="openrouter_default",
    )

    assert run_id is not None
    detail = db.get_run_detail(run_id)
    assert detail is not None

    summary_artifacts = [a for a in detail.artifacts if a.kind == "summary"]
    assert len(summary_artifacts) == 1
    assert summary_artifacts[0].summary_preset == "key_points"
    assert summary_artifacts[0].summary_profile == "openrouter_default"

    markdown_artifacts = [a for a in detail.artifacts if a.kind == "markdown"]
    assert len(markdown_artifacts) == 1
    assert markdown_artifacts[0].summary_preset == ""
    assert markdown_artifacts[0].summary_profile == ""


def test_record_pipeline_run_merge_keeps_old_and_new_summary(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    bvid = "BV1AB411c7mD"
    markdown_key = "BV1AB411c7mD-11111111/BV1AB411c7mD_demo_transcription.md"

    first = _mock_results(
        markdown_key=markdown_key,
        summary_key="BV1AB411c7mD-22222222/BV1AB411c7mD_demo_summary.md",
    )
    second = _mock_results(
        markdown_key=markdown_key,
        summary_key="BV1AB411c7mD-33333333/BV1AB411c7mD_demo_summary.md",
    )

    run_id = record_pipeline_run(
        db=db,
        bvid=bvid,
        results=first,
        summary_preset="timeline_merge",
        summary_profile="profile_a",
        merge_existing_artifacts=True,
    )
    assert run_id is not None

    run_id_second = record_pipeline_run(
        db=db,
        bvid=bvid,
        results=second,
        summary_preset="financial_blog",
        summary_profile="profile_b",
        merge_existing_artifacts=True,
    )
    assert run_id_second == run_id

    detail = db.get_run_detail(run_id)
    assert detail is not None

    summary_artifacts = [a for a in detail.artifacts if a.kind == "summary"]
    assert len(summary_artifacts) == 2
    metadata_pairs = {
        (artifact.summary_preset, artifact.summary_profile)
        for artifact in summary_artifacts
    }
    assert ("timeline_merge", "profile_a") in metadata_pairs
    assert ("financial_blog", "profile_b") in metadata_pairs


def test_list_runs_supports_search_by_author(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="run-author-hit",
        bvid="BV1AB411c7mD",
        title="一期转录",
        author="测试UP主A",
        created_at="2026-02-21T00:00:00+00:00",
        artifacts=[],
    )
    db.record_run(
        run_id="run-author-miss",
        bvid="BV1CD411c7mD",
        title="二期转录",
        author="另一个UP主",
        created_at="2026-02-20T00:00:00+00:00",
        artifacts=[],
    )

    page = db.list_runs(search="测试UP主A")

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].run_id == "run-author-hit"
