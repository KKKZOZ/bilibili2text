import sys
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import history
from backend.routes.history import _resolve_regenerate_summary_preset
from backend.schemas import HistoryRegenerateSummaryRequest

from b2t.history import HistoryArtifact, HistoryDB
from b2t.storage import StoredArtifact
from tests.test_summary_selection import _config


def test_regenerate_custom_summary_preset_keeps_custom_identity() -> None:
    resolved = _resolve_regenerate_summary_preset(
        config=_config(),
        summary_preset="__user_custom__",
        summary_prompt_template="Custom summary: {content}",
    )

    assert resolved == "__user_custom__"


def test_regenerate_custom_summary_preset_requires_template() -> None:
    try:
        _resolve_regenerate_summary_preset(
            config=_config(),
            summary_preset="__user_custom__",
            summary_prompt_template=None,
        )
    except ValueError as exc:
        assert "用户自定义总结模板不能为空" in str(exc)
    else:
        raise AssertionError("expected custom preset without template to fail")


def _seed_history(db: HistoryDB) -> None:
    db.record_run(
        run_id="BV1AB411c7mD-source",
        bvid="BV1AB411c7mD",
        title="测试视频",
        author="测试作者",
        pubdate="2026-07-30 12:00:00",
        created_at="2026-07-30T04:00:00+00:00",
        has_summary=True,
        artifacts=[
            HistoryArtifact(
                kind="markdown",
                filename="BV1AB411c7mD_demo.md",
                storage_key="source/BV1AB411c7mD_demo.md",
                backend="minio",
            ),
            HistoryArtifact(
                kind="summary",
                filename="BV1AB411c7mD_demo_summary.md",
                storage_key="old/BV1AB411c7mD_demo_summary.md",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-6-plus",
            ),
            HistoryArtifact(
                kind="summary_table_md",
                filename="BV1AB411c7mD_demo_summary_table.md",
                storage_key="old/BV1AB411c7mD_demo_summary_table.md",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-6-plus",
            ),
            HistoryArtifact(
                kind="summary_png",
                filename="BV1AB411c7mD_demo_summary.png",
                storage_key="old/BV1AB411c7mD_demo_summary.png",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-6-plus",
            ),
            HistoryArtifact(
                kind="summary_timeline",
                filename="BV1AB411c7mD_demo_summary_timeline.txt",
                storage_key="old/BV1AB411c7mD_demo_summary_timeline.txt",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-6-plus",
            ),
            HistoryArtifact(
                kind="summary",
                filename="BV1AB411c7mD_demo_summary.md",
                storage_key="other/BV1AB411c7mD_demo_summary.md",
                backend="minio",
                summary_preset="other-preset",
                summary_profile="qwen3-6-plus",
            ),
        ],
    )


def _regenerate_request(*, overwrite_existing: bool) -> HistoryRegenerateSummaryRequest:
    return HistoryRegenerateSummaryRequest(
        summary_preset="financial_timeline_merge",
        summary_profile="qwen3-6-plus",
        overwrite_existing=overwrite_existing,
    )


def test_regenerate_same_config_requires_explicit_overwrite_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path)
    _seed_history(db)
    generated = False

    monkeypatch.setattr(history, "get_history_db", lambda: db)
    monkeypatch.setattr(history, "get_runtime_app_config", lambda **kwargs: _config())
    monkeypatch.setattr(history, "get_storage_backend", lambda: object())

    def fake_generate(**kwargs):
        nonlocal generated
        generated = True
        return {}

    monkeypatch.setattr(history, "_run_summary_only_from_existing", fake_generate)

    try:
        history.regenerate_history_summary(
            "BV1AB411c7mD-source",
            _regenerate_request(overwrite_existing=False),
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "覆盖前需要用户确认" in str(exc.detail)
    else:
        raise AssertionError(
            "expected duplicate summary regeneration to require confirmation"
        )

    assert generated is False


def test_regenerate_same_config_replaces_only_matching_summary_family(
    tmp_path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path)
    _seed_history(db)
    deleted_storage_keys: list[str] = []

    class FakeStorage:
        def delete_file(self, storage_key: str) -> None:
            deleted_storage_keys.append(storage_key)

    monkeypatch.setattr(history, "get_history_db", lambda: db)
    monkeypatch.setattr(history, "get_runtime_app_config", lambda **kwargs: _config())
    monkeypatch.setattr(history, "get_storage_backend", FakeStorage)
    monkeypatch.setattr(
        history,
        "_run_summary_only_from_existing",
        lambda **kwargs: {
            "summary": StoredArtifact(
                filename="BV1AB411c7mD_demo_summary.md",
                storage_key="new/BV1AB411c7mD_demo_summary.md",
                backend="minio",
            ),
            "summary_timeline": StoredArtifact(
                filename="BV1AB411c7mD_demo_summary_timeline.txt",
                storage_key="new/BV1AB411c7mD_demo_summary_timeline.txt",
                backend="minio",
            ),
        },
    )

    history.regenerate_history_summary(
        "BV1AB411c7mD-source",
        _regenerate_request(overwrite_existing=True),
    )

    detail = db.get_run_detail("BV1AB411c7mD-source")
    assert detail is not None
    task = detail.summary_regenerations[0]
    assert task.summary_preset == "financial_timeline_merge"
    assert task.summary_profile == "qwen3-6-plus"
    assert task.status == "succeeded"
    assert task.error == ""
    stored_keys = {artifact.storage_key for artifact in detail.artifacts}
    assert "source/BV1AB411c7mD_demo.md" in stored_keys
    assert "other/BV1AB411c7mD_demo_summary.md" in stored_keys
    assert "new/BV1AB411c7mD_demo_summary.md" in stored_keys
    assert "new/BV1AB411c7mD_demo_summary_timeline.txt" in stored_keys
    assert not any(storage_key.startswith("old/") for storage_key in stored_keys)
    assert set(deleted_storage_keys) == {
        "old/BV1AB411c7mD_demo_summary.md",
        "old/BV1AB411c7mD_demo_summary_table.md",
        "old/BV1AB411c7mD_demo_summary.png",
        "old/BV1AB411c7mD_demo_summary_timeline.txt",
    }


def test_regenerate_failure_persists_failed_status(tmp_path, monkeypatch) -> None:
    db = HistoryDB(tmp_path)
    _seed_history(db)

    monkeypatch.setattr(history, "get_history_db", lambda: db)
    monkeypatch.setattr(history, "get_runtime_app_config", lambda **kwargs: _config())
    monkeypatch.setattr(history, "get_storage_backend", lambda: object())

    def fail_generate(**kwargs):
        running = db.get_run_detail("BV1AB411c7mD-source")
        assert running is not None
        assert running.summary_regenerations[0].status == "running"
        raise RuntimeError("模型服务不可用")

    monkeypatch.setattr(history, "_run_summary_only_from_existing", fail_generate)

    try:
        history.regenerate_history_summary(
            "BV1AB411c7mD-source",
            _regenerate_request(overwrite_existing=True),
        )
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "模型服务不可用"
    else:
        raise AssertionError("expected summary regeneration to fail")

    failed = db.get_run_detail("BV1AB411c7mD-source")
    assert failed is not None
    assert failed.summary_regenerations[0].status == "failed"
    assert failed.summary_regenerations[0].error == "模型服务不可用"


def test_regenerate_same_config_rejects_concurrent_request(
    tmp_path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path)
    _seed_history(db)
    assert db.try_start_summary_regeneration(
        "BV1AB411c7mD-source",
        summary_preset="financial_timeline_merge",
        summary_profile="qwen3-6-plus",
    )
    generated = False

    monkeypatch.setattr(history, "get_history_db", lambda: db)
    monkeypatch.setattr(history, "get_runtime_app_config", lambda **kwargs: _config())
    monkeypatch.setattr(history, "get_storage_backend", lambda: object())

    def fake_generate(**kwargs):
        nonlocal generated
        generated = True
        return {}

    monkeypatch.setattr(history, "_run_summary_only_from_existing", fake_generate)

    try:
        history.regenerate_history_summary(
            "BV1AB411c7mD-source",
            _regenerate_request(overwrite_existing=True),
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "正在生成中" in str(exc.detail)
    else:
        raise AssertionError("expected concurrent regeneration to be rejected")

    assert generated is False


def test_summary_family_prefers_explicit_source_relationships(tmp_path) -> None:
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="relationship-run",
        bvid="BV1AB411c7mD",
        title="relationship",
        has_summary=True,
        artifacts=[
            HistoryArtifact(
                kind="summary",
                filename="summary-one.md",
                storage_key="run/summary-one.md",
                backend="local",
            ),
            HistoryArtifact(
                kind="summary_timeline",
                filename="unrelated-name.txt",
                storage_key="run/chapters.txt",
                backend="local",
                derived_from="run/summary-one.md",
            ),
            HistoryArtifact(
                kind="summary_png",
                filename="summary-one.png",
                storage_key="run/legacy-summary-one.png",
                backend="local",
            ),
            HistoryArtifact(
                kind="summary",
                filename="summary-two.md",
                storage_key="run/summary-two.md",
                backend="local",
            ),
        ],
    )
    detail = db.get_run_detail("relationship-run")
    assert detail is not None
    summary = next(
        item for item in detail.artifacts if item.storage_key == "run/summary-one.md"
    )

    assert history._summary_family_storage_keys(detail, summary) == {
        "run/summary-one.md",
        "run/chapters.txt",
        "run/legacy-summary-one.png",
    }
