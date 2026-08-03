import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.job_store import JobCapacityError, JobManager, JobPatch
from backend.task_queue import BoundedTaskQueue, TaskQueueFull


def _create(manager: JobManager) -> str:
    job = manager.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=False,
    )
    return str(job["job_id"])


def test_cancelling_queued_job_cancels_associated_future() -> None:
    manager = JobManager(limit=2)
    job_id = _create(manager)
    future = Future()

    manager.submit(job_id, lambda: None, submitter=lambda *_args, **_kwargs: future)

    cancelled, status = manager.cancel(job_id)

    assert (cancelled, status) == (True, "cancelled")
    assert future.cancelled()
    assert manager.cancellation_token(job_id).is_cancelled()


def test_cancelling_running_job_signals_token_when_future_cannot_cancel() -> None:
    manager = JobManager(limit=2)
    job_id = _create(manager)
    future = Future()
    assert future.set_running_or_notify_cancel()

    manager.submit(job_id, lambda: None, submitter=lambda *_args, **_kwargs: future)

    cancelled, status = manager.cancel(job_id)

    assert (cancelled, status) == (True, "cancelled")
    assert not future.cancelled()
    assert manager.cancellation_token(job_id).is_cancelled()
    future.set_result(None)
    assert manager.get(job_id)["status"] == "cancelled"


def test_cancelled_job_ignores_late_stage_metadata() -> None:
    manager = JobManager(limit=2)
    job_id = _create(manager)

    manager.cancel(job_id)
    manager.patch(
        job_id,
        JobPatch(status="running", stage="summarizing", progress=90),
    )

    job = manager.get(job_id)
    assert job is not None
    assert job["status"] == "cancelled"
    assert job["stage"] == "cancelled"
    assert manager.legacy_jobs[job_id].stage_seen["summarizing"] is False


def test_submission_failure_marks_job_failed_instead_of_leaving_it_queued() -> None:
    manager = JobManager(limit=2)
    job_id = _create(manager)

    submitted = manager.submit(
        job_id,
        lambda: None,
        submitter=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TaskQueueFull("full")
        ),
    )

    assert submitted is None
    job = manager.get(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["stage"] == "failed"
    assert "提交失败" in str(job["error"])


def test_future_exception_marks_active_job_failed() -> None:
    manager = JobManager(limit=2)
    job_id = _create(manager)
    future = Future()

    manager.submit(job_id, lambda: None, submitter=lambda *_args, **_kwargs: future)
    future.set_exception(RuntimeError("unexpected"))

    job = manager.get(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert "unexpected" in str(job["error"])


def test_capacity_evicts_terminal_jobs_but_rejects_when_all_jobs_are_active() -> None:
    manager = JobManager(limit=2)
    first_id = _create(manager)
    second_id = _create(manager)
    manager.patch(first_id, JobPatch(status="running"))
    manager.patch(second_id, JobPatch(status="running"))

    with pytest.raises(JobCapacityError):
        _create(manager)

    manager.patch(first_id, JobPatch(status="succeeded", stage="completed"))
    third_id = _create(manager)

    assert manager.get(first_id) is None
    assert manager.get(second_id) is not None
    assert manager.get(third_id) is not None


def test_concurrent_job_creation_keeps_lifecycle_indexes_consistent() -> None:
    manager = JobManager(limit=100)

    with ThreadPoolExecutor(max_workers=12) as executor:
        job_ids = list(executor.map(lambda _index: _create(manager), range(80)))

    assert len(set(job_ids)) == 80
    assert all(manager.cancellation_token(job_id) is not None for job_id in job_ids)


def test_bounded_task_queue_rejects_submission_when_full() -> None:
    queue = BoundedTaskQueue(max_workers=1, max_queued=0, thread_name_prefix="test")
    release = Event()
    future = queue.submit(release.wait)

    with pytest.raises(TaskQueueFull):
        queue.submit(lambda: None)

    release.set()
    assert future.result(timeout=1) is True
    queue.shutdown()
