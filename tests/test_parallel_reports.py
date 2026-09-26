"""Regression tests for independent summary/report completion and persistence."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend import postprocess
from backend.job_store import JobManager, JobPatch
from backend.routes.process import _process_response_is_active
from backend.schemas import ProcessStatusResponse

from b2t.config import create_app_config
from b2t.download.subtitle import BilibiliSubtitle
from b2t.pipeline import run_pipeline
from b2t.storage import ArtifactKind, StoredArtifact


@pytest.mark.parametrize("summary_fails", [False, True])
@pytest.mark.parametrize("report_first", [False, True])
def test_report_overlaps_summary_and_preserves_both_results(
    monkeypatch, tmp_path, summary_fails, report_first
):
    manager = JobManager()
    job = manager.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
    )
    job_id = job["job_id"]
    manager.patch(job_id, JobPatch(status="running"))
    summary_started = Event()
    report_started = Event()
    report_finished = Event()
    summary_finished = Event()
    stored = {}

    class Storage:
        # Mimic remote storage: pipeline's temporary local files are removed.
        backend_name = "memory"
        persist_local_outputs = False

        def store_file(self, local_path, *, object_key):
            stored[object_key] = local_path.read_bytes()
            return StoredArtifact(local_path.name, object_key, "memory")

        def delete_file(self, key):
            stored.pop(key, None)

    storage = Storage()
    monkeypatch.setattr(postprocess, "job_manager", manager)
    monkeypatch.setattr(postprocess, "_get_job", manager.get)
    monkeypatch.setattr(
        postprocess,
        "_update_job",
        lambda job_id, **kwargs: manager.patch(job_id, JobPatch(**kwargs)),
    )
    monkeypatch.setattr(postprocess, "_build_success_download_fields", lambda r: {})
    monkeypatch.setattr(
        postprocess,
        "_build_all_download_items",
        lambda artifacts: [{"url": a.storage_key} for a in artifacts],
    )
    monkeypatch.setattr(
        postprocess, "_artifact_download_item", lambda a: {"url": a.storage_key}
    )
    monkeypatch.setattr("b2t.pipeline.get_video_metadata", lambda _: None)
    monkeypatch.setattr(
        "b2t.pipeline.fetch_bilibili_subtitle",
        lambda _: BilibiliSubtitle(text="Original full transcript", items=()),
    )

    def summarize(md_path, *args, **kwargs):
        summary_started.set()
        assert report_started.wait(5), "report must start before summary finishes"
        if report_first:
            assert report_finished.wait(5)
        if summary_fails:
            raise RuntimeError("summary failed")
        path = md_path.with_name("summary.md")
        path.write_text("Summary", encoding="utf-8")
        return path

    def generate(**kwargs):
        report_started.set()
        assert summary_started.wait(5), "summary must start while report is running"
        if not report_first:
            assert summary_finished.wait(5)
        source = kwargs["source_artifact"]
        assert b"Original full transcript" in stored[source.storage_key]
        stored["report.html"] = b"Report"
        return StoredArtifact(
            "report.html", "report.html", "memory", ArtifactKind.SUMMARY_FANCY_HTML
        )

    monkeypatch.setattr("b2t.pipeline.summarize_with_comment_viewpoints", summarize)
    monkeypatch.setattr(postprocess, "generate_stored_report", generate)
    futures = []
    with ThreadPoolExecutor(max_workers=1) as executor:

        def submit(fn):
            def work():
                try:
                    fn()
                finally:
                    report_finished.set()

            futures.append(executor.submit(work))

        monkeypatch.setattr(postprocess, "submit_report", submit)
        scheduler = postprocess.PostProcessScheduler()
        sources = {}

        def ready(results):
            sources.update(results)
            assert "summary" not in results
            scheduler.start_report_from_transcript(
                job_id=job_id,
                bvid=None,
                results=results,
                config=None,
                storage_backend=storage,
                ephemeral_upload=True,
            )

        try:
            results = run_pipeline(
                "BV1ABcsztEcY",
                create_app_config(output_dir=tmp_path),
                storage_backend=storage,
                stt_storage_backend=storage,
                transcript_ready_callback=ready,
            )
        except RuntimeError as exc:
            assert summary_fails
            assert str(exc) == "summary failed"
            manager.patch(job_id, JobPatch(status="failed"))
        else:
            assert not summary_fails
            artifacts = [a for a in results.values() if isinstance(a, StoredArtifact)]
            manager.patch(
                job_id,
                JobPatch(
                    status="succeeded",
                    all_downloads=[{"url": a.storage_key} for a in artifacts],
                    ephemeral_artifacts=[
                        {"storage_key": a.storage_key} for a in artifacts
                    ],
                ),
            )
        finally:
            summary_finished.set()
        for future in futures:
            future.result(timeout=5)

    final = manager.get(job_id)
    assert final["fancy_html_status"] == "succeeded"
    urls = {a["url"] for a in final["all_downloads"]}
    assert {"report.html", sources["markdown"].storage_key} <= urls
    assert "report.html" in {a["storage_key"] for a in final["ephemeral_artifacts"]}
    assert sources["markdown"].storage_key in stored
    if not summary_fails:
        assert results["summary"].storage_key in urls


def test_failed_summary_keeps_queued_report_active_and_cancellable():
    manager = JobManager()
    job = manager.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
    )
    job_id = job["job_id"]
    manager.patch(job_id, JobPatch(report_dispatched=True, status="failed"))
    current = manager.get(job_id)
    assert current["fancy_html_status"] == "pending"
    assert _process_response_is_active(ProcessStatusResponse(**current))
    assert manager.cancel(job_id)[0]
    assert manager.cancellation_token(job_id).is_cancelled()


@pytest.mark.parametrize("cached_summary", [False, True])
def test_cached_transcript_dispatches_report_once_before_summary(
    monkeypatch, cached_summary
):
    from backend import existing_transcriptions as existing

    source = StoredArtifact("source.md", "source.md", "local", ArtifactKind.MARKDOWN)
    sources = {"markdown": source}
    calls = []
    monkeypatch.setattr(existing, "_update_job", lambda *a, **k: None)
    monkeypatch.setattr(existing, "_append_info", lambda *a: None)
    monkeypatch.setattr(
        existing,
        "_resolve_requested_summary_selection",
        lambda **k: ("default", "default"),
    )
    monkeypatch.setattr(
        existing,
        "_find_existing_summary_results_for_selection",
        lambda **k: ("run", sources) if cached_summary else None,
    )
    monkeypatch.setattr(
        existing, "_should_refresh_existing_summary_metadata", lambda **k: False
    )
    monkeypatch.setattr(existing, "_build_success_download_fields", lambda r: {})
    monkeypatch.setattr(existing, "_collect_all_artifacts_for_bvid", lambda *a: [])
    monkeypatch.setattr(existing, "_build_all_download_items", lambda a: [])
    monkeypatch.setattr(existing, "_record_history", lambda **k: "run")
    monkeypatch.setattr(
        existing.postprocess_scheduler, "trigger_rag_index", lambda *a: None
    )
    monkeypatch.setattr(
        existing.postprocess_scheduler,
        "start_report_from_transcript",
        lambda **k: calls.append(k["results"]),
    )

    def summarize(**kwargs):
        assert calls == [sources]
        return {}

    monkeypatch.setattr(existing, "_run_summary_only_from_existing", summarize)
    assert existing.existing_transcription_service._summarize_existing(
        job_id="job",
        bvid="BV1ABcsztEcY",
        transcription_id="BV1ABcsztEcY",
        storage_backend=None,
        config=None,
        existing_results=sources,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=True,
        include_comments=False,
        comment_limit=0,
    )
    assert calls == [sources]
