"""Asynchronous post-processing after transcription or summary generation."""

import logging
from datetime import datetime

from backend.dependencies import get_history_db, get_rag_store, get_storage_backend
from backend.jobs import _append_job_log, _get_job, _update_job
from backend.logging_config import JOB_LOG_DATE_FORMAT, _redact_text
from backend.services import (
    _artifact_download_item,
    _merge_history_artifact,
    _run_fancy_html_only_from_summary,
)
from backend.task_queue import submit_postprocess

logger = logging.getLogger(__name__)


class PostProcessScheduler:
    """Schedule non-blocking indexing and fancy HTML generation work."""

    def trigger_rag_index(self, run_id: str | None, config) -> None:
        if run_id is None or not config.rag.enabled:
            return

        def _do_index() -> None:
            try:
                from b2t.rag.indexer import index_run  # noqa: PLC0415

                count = index_run(
                    run_id=run_id,
                    history_db=get_history_db(),
                    storage_backend=get_storage_backend(),
                    rag_config=config.rag,
                    store=get_rag_store(),
                    force=True,
                )
                logger.info("RAG 索引完成: run_id=%s, chunks=%d", run_id, count)
            except Exception as exc:
                logger.warning("RAG 索引失败（不影响转录结果）: %s", exc)

        submit_postprocess(_do_index)

    def trigger_fancy_html_generation(
        self,
        *,
        job_id: str,
        bvid: str | None,
        results: dict[str, object],
        config,
        storage_backend,
        run_id: str | None,
        summary_preset: str | None,
        summary_profile: str | None,
    ) -> None:
        summary_artifact = results.get("summary")
        if not (
            hasattr(summary_artifact, "storage_key")
            and hasattr(summary_artifact, "filename")
        ):
            return

        def _do_generate() -> None:
            _update_job(
                job_id,
                fancy_html_status="running",
                fancy_html_error=None,
            )
            try:
                fancy_artifact = _run_fancy_html_only_from_summary(
                    summary_artifact=summary_artifact,
                    storage_backend=storage_backend,
                    config=config,
                    summary_profile=summary_profile,
                )
                if run_id and bvid:
                    _merge_history_artifact(
                        run_id=run_id,
                        bvid=bvid,
                        artifact=fancy_artifact,
                        summary_preset=summary_preset,
                        summary_profile=summary_profile,
                    )

                job = _get_job(job_id) or {}
                existing_downloads = job.get("all_downloads")
                merged_downloads = (
                    list(existing_downloads)
                    if isinstance(existing_downloads, list)
                    else []
                )
                merged_downloads.append(_artifact_download_item(fancy_artifact))
                deduped_downloads: list[dict[str, str]] = []
                seen_urls: set[str] = set()
                for item in merged_downloads:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    if not isinstance(url, str) or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    deduped_downloads.append(item)

                notice = str(job.get("notice") or "").strip()
                suffix = "Fancy HTML 已生成。"
                next_notice = f"{notice} {suffix}".strip() if notice else suffix
                _update_job(
                    job_id,
                    all_downloads=deduped_downloads,
                    fancy_html_status="succeeded",
                    fancy_html_error=None,
                    notice=next_notice,
                )
            except Exception as exc:
                logger.warning("Fancy HTML 生成失败（不影响主流程）: %s", exc)
                _update_job(
                    job_id,
                    fancy_html_status="failed",
                    fancy_html_error=str(exc),
                )
                message = _redact_text(f"Fancy HTML 生成失败: {exc}")
                _append_job_log(
                    job_id,
                    (
                        f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} "
                        f"[WARNING] b2t.pipeline: {message}"
                    ),
                )

        submit_postprocess(_do_generate)


postprocess_scheduler = PostProcessScheduler()
