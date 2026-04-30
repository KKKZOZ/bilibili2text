"""Background job execution: the ``_run_job`` orchestrator."""

import logging
from pathlib import Path
import shutil
from datetime import datetime
from threading import get_ident

from b2t.download.yutto_cli import extract_bvid
from b2t.pipeline import run_pipeline

from backend.existing_transcriptions import existing_transcription_service
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
)
from backend.dependencies import (
    get_storage_backend,
    get_stt_storage_backend,
)
from backend.postprocess import postprocess_scheduler
from backend.settings import get_runtime_app_config

logger = logging.getLogger(__name__)


def _cleanup_upload_temp_dir(temp_dir: Path | None) -> None:
    if temp_dir is None:
        return
    shutil.rmtree(temp_dir, ignore_errors=True)


def _run_job(
    job_id: str,
    *,
    url: str | None,
    input_audio_path: str | None = None,
    input_bvid: str | None = None,
    skip_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
    auto_generate_fancy_html: bool,
    api_key: str | None = None,
    deepseek_api_key: str | None = None,
) -> None:
    normalized_url = (url or "").strip()
    normalized_audio_path = (input_audio_path or "").strip()
    bvid = (input_bvid or "").strip() or None
    if bvid is None and normalized_url:
        bvid = extract_bvid(normalized_url)

    upload_temp_dir: Path | None = None
    if normalized_audio_path:
        upload_temp_dir = Path(normalized_audio_path).expanduser().resolve().parent

    try:
        config = get_runtime_app_config(require_public_api_key=True, api_key=api_key, deepseek_api_key=deepseek_api_key)
        storage_backend = get_storage_backend()
        stt_storage_backend = get_stt_storage_backend()
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
        _cleanup_upload_temp_dir(upload_temp_dir)
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
        _cleanup_upload_temp_dir(upload_temp_dir)
        return

    if bvid is not None and existing_transcription_service.handle_if_existing(
        job_id=job_id,
        bvid=bvid,
        storage_backend=storage_backend,
        config=config,
        skip_summary=skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        auto_generate_fancy_html=auto_generate_fancy_html,
    ):
        _cleanup_upload_temp_dir(upload_temp_dir)
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
            if normalized_audio_path:
                results = run_pipeline(
                    "",
                    config,
                    audio_path=normalized_audio_path,
                    input_bvid=bvid,
                    skip_summary=skip_summary,
                    summary_preset=summary_preset,
                    summary_profile=summary_profile,
                    storage_backend=storage_backend,
                    stt_storage_backend=stt_storage_backend,
                    progress_callback=lambda stage, label, progress: _update_job(
                        job_id,
                        status="running",
                        stage=stage,
                        stage_label=label,
                        progress=progress,
                    ),
                )
            else:
                results = run_pipeline(
                    normalized_url,
                    config,
                    skip_summary=skip_summary,
                    summary_preset=summary_preset,
                    summary_profile=summary_profile,
                    storage_backend=storage_backend,
                    stt_storage_backend=stt_storage_backend,
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

        # Extract metadata
        metadata = results.get("_metadata")
        metadata_fields = {}
        if metadata:
            metadata_fields["author"] = metadata.author
            metadata_fields["pubdate"] = metadata.pubdate
            if getattr(metadata, "title", None):
                metadata_fields["title"] = metadata.title
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
            _run_id = _record_history(
                bvid=bvid,
                results=results,
                config=config,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
            )
            if auto_generate_fancy_html:
                postprocess_scheduler.trigger_fancy_html_generation(
                    job_id=job_id,
                    bvid=bvid,
                    results=results,
                    config=config,
                    storage_backend=storage_backend,
                    run_id=_run_id,
                    summary_preset=summary_preset,
                    summary_profile=summary_profile,
                )
            else:
                _update_job(job_id, fancy_html_status="idle")
            postprocess_scheduler.trigger_rag_index(_run_id, config)
        else:
            _update_job(job_id, fancy_html_status="idle")
    finally:
        root_logger.removeHandler(log_handler)
        log_handler.close()
        _cleanup_upload_temp_dir(upload_temp_dir)
