"""Asynchronous post-processing after transcription or summary generation."""

import logging
from datetime import datetime

from b2t.cancellation import PipelineCancelled
from b2t.config import STOCK_STATUS_MODE_BACKGROUND_HYBRID, get_stock_status_mode
from b2t.report.options import ReportOptions
from b2t.timezone import SHANGHAI_TZ
from backend.dependencies import get_history_db, get_rag_store, get_storage_backend
from backend.ephemeral_uploads import (
    ephemeral_upload_expires_at,
    serialize_ephemeral_artifacts,
)
from backend.job_store import job_manager
from backend.jobs import _append_job_log, _get_job, _update_job
from backend.logging_config import JOB_LOG_DATE_FORMAT, _redact_text
from backend.report_service import generate_stored_report
from backend.services import (
    _artifact_download_item,
    _build_all_download_items,
    _build_success_download_fields,
    _generate_summary_png_exports,
    _merge_history_artifact,
    _record_history,
)
from backend.settings import STOCK_STATUS_MAX_WORKERS
from backend.task_queue import TaskQueueFull, submit_postprocess, submit_report

logger = logging.getLogger(__name__)


class PostProcessScheduler:
    """Schedule non-blocking indexing and fancy HTML generation work."""

    def start_report_from_transcript(
        self,
        *,
        job_id,
        bvid,
        results,
        config,
        storage_backend,
        summary_preset=None,
        summary_profile=None,
        ephemeral_upload=False,
    ) -> None:
        """Publish durable sources, then enqueue the independent report branch."""
        token = job_manager.cancellation_token(job_id)

        def publish_and_start():
            metadata = results.get("_metadata")
            resource_id = bvid or getattr(metadata, "bvid", None)
            run_id = None
            if resource_id and not ephemeral_upload:
                run_id = _record_history(
                    bvid=resource_id, results=results, config=config
                )
            artifacts = [
                item
                for key, item in results.items()
                if not key.startswith("_") and hasattr(item, "storage_key")
            ]
            _update_job(
                job_id,
                report_dispatched=True,
                history_run_id=run_id,
                all_downloads=_build_all_download_items(artifacts),
                is_ephemeral_upload=ephemeral_upload,
                expires_at=ephemeral_upload_expires_at() if ephemeral_upload else None,
                ephemeral_artifacts=serialize_ephemeral_artifacts(artifacts)
                if ephemeral_upload
                else [],
                **_build_success_download_fields(results),
            )
            self.trigger_fancy_html_generation(
                job_id=job_id,
                bvid=resource_id,
                results=dict(results),
                config=config,
                storage_backend=storage_backend,
                run_id=run_id,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
            )

        if token:
            token.run_if_active(publish_and_start)
        else:
            publish_and_start()

    def trigger_stock_status_refresh(
        self,
        *,
        bvid: str | None,
        results: dict[str, object],
        config,
        storage_backend,
    ) -> None:
        if get_stock_status_mode(config) != STOCK_STATUS_MODE_BACKGROUND_HYBRID:
            return
        summary_artifact = results.get("summary")
        if not bvid or not (
            hasattr(summary_artifact, "storage_key")
            and hasattr(summary_artifact, "filename")
        ):
            return

        def _do_refresh() -> None:
            try:
                generated = _generate_summary_png_exports(
                    results=results,
                    storage_backend=storage_backend,
                    config=config,
                    fetch_stock_statuses=True,
                    refresh_stock_statuses=True,
                    prefer_baostock_for_a_shares=True,
                    stock_status_max_workers=STOCK_STATUS_MAX_WORKERS,
                    include_no_table=False,
                )
                if generated:
                    logger.info("股票行情缓存及图片刷新完成: bvid=%s", bvid)
            except Exception as exc:
                logger.warning("股票行情后台刷新失败（不影响下载）: %s", exc)

        submit_postprocess(_do_refresh)

    def trigger_rag_index(self, run_id: str | None, config) -> None:
        if run_id is None or not config.rag.enabled:
            return

        def _do_index() -> None:
            try:
                from b2t.rag.indexer import index_run

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

        try:
            submit_postprocess(_do_index)
        except TaskQueueFull:
            logger.warning("RAG 索引任务队列已满，跳过本次索引: run_id=%s", run_id)

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
        def report_progress(message: str) -> None:
            _append_job_log(
                job_id,
                f"{datetime.now(tz=SHANGHAI_TZ).strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.report.pi: {_redact_text(message)}",
            )

        source_artifact = results.get("markdown")
        if not (
            hasattr(source_artifact, "storage_key")
            and hasattr(source_artifact, "filename")
        ):
            _update_job(
                job_id,
                fancy_html_status="failed",
                fancy_html_error="缺少完整转写，无法生成报告",
            )
            return

        def _do_generate() -> None:
            token = job_manager.cancellation_token(job_id)
            if token and token.is_cancelled():
                return
            _update_job(
                job_id,
                fancy_html_status="running",
                fancy_html_error=None,
            )
            try:
                job_input = _get_job(job_id) or {}
                options = ReportOptions.model_validate(
                    job_input.get("report_options") or {}
                )
                metadata = results.get("_metadata")
                source_metadata = {
                    name: getattr(metadata, name, "") or job_input.get(name, "")
                    for name in ("title", "author", "description")
                }
                source_metadata["url"] = job_input.get("report_source_url", "")
                fancy_artifact = generate_stored_report(
                    source_artifact=source_artifact,
                    json_artifact=results.get("json"),
                    progress_callback=report_progress,
                    options=options,
                    metadata=source_metadata,
                    cancellation_token=token,
                    storage_backend=storage_backend,
                    config=config,
                )
                if token and token.is_cancelled():
                    storage_backend.delete_file(fancy_artifact.storage_key)
                    return

                def _publish() -> None:
                    if run_id and bvid:
                        _merge_history_artifact(
                            run_id=run_id,
                            bvid=bvid,
                            artifact=fancy_artifact,
                            summary_preset=summary_preset,
                            summary_profile=fancy_artifact.summary_profile,
                            fancy_html_status="succeeded",
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
                    suffix = "阅读报告已生成。"
                    next_notice = f"{notice} {suffix}".strip() if notice else suffix
                    ephemeral = {}
                    if job.get("is_ephemeral_upload"):
                        ephemeral["ephemeral_artifacts"] = list(
                            job.get("ephemeral_artifacts") or []
                        ) + serialize_ephemeral_artifacts([fancy_artifact])
                    _update_job(
                        job_id,
                        **ephemeral,
                        all_downloads=deduped_downloads,
                        fancy_html_status="succeeded",
                        fancy_html_error=None,
                        notice=next_notice,
                    )

                if token:
                    try:
                        token.run_if_active(_publish)
                    except PipelineCancelled:
                        storage_backend.delete_file(fancy_artifact.storage_key)
                        raise
                else:
                    _publish()
                report_progress("阅读报告已保存，已加入下载列表")
            except PipelineCancelled:
                return
            except Exception as exc:
                logger.warning("阅读报告生成失败（不影响主流程）: %s", exc)
                _update_job(
                    job_id,
                    fancy_html_status="failed",
                    fancy_html_error=str(exc),
                )
                message = _redact_text(f"阅读报告生成失败: {exc}")
                _append_job_log(
                    job_id,
                    (
                        f"{datetime.now(tz=SHANGHAI_TZ).strftime(JOB_LOG_DATE_FORMAT)} "
                        f"[WARNING] b2t.pipeline: {message}"
                    ),
                )

        report_progress("阅读报告已进入队列，等待 Pi 执行")
        try:
            submit_report(_do_generate)
        except TaskQueueFull:
            message = "阅读报告生成任务队列已满，未能提交。"
            logger.warning(message)
            _update_job(
                job_id,
                fancy_html_status="failed",
                fancy_html_error=message,
            )
            _append_job_log(
                job_id,
                f"{datetime.now(tz=SHANGHAI_TZ).strftime(JOB_LOG_DATE_FORMAT)} [WARNING] b2t.pipeline: {message}",
            )


postprocess_scheduler = PostProcessScheduler()
