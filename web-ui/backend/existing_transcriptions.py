"""Reuse previously stored transcriptions when a BV has already been processed."""

from datetime import datetime
import logging

from b2t.storage import StorageBackend

from backend.jobs import _append_job_log, _update_job
from backend.logging_config import JOB_LOG_DATE_FORMAT, _redact_text
from backend.postprocess import postprocess_scheduler
from backend.services import (
    _build_all_download_items,
    _build_success_download_fields,
    _collect_all_artifacts_for_bvid,
    _record_history,
    _run_summary_only_from_existing,
)

logger = logging.getLogger(__name__)


class ExistingTranscriptionService:
    def handle_if_existing(
        self,
        *,
        job_id: str,
        bvid: str,
        storage_backend: StorageBackend,
        config,
        skip_summary: bool,
        summary_preset: str | None,
        summary_profile: str | None,
        auto_generate_fancy_html: bool,
    ) -> bool:
        try:
            existing_results = storage_backend.find_existing_transcription(bvid)
        except Exception as exc:
            logger.warning("查询历史转录结果失败，将继续正常转录: %s", exc)
            return False

        if existing_results is None:
            return False

        if skip_summary:
            return self._return_existing_without_summary(
                job_id=job_id,
                bvid=bvid,
                storage_backend=storage_backend,
                config=config,
                existing_results=existing_results,
            )

        return self._summarize_existing(
            job_id=job_id,
            bvid=bvid,
            storage_backend=storage_backend,
            config=config,
            existing_results=existing_results,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            auto_generate_fancy_html=auto_generate_fancy_html,
        )

    def _return_existing_without_summary(
        self,
        *,
        job_id: str,
        bvid: str,
        storage_backend: StorageBackend,
        config,
        existing_results,
    ) -> bool:
        try:
            success_fields = _build_success_download_fields(existing_results)
        except ValueError:
            return False

        all_artifacts = _collect_all_artifacts_for_bvid(
            storage_backend,
            bvid,
            existing_results,
        )
        notice = f"检测到 {bvid} 已经转录过，已直接返回历史文件。"
        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            stage_label="已命中历史转录结果",
            progress=100,
            already_transcribed=True,
            notice=notice,
            all_downloads=_build_all_download_items(all_artifacts),
            error=None,
            **success_fields,
        )
        _append_info(job_id, notice)
        run_id = _record_history(
            bvid=bvid,
            results=existing_results,
            config=config,
        )
        postprocess_scheduler.trigger_rag_index(run_id, config)
        return True

    def _summarize_existing(
        self,
        *,
        job_id: str,
        bvid: str,
        storage_backend: StorageBackend,
        config,
        existing_results,
        summary_preset: str | None,
        summary_profile: str | None,
        auto_generate_fancy_html: bool,
    ) -> bool:
        _update_job(
            job_id,
            status="running",
            stage="summarizing",
            stage_label="命中历史转录，正在重新总结",
            progress=90,
        )
        try:
            summary_results = _run_summary_only_from_existing(
                bvid=bvid,
                storage_backend=storage_backend,
                config=config,
                existing_results=existing_results,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
            )
        except Exception as exc:
            _fail_job(job_id, str(exc))
            return True

        combined_results = dict(existing_results)
        combined_results.update(summary_results)
        try:
            success_fields = _build_success_download_fields(combined_results)
        except ValueError as exc:
            _fail_job(job_id, str(exc))
            return True

        all_artifacts = _collect_all_artifacts_for_bvid(
            storage_backend,
            bvid,
            combined_results,
        )
        notice = f"检测到 {bvid} 已经转录过，已复用历史转录并完成新的总结。"
        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            stage_label="处理完成（复用历史转录）",
            progress=100,
            already_transcribed=True,
            notice=notice,
            all_downloads=_build_all_download_items(all_artifacts),
            error=None,
            **success_fields,
        )
        _append_info(job_id, notice)

        run_id = _record_history(
            bvid=bvid,
            results=combined_results,
            config=config,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
        )
        if auto_generate_fancy_html:
            postprocess_scheduler.trigger_fancy_html_generation(
                job_id=job_id,
                bvid=bvid,
                results=combined_results,
                config=config,
                storage_backend=storage_backend,
                run_id=run_id,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
            )
        else:
            _update_job(job_id, fancy_html_status="idle")
        postprocess_scheduler.trigger_rag_index(run_id, config)
        return True


def _append_info(job_id: str, message: str) -> None:
    _append_job_log(
        job_id,
        (
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} "
            f"[INFO] b2t.pipeline: {_redact_text(message)}"
        ),
    )


def _fail_job(job_id: str, message: str) -> None:
    _update_job(
        job_id,
        status="failed",
        stage="failed",
        stage_label="处理失败",
        error=message,
    )
    _append_job_log(
        job_id,
        (
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} "
            f"[ERROR] b2t.pipeline: {_redact_text(message)}"
        ),
    )


existing_transcription_service = ExistingTranscriptionService()
