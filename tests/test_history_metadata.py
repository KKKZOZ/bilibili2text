from b2t.history import HistoryArtifact, HistoryDB, build_history_artifacts, record_pipeline_run
from b2t.storage.base import StoredArtifact, classify_artifact_filename


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


def test_build_history_artifacts_marks_fancy_html_as_summary_family() -> None:
    artifacts = build_history_artifacts(
        {
            "summary_fancy_html": StoredArtifact(
                filename="BV1AB411c7mD_demo_summary_fancy.html",
                storage_key="BV1AB411c7mD-11111111/BV1AB411c7mD_demo_summary_fancy.html",
                backend="minio",
            )
        },
        summary_preset="key_points",
        summary_profile="profile_a",
    )

    assert len(artifacts) == 1
    assert artifacts[0].kind == "summary_fancy_html"
    assert artifacts[0].summary_preset == "key_points"
    assert artifacts[0].summary_profile == "profile_a"


def test_classify_rag_fancy_html_as_summary_family() -> None:
    assert (
        classify_artifact_filename("rag_20260315_120000_foo_bar_fancy.html")
        == "summary_fancy_html"
    )


def test_get_run_detail_normalizes_legacy_rag_fancy_html_kind(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="rag-run-1",
        bvid="",
        title="测试问题",
        created_at="2026-03-15T00:00:00+00:00",
        record_type="rag_query",
        artifacts=[
            HistoryArtifact(
                kind="rag_answer",
                filename="rag_20260315_120000_test_question.md",
                storage_key="rag_answers/run-1/rag_20260315_120000_test_question.md",
                backend="minio",
            ),
            HistoryArtifact(
                kind="file",
                filename="rag_20260315_120000_test_question_fancy.html",
                storage_key="rag_answers/run-1/rag_20260315_120000_test_question_fancy.html",
                backend="minio",
            ),
        ],
    )

    detail = db.get_run_detail("rag-run-1")

    assert detail is not None
    assert [artifact.kind for artifact in detail.artifacts] == [
        "rag_answer",
        "summary_fancy_html",
    ]


def test_record_run_preserves_rag_query_type_when_fancy_html_removed(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    run_id = "rag-run-delete-fancy"
    db.record_run(
        run_id=run_id,
        bvid="",
        title="测试问题",
        created_at="2026-03-16T00:00:00+00:00",
        record_type="rag_query",
        has_summary=True,
        artifacts=[
            HistoryArtifact(
                kind="rag_answer",
                filename="rag_20260316_120000_test_question.md",
                storage_key="rag_answers/run-2/rag_20260316_120000_test_question.md",
                backend="minio",
            ),
            HistoryArtifact(
                kind="summary_fancy_html",
                filename="rag_20260316_120000_test_question_fancy.html",
                storage_key="rag_answers/run-2/rag_20260316_120000_test_question_fancy.html",
                backend="minio",
            ),
        ],
    )

    detail = db.get_run_detail(run_id)
    assert detail is not None

    remained_artifacts = [artifact for artifact in detail.artifacts if artifact.kind != "summary_fancy_html"]
    db.record_run(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=False,
        artifacts=remained_artifacts,
        record_type=detail.record_type,
    )

    updated = db.get_run_detail(run_id)
    assert updated is not None
    assert updated.record_type == "rag_query"
    assert [artifact.kind for artifact in updated.artifacts] == ["rag_answer"]


def test_update_run_fancy_html_status_persists_for_rag_query(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    run_id = "rag-run-fancy-status"
    db.record_run(
        run_id=run_id,
        bvid="",
        title="测试问题",
        created_at="2026-03-16T00:00:00+00:00",
        record_type="rag_query",
        artifacts=[],
    )

    db.update_run_fancy_html_status(
        run_id,
        status="running",
        error="",
    )
    running = db.get_run_detail(run_id)
    assert running is not None
    assert running.fancy_html_status == "running"
    assert running.fancy_html_error == ""

    db.update_run_fancy_html_status(
        run_id,
        status="failed",
        error="生成失败",
    )
    failed = db.get_run_detail(run_id)
    assert failed is not None
    assert failed.fancy_html_status == "failed"
    assert failed.fancy_html_error == "生成失败"
