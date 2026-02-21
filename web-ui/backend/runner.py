"""Background job execution: the ``_run_job`` orchestrator."""

import logging
from datetime import datetime
from threading import get_ident

from b2t.download.yutto_cli import extract_bvid
from b2t.pipeline import run_pipeline

from backend.jobs import _append_job_log, _update_job
from backend.logging_config import (
    JOB_LOG_DATE_FORMAT,
    _JobLogHandler,
    _redact_text,
)
from backend.services import (
    _build_all_download_items,
    _build_success_download_fields,
    _collect_all_artifacts_for_bvid,
    _record_history,
    _run_summary_only_from_existing,
)
from backend.state import _get_app_config, _get_storage_backend

logger = logging.getLogger(__name__)


def _run_job(
    job_id: str,
    *,
    url: str,
    skip_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
) -> None:
    try:
        config = _get_app_config()
        storage_backend = _get_storage_backend()
    except FileNotFoundError as exc:
        error_message = str(exc) or "配置文件或总结 preset 配置文件不存在"
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            stage_label="处理失败",
            progress=0,
            error=error_message,
        )
        _append_job_log(
            job_id,
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(error_message)}",
        )
        return
    except Exception as exc:
        error_message = str(exc) or "初始化配置或存储后端失败"
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            stage_label="处理失败",
            progress=0,
            error=error_message,
        )
        _append_job_log(
            job_id,
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(error_message)}",
        )
        return

    bvid = extract_bvid(url)
    if bvid is not None:
        try:
            existing_results = storage_backend.find_existing_transcription(bvid)
        except Exception as exc:
            logger.warning("查询历史转录结果失败，将继续正常转录: %s", exc)
            existing_results = None

        if existing_results is not None:
            if skip_summary:
                try:
                    success_fields = _build_success_download_fields(existing_results)
                except ValueError:
                    pass
                else:
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
                    _append_job_log(
                        job_id,
                        f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.pipeline: {_redact_text(notice)}",
                    )
                    _record_history(bvid=bvid, results=existing_results)
                    return
            else:
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
                    _update_job(
                        job_id,
                        status="failed",
                        stage="failed",
                        stage_label="处理失败",
                        error=str(exc),
                    )
                    _append_job_log(
                        job_id,
                        f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
                    )
                    return

                combined_results = dict(existing_results)
                combined_results.update(summary_results)
                try:
                    success_fields = _build_success_download_fields(combined_results)
                except ValueError as exc:
                    _update_job(
                        job_id,
                        status="failed",
                        stage="failed",
                        stage_label="处理失败",
                        error=str(exc),
                    )
                    _append_job_log(
                        job_id,
                        f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
                    )
                    return

                all_artifacts = _collect_all_artifacts_for_bvid(
                    storage_backend,
                    bvid,
                    combined_results,
                )
                notice = (
                    f"检测到 {bvid} 已经转录过，已复用历史转录并完成新的总结。"
                )
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
                _append_job_log(
                    job_id,
                    f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.pipeline: {_redact_text(notice)}",
                )
                _record_history(bvid=bvid, results=combined_results)
                return

    log_handler = _JobLogHandler(job_id=job_id, thread_id=get_ident())
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)

    _update_job(
        job_id,
        status="running",
        stage="queued",
        stage_label="开始处理任务",
        progress=5,
    )

    try:
        try:
            results = run_pipeline(
                url,
                config,
                skip_summary=skip_summary,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
                progress_callback=lambda stage, label, progress: _update_job(
                    job_id,
                    status="running",
                    stage=stage,
                    stage_label=label,
                    progress=progress,
                ),
            )
        except Exception as exc:
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error=str(exc),
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
            )
            return

        try:
            success_fields = _build_success_download_fields(results)
        except ValueError as exc:
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error=str(exc),
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
            )
            return

        # 提取元信息
        metadata = results.get("_metadata")
        metadata_fields = {}
        if metadata:
            metadata_fields["author"] = metadata.author
            metadata_fields["pubdate"] = metadata.pubdate
        if bvid:
            metadata_fields["bvid"] = bvid

        try:
            all_artifacts = _collect_all_artifacts_for_bvid(
                storage_backend, bvid, results
            )
            all_downloads = _build_all_download_items(all_artifacts)
        except Exception as exc:
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error=str(exc),
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
            )
            return

        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            stage_label="处理完成",
            progress=100,
            already_transcribed=False,
            notice=None,
            all_downloads=all_downloads,
            error=None,
            **success_fields,
            **metadata_fields,
        )
        if bvid is not None:
            _record_history(bvid=bvid, results=results)
    finally:
        root_logger.removeHandler(log_handler)
        log_handler.close()
