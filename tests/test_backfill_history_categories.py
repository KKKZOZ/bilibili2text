from b2t.download.metadata import VideoMetadata
from b2t.history import HistoryDB
from scripts.backfill_history_categories import backfill_missing_categories


def _metadata(bvid: str, tid: int) -> VideoMetadata:
    return VideoMetadata(
        bvid=bvid,
        title="测试视频",
        author="测试UP主",
        author_uid=1,
        pubdate="",
        pubdate_timestamp=0,
        description="",
        tid=tid,
    )


def test_backfill_updates_all_missing_rows_once_per_bvid(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    bvid = "BV1Hdgs6ME67"
    db.record_run(run_id="run-1", bvid=bvid, title="第一条")
    db.record_run(run_id="run-2", bvid=bvid, title="第二条")
    db.record_run(
        run_id="already-filled",
        bvid="BV1AB411c7mD",
        title="已有分区",
        tid=36,
    )
    db.record_run(
        run_id="podcast",
        bvid="xiaoyuzhou_episode-1",
        title="播客",
    )
    requested: list[str] = []

    def fetch_metadata(requested_bvid: str) -> VideoMetadata:
        requested.append(requested_bvid)
        return _metadata(requested_bvid, 207)

    result = backfill_missing_categories(db, metadata_fetcher=fetch_metadata)

    assert requested == [bvid]
    assert result.videos_found == 1
    assert result.videos_updated == 1
    assert result.rows_updated == 2
    assert result.failures == 0
    assert db.get_run_detail("run-1").tid == 207
    assert db.get_run_detail("run-2").tid == 207
    assert db.get_run_detail("already-filled").tid == 36


def test_backfill_dry_run_does_not_update_database(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    bvid = "BV1Hdgs6ME67"
    db.record_run(run_id="run-1", bvid=bvid, title="测试")

    result = backfill_missing_categories(
        db,
        dry_run=True,
        metadata_fetcher=lambda requested_bvid: _metadata(requested_bvid, 207),
    )

    assert result.videos_found == 1
    assert result.videos_updated == 0
    assert result.rows_updated == 0
    assert db.get_run_detail("run-1").tid == 0


def test_record_run_without_tid_preserves_existing_partition(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(run_id="run-1", bvid="BV1Hdgs6ME67", title="初始", tid=207)

    db.record_run(run_id="run-1", bvid="BV1Hdgs6ME67", title="更新后")

    detail = db.get_run_detail("run-1")
    assert detail is not None
    assert detail.title == "更新后"
    assert detail.tid == 207
