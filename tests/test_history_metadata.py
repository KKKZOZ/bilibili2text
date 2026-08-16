import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from b2t.history import (
    HistoryArtifact,
    HistoryDB,
    build_history_artifacts,
    infer_title,
    record_pipeline_run,
)
from b2t.storage.base import ArtifactKind, StoredArtifact, classify_artifact_filename


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
            storage_key=markdown_key.replace(
                "_transcription.md", "_transcription.json"
            ),
            backend="minio",
        ),
        "summary": StoredArtifact(
            filename="BV1AB411c7mD_demo_summary.md",
            storage_key=summary_key,
            backend="minio",
        ),
    }


def test_infer_title_moves_multipart_page_to_uppercase_suffix() -> None:
    title = infer_title(
        "BV1ua4y1Y7yX_p5_[速成零基础高中数学合集]20个视频整理版_transcription.md",
        bvid="BV1ua4y1Y7yX",
    )

    assert title == "[速成零基础高中数学合集]20个视频整理版_P5"


def test_record_pipeline_run_persists_summary_metadata(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    full_title = "这是一个远远超过十五个字符但历史页面仍应完整展示的视频标题"
    results = _mock_results(
        markdown_key=("BV1AB411c7mD-11111111/BV1AB411c7mD_demo_transcription.md"),
        summary_key="BV1AB411c7mD-22222222/BV1AB411c7mD_demo_summary.md",
    )

    run_id = record_pipeline_run(
        db=db,
        bvid="BV1AB411c7mD",
        results=results,
        title=full_title,
        tid=207,
        summary_preset="key_points",
        summary_profile="openrouter_default",
    )

    assert run_id is not None
    detail = db.get_run_detail(run_id)
    assert detail is not None
    assert detail.title == full_title
    assert detail.tid == 207
    assert db.list_runs().items[0].tid == 207

    summary_artifacts = [a for a in detail.artifacts if a.kind == "summary"]
    assert len(summary_artifacts) == 1
    assert summary_artifacts[0].summary_preset == "key_points"
    assert summary_artifacts[0].summary_profile == "openrouter_default"
    assert db.list_runs().items[0].summary_version_count == 1
    markdown_artifacts = [a for a in detail.artifacts if a.kind == "markdown"]
    assert len(markdown_artifacts) == 1
    assert markdown_artifacts[0].summary_preset == ""
    assert markdown_artifacts[0].summary_profile == ""


def test_list_runs_counts_summary_roots_as_versions(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="summary-versions",
        bvid="BV1AB411c7mD",
        title="多版本总结",
        artifacts=[
            HistoryArtifact(
                kind="markdown",
                filename="video_transcription.md",
                storage_key="run/transcription.md",
                backend="local",
            ),
            HistoryArtifact(
                kind="summary",
                filename="video_summary.md",
                storage_key="run/summary-a.md",
                backend="local",
            ),
            HistoryArtifact(
                kind="summary_png",
                filename="video_summary.png",
                storage_key="run/summary-a.png",
                backend="local",
                derived_from="run/summary-a.md",
            ),
            HistoryArtifact(
                kind="summary",
                filename="video_summary.md",
                storage_key="run/summary-b.md",
                backend="local",
            ),
            HistoryArtifact(
                kind="summary_fancy_html",
                filename="video_summary_fancy.html",
                storage_key="run/summary-b.html",
                backend="local",
                derived_from="run/summary-b.md",
            ),
        ],
    )

    item = db.list_runs().items[0]

    assert item.file_count == 5
    assert item.summary_version_count == 2


def test_list_runs_combines_multi_category_and_author_filters(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="finance-target",
        bvid="BV1Hdgs6ME67",
        title="目标财经视频",
        author="目标UP主",
        tid=207,
    )
    db.record_run(
        run_id="finance-other-author",
        bvid="BV1AB411c7mD",
        title="其他财经视频",
        author="其他UP主",
        tid=207,
    )
    db.record_run(
        run_id="daily-target-author",
        bvid="BV1CD411c7mE",
        title="生活视频",
        author="目标UP主",
        tid=21,
    )
    db.record_run(
        run_id="daily-other-selected-author",
        bvid="BV1EF411c7mF",
        title="另一个生活视频",
        author="另一个目标UP主",
        tid=21,
    )

    page = db.list_runs(
        category_tids=(36, 207, 208, 21),
        authors=("目标UP主", "另一个目标UP主"),
    )

    assert {item.run_id for item in page.items} == {
        "finance-target",
        "daily-target-author",
        "daily-other-selected-author",
    }


def test_list_runs_filters_multiple_platforms_and_counts_options(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(run_id="bili", bvid="BV1Hdgs6ME67", title="B站")
    db.record_run(
        run_id="podcast",
        bvid="xiaoyuzhou_0123456789abcdef01234567",
        title="小宇宙",
    )
    db.record_run(run_id="audio", bvid="ximalaya_123456", title="喜马拉雅")
    db.record_run(
        run_id="rag",
        bvid="rag_20260815_120000",
        title="知识库查询",
        record_type="rag_query",
    )

    page = db.list_runs(platforms=("bilibili", "ximalaya", "knowledge_base"))

    assert {item.run_id for item in page.items} == {"bili", "audio", "rag"}
    assert db.list_history_platform_counts() == [
        ("bilibili", 1),
        ("xiaoyuzhou", 1),
        ("ximalaya", 1),
        ("knowledge_base", 1),
    ]


def test_history_artifact_metadata_round_trips_and_links_timeline(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    markdown = StoredArtifact(
        filename="custom-input.md",
        storage_key="run/custom-input.md",
        backend="local",
        kind=ArtifactKind.MARKDOWN,
    )
    summary = StoredArtifact(
        filename="not-a-summary-filename.md",
        storage_key="run/generated.md",
        backend="local",
        kind=ArtifactKind.SUMMARY,
        derived_from=markdown.storage_key,
        summary_preset="key_points",
        summary_profile="profile_a",
    )
    timeline = StoredArtifact(
        filename="chapters.txt",
        storage_key="run/chapters.txt",
        backend="local",
        kind=ArtifactKind.SUMMARY_TIMELINE,
        derived_from=summary.storage_key,
        summary_preset="key_points",
        summary_profile="profile_a",
    )

    db.record_run(
        run_id="metadata-round-trip",
        bvid="BV1AB411c7mD",
        title="metadata",
        has_summary=True,
        artifacts=build_history_artifacts(
            {"markdown": markdown, "summary": summary, "timeline": timeline}
        ),
    )

    detail = db.get_run_detail("metadata-round-trip")
    assert detail is not None
    artifacts = {artifact.storage_key: artifact for artifact in detail.artifacts}
    assert artifacts[timeline.storage_key].kind == ArtifactKind.SUMMARY_TIMELINE
    assert artifacts[timeline.storage_key].derived_from == summary.storage_key
    assert artifacts[timeline.storage_key].summary_preset == "key_points"
    assert artifacts[timeline.storage_key].summary_profile == "profile_a"


def test_history_db_migrates_legacy_artifact_table_and_falls_back_to_filename(
    tmp_path,
) -> None:
    db_path = tmp_path / "b2t_history.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE transcription_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                bvid TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                pubdate TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                has_summary INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE transcription_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                backend TEXT NOT NULL
            );
            INSERT INTO transcription_runs
                (run_id, bvid, title, created_at)
            VALUES ('legacy-run', 'BV1AB411c7mD', 'legacy', '2026-01-01T00:00:00+00:00');
            INSERT INTO transcription_artifacts
                (run_id, kind, filename, storage_key, backend)
            VALUES
                ('legacy-run', 'file', 'legacy_summary_timeline.txt', 'legacy/timeline.txt', 'local');
            """
        )

    db = HistoryDB(tmp_path)
    detail = db.get_run_detail("legacy-run")

    assert detail is not None
    assert detail.artifacts[0].kind == ArtifactKind.SUMMARY_TIMELINE
    with sqlite3.connect(db_path) as conn:
        artifact_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(transcription_artifacts)")
        }
        regeneration_table = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'summary_regenerations'"
        ).fetchone()
    assert {"derived_from", "summary_preset", "summary_profile"} <= artifact_columns
    assert regeneration_table is not None


def test_classify_summary_png_artifacts() -> None:
    assert classify_artifact_filename("BV1AB411c7mD_demo_summary.png") == "summary_png"
    assert (
        classify_artifact_filename("BV1AB411c7mD_demo_summary_no_table.png")
        == "summary_no_table_png"
    )
    assert (
        classify_artifact_filename("BV1AB411c7mD_demo_summary_table.png")
        == "summary_table_png"
    )
    assert (
        classify_artifact_filename("BV1AB411c7mD_demo_summary_timeline.txt")
        == "summary_timeline"
    )


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


def test_record_pipeline_run_merge_preserves_existing_author_and_pubdate(
    tmp_path,
) -> None:
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
        author="测试UP主",
        pubdate="2026-05-01 12:34:56",
        merge_existing_artifacts=True,
    )
    assert run_id is not None

    record_pipeline_run(
        db=db,
        bvid=bvid,
        results=second,
        author="",
        pubdate="",
        summary_preset="financial_blog",
        summary_profile="profile_b",
        merge_existing_artifacts=True,
    )

    detail = db.get_run_detail(run_id)
    assert detail is not None
    assert detail.author == "测试UP主"
    assert detail.pubdate == "2026-05-01 12:34:56"


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

    remained_artifacts = [
        artifact
        for artifact in detail.artifacts
        if artifact.kind != "summary_fancy_html"
    ]
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


def test_update_run_summary_regeneration_status_persists(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    run_id = "summary-regeneration-status"
    db.record_run(
        run_id=run_id,
        bvid="BV1AB411c7mD",
        title="测试视频",
        artifacts=[],
    )

    assert db.try_start_summary_regeneration(
        run_id,
        summary_preset="key_points",
        summary_profile="profile-a",
    )
    running = db.get_run_detail(run_id)
    assert running is not None
    assert len(running.summary_regenerations) == 1
    assert running.summary_regenerations[0].status == "running"
    assert running.summary_regenerations[0].error == ""
    assert not db.try_start_summary_regeneration(
        run_id,
        summary_preset="key_points",
        summary_profile="profile-a",
    )
    assert db.try_start_summary_regeneration(
        run_id,
        summary_preset="timeline",
        summary_profile="profile-a",
    )

    db.update_summary_regeneration_status(
        run_id,
        summary_preset="key_points",
        summary_profile="profile-a",
        status="failed",
        error="总结失败",
    )
    failed = db.get_run_detail(run_id)
    assert failed is not None
    assert failed.summary_regenerations[0].status == "failed"
    assert failed.summary_regenerations[0].error == "总结失败"


def test_summary_regeneration_start_is_atomic_for_same_config(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    run_id = "concurrent-summary-regeneration"
    db.record_run(
        run_id=run_id,
        bvid="BV1AB411c7mD",
        title="测试视频",
        artifacts=[],
    )
    barrier = Barrier(2)

    def start() -> bool:
        barrier.wait()
        return db.try_start_summary_regeneration(
            run_id,
            summary_preset="key_points",
            summary_profile="profile-a",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start(), range(2)))

    assert sorted(results) == [False, True]
