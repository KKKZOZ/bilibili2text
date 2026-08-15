import asyncio
import sys
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.event_stream import EventBroker, job_channel
from backend.job_store import JobPatch, JobRepository
from backend.routes import history, process


def _create_job(repository: JobRepository) -> str:
    job = repository.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=False,
    )
    return str(job["job_id"])


def test_event_broker_coalesces_cross_thread_notifications() -> None:
    async def scenario() -> None:
        broker = EventBroker()
        subscription = broker.subscribe(["job:one"])

        publisher = Thread(
            target=lambda: (
                broker.publish("job:one"),
                broker.publish("job:one"),
            )
        )
        publisher.start()
        publisher.join()

        assert await asyncio.wait_for(subscription.wait(), timeout=1)
        assert subscription.queue.empty()

        subscription.close()
        broker.publish("job:one")
        await asyncio.sleep(0)
        assert subscription.queue.empty()

    asyncio.run(scenario())


def test_job_repository_notifies_only_effective_changes() -> None:
    changed: list[str] = []
    repository = JobRepository(limit=10, on_change=changed.append)
    job_id = _create_job(repository)

    repository.patch(job_id, JobPatch(status="running", progress=20))
    repository.append_log(job_id, "working")
    repository.cancel(job_id)
    repository.patch(job_id, JobPatch(progress=90))
    repository.append_log(job_id, "ignored")

    assert changed == [job_id, job_id, job_id, job_id]


def test_process_event_stream_sends_terminal_snapshot_and_closes(monkeypatch) -> None:
    repository = JobRepository(limit=10)
    job_id = _create_job(repository)
    repository.patch(
        job_id,
        JobPatch(status="succeeded", stage="completed", progress=100),
    )
    monkeypatch.setattr(process, "_get_job", repository.get)

    async def collect() -> list[str]:
        response = await process.process_events(job_id)
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())

    assert len(chunks) == 1
    assert chunks[0].startswith("event: job\n")
    assert '"status": "succeeded"' in chunks[0]


def test_process_event_stream_pushes_repository_changes(monkeypatch) -> None:
    repository = JobRepository(
        limit=10,
        on_change=lambda job_id: process.event_broker.publish(job_channel(job_id)),
    )
    job_id = _create_job(repository)
    repository.patch(job_id, JobPatch(status="running", progress=20))
    monkeypatch.setattr(process, "_get_job", repository.get)

    async def collect() -> list[str]:
        response = await process.process_events(job_id)
        iterator = response.body_iterator
        initial = await anext(iterator)
        repository.patch(
            job_id,
            JobPatch(status="succeeded", stage="completed", progress=100),
        )
        terminal = await asyncio.wait_for(anext(iterator), timeout=1)
        try:
            await anext(iterator)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("terminal SSE stream did not close")
        return [initial, terminal]

    chunks = asyncio.run(collect())

    assert '"status": "running"' in chunks[0]
    assert '"status": "succeeded"' in chunks[1]


def test_history_event_stream_sends_terminal_snapshot(monkeypatch) -> None:
    detail = SimpleNamespace(
        run_id="rag-query-deadbeef",
        bvid="rag-query",
        title="Question",
        author="RAG",
        pubdate="",
        created_at="2026-08-15T00:00:00+00:00",
        has_summary=True,
        artifacts=[],
        record_type="rag_query",
        fancy_html_status="succeeded",
        fancy_html_error="",
    )
    database = SimpleNamespace(get_run_detail=lambda run_id: detail)
    monkeypatch.setattr(history, "get_history_db", lambda: database)

    async def collect() -> list[str]:
        response = await history.history_events(detail.run_id)
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())

    assert len(chunks) == 1
    assert chunks[0].startswith("event: history\n")
    assert '"fancy_html_status": "succeeded"' in chunks[0]
