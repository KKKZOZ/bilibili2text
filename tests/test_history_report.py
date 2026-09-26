import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend import services
from backend.routes import report
from backend.schemas import HistoryReportRequest
from backend.task_queue import TaskQueueFull

from b2t.config import create_app_config
from b2t.history import HistoryArtifact, HistoryDB
from b2t.report.options import ReportOptions
from b2t.storage import StoredArtifact


@pytest.fixture
def history_report(monkeypatch, tmp_path):
    db = HistoryDB(tmp_path)
    db.record_run(
        run_id="test-run",
        bvid="BV1Fz421q7oh",
        title="Transcript only",
        artifacts=[
            HistoryArtifact("markdown", "source.md", "run/source.md", "local"),
            HistoryArtifact("json", "source.json", "run/source.json", "local"),
        ],
    )
    config = create_app_config(
        summarize_provider="deepseek", summarize_api_key="user-key"
    )
    tasks, deleted, calls = [], [], []
    monkeypatch.setattr(report, "get_history_db", lambda: db)
    monkeypatch.setattr(services, "get_history_db", lambda: db)
    monkeypatch.setattr(
        report,
        "get_storage_backend",
        lambda: SimpleNamespace(delete_file=deleted.append),
    )
    monkeypatch.setattr(report, "check_runtime", lambda: None)
    monkeypatch.setattr(report, "submit_report", tasks.append)

    def runtime(**kwargs):
        assert kwargs["user_credentials_only"] is True
        assert kwargs["deepseek_api_key"] == "user-key"
        return config

    monkeypatch.setattr(report, "get_runtime_app_config", runtime)

    def generate(**kwargs):
        calls.append(kwargs)
        return StoredArtifact(
            "report.html",
            "run/report.html",
            "local",
            "summary_fancy_html",
            derived_from="run/source.md",
            summary_profile="default",
        )

    monkeypatch.setattr(report, "generate_stored_report", generate)
    payload = HistoryReportRequest(
        deepseek_api_key="user-key", report_options=ReportOptions(mode="brief")
    )
    return db, tasks, deleted, calls, payload


def test_history_report_without_summary_is_async_and_deduplicated(history_report):
    db, tasks, _, calls, payload = history_report
    response = report.generate_history_report("test-run", payload)
    assert response.fancy_html_status == "running"
    assert not response.has_summary
    assert not calls
    report.generate_history_report("test-run", payload)
    assert len(tasks) == 1
    tasks[0]()
    assert calls[0]["source_artifact"].storage_key == "run/source.md"
    assert calls[0]["json_artifact"].storage_key == "run/source.json"
    assert calls[0]["options"].mode == "brief"
    detail = db.get_run_detail("test-run")
    assert detail.fancy_html_status == "succeeded"
    assert {a.kind for a in detail.artifacts} == {
        "markdown",
        "json",
        "summary_fancy_html",
    }


def test_history_report_failure_is_visible_and_retryable(history_report, monkeypatch):
    db, tasks, _, _, payload = history_report

    def fail(**kwargs):
        raise RuntimeError("Connection error user-key")

    monkeypatch.setattr(report, "generate_stored_report", fail)
    report.generate_history_report("test-run", payload)
    tasks[0]()
    detail = db.get_run_detail("test-run")
    assert detail.fancy_html_status == "failed"
    assert "Connection error" in detail.fancy_html_error
    assert "user-key" not in detail.fancy_html_error
    report.generate_history_report("test-run", payload)
    assert len(tasks) == 2


def test_history_report_full_queue_does_not_leave_running_status(
    history_report, monkeypatch
):
    db, _, _, _, payload = history_report

    def full(fn):
        raise TaskQueueFull()

    monkeypatch.setattr(report, "submit_report", full)
    with pytest.raises(HTTPException) as exc:
        report.generate_history_report("test-run", payload)
    assert exc.value.status_code == 503
    assert db.get_run_detail("test-run").fancy_html_status == "failed"


def test_history_report_does_not_restore_deleted_history(history_report):
    db, tasks, deleted, _, payload = history_report
    report.generate_history_report("test-run", payload)
    db.delete_run("test-run")
    tasks[0]()
    assert db.get_run_detail("test-run") is None
    assert deleted == ["run/report.html"]


def test_history_report_requires_transcript(history_report):
    db, tasks, _, _, payload = history_report
    db.record_run(
        run_id="summary-only",
        bvid="BV1Fz421q7oh",
        title="Missing transcript",
        artifacts=[HistoryArtifact("summary", "summary.md", "summary.md", "local")],
    )
    with pytest.raises(HTTPException) as exc:
        report.generate_history_report("summary-only", payload)
    assert exc.value.status_code == 400
    assert tasks == []
