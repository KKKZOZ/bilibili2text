"""Background job execution: the ``_run_job`` orchestrator."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from threading import get_ident

from b2t.download.comments import DEFAULT_COMMENT_LIMIT
from b2t.download.platform import Platform
from b2t.download.url_detect import detect_platform, extract_platform_id
from b2t.download.ximalaya import resolve_ximalaya_sound_url
from b2t.download.yutto_cli import extract_bvid, normalize_bilibili_target
from b2t.pipeline import run_pipeline
from backend.bvid_locks import bvid_transcription_locks
from backend.dependencies import (
    get_storage_backend,
    get_stt_storage_backend,
)
from backend.ephemeral_uploads import (
    ephemeral_upload_expires_at,
    serialize_ephemeral_artifacts,
)
from backend.existing_transcriptions import existing_transcription_service
from backend.jobs import _append_job_log, _update_job
from backend.logging_config import (
    JOB_LOG_DATE_FORMAT,
    _JobLogHandler,
    _redact_text,
)
from backend.postprocess import postprocess_scheduler
from backend.services import (
    _build_all_download_items,
    _build_success_download_fields,
    _collect_all_artifacts_for_bvid,
    _generate_summary_png_exports,
    _record_history,
)
from backend.settings import STOCK_STATUS_SYNC_TIMEOUT_SECONDS, get_runtime_app_config

logger = logging.getLogger(__name__)


def _infer_resource_id_from_url(url: str) -> tuple[str, str | None]:
    """Normalize supported URLs and return an ID suitable for cache/lock lookup."""
    normalized_url = url.strip()
    platform = detect_platform(normalized_url)
    if platform is None or platform == Platform.BILIBILI:
        try:
            normalized_url = normalize_bilibili_target(normalized_url)
        except Exception:
            pass
        return normalized_url, extract_bvid(normalized_url)

    if platform == Platform.XIMALAYA:
        try:
            normalized_url, platform_id = resolve_ximalaya_sound_url(normalized_url)
        except Exception as exc:
            logger.warning("Unable to resolve Ximalaya resource ID early: %s", exc)
            return normalized_url, None
    else:
        platform_id = extract_platform_id(normalized_url, platform)
        if platform_id is None:
            return normalized_url, None

    return normalized_url, f"{platform.value}_{platform_id}"


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
    summary_prompt_template: str | None,
    auto_generate_fancy_html: bool,
    prefer_bilibili_subtitle: bool = True,
    include_comments: bool = True,
    comment_limit: int | None = DEFAULT_COMMENT_LIMIT,
    ephemeral_upload: bool = False,
    api_key: str | None = None,
    deepseek_api_key: str | None = None,
    custom_llm_base_url: str | None = None,
    custom_llm_api_key: str | None = None,
    custom_llm_model: str | None = None,
) -> None:
    normalized_url = (url or "").strip()
    normalized_audio_path = (input_audio_path or "").strip()
    bvid = (input_bvid or "").strip() or None
    transcription_id = bvid
    if bvid is None and normalized_url:
        normalized_url, bvid = _infer_resource_id_from_url(normalized_url)
        transcription_id = bvid

    upload_temp_dir: Path | None = None
    if normalized_audio_path:
        upload_temp_dir = Path(normalized_audio_path).expanduser().resolve().parent

    try:
        config = get_runtime_app_config(
            require_public_api_key=True,
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            custom_llm_base_url=custom_llm_base_url,
            custom_llm_api_key=custom_llm_api_key,
            custom_llm_model=custom_llm_model,
        )
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

    if bvid is not None and not ephemeral_upload:
        _update_job(job_id, bvid=bvid)

    if (
        not ephemeral_upload
        and bvid is not None
        and existing_transcription_service.handle_if_existing(
            job_id=job_id,
            bvid=bvid,
            transcription_id=transcription_id,
            storage_backend=storage_backend,
            config=config,
            skip_summary=skip_summary,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            summary_prompt_template=summary_prompt_template,
            auto_generate_fancy_html=auto_generate_fancy_html,
            include_comments=include_comments,
            comment_limit=comment_limit,
        )
    ):
        _cleanup_upload_temp_dir(upload_temp_dir)
        return

    acquired_bvid_lock = False
    if bvid is not None and not ephemeral_upload:
        claim = bvid_transcription_locks.acquire(transcription_id or bvid, job_id)
        if not claim.acquired:
            error_message = (
                f"{bvid} 的转录任务正在进行中，请稍后再试。"
                "如果上一个任务超过 10 分钟仍未完成，系统会允许重新提交。"
            )
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="转录正在进行",
                progress=0,
                bvid=bvid,
                error=error_message,
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [WARNING] b2t.pipeline: {_redact_text(error_message)}",
            )
            _cleanup_upload_temp_dir(upload_temp_dir)
            return
        acquired_bvid_lock = True

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
                    summary_prompt_template=summary_prompt_template,
                    storage_backend=storage_backend,
                    stt_storage_backend=stt_storage_backend,
                    prefer_bilibili_subtitle=False,
                    include_comments=False,
                    progress_callback=lambda stage, label, progress: _update_job(
                        job_id,
                        status="running",
                        stage=stage,
                        stage_label=label,
                        progress=progress,
                    ),
                    bilibili_subtitle_used_callback=lambda: _update_job(
                        job_id,
                        used_bilibili_subtitle=True,
                    ),
                )
            else:
                results = run_pipeline(
                    normalized_url,
                    config,
                    skip_summary=skip_summary,
                    summary_preset=summary_preset,
                    summary_profile=summary_profile,
                    summary_prompt_template=summary_prompt_template,
                    storage_backend=storage_backend,
                    stt_storage_backend=stt_storage_backend,
                    prefer_bilibili_subtitle=prefer_bilibili_subtitle,
                    include_comments=include_comments,
                    comment_limit=comment_limit,
                    progress_callback=lambda stage, label, progress: _update_job(
                        job_id,
                        status="running",
                        stage=stage,
                        stage_label=label,
                        progress=progress,
                    ),
                    bilibili_subtitle_used_callback=lambda: _update_job(
                        job_id,
                        used_bilibili_subtitle=True,
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

        png_export_warning: str | None = None
        if not skip_summary and "summary" in results:
            _update_job(
                job_id,
                status="running",
                stage="postprocessing",
                stage_label="后处理及文件导出",
                progress=96,
            )
            try:
                png_results = _generate_summary_png_exports(
                    results=results,
                    storage_backend=storage_backend,
                    config=config,
                    stock_status_timeout_seconds=STOCK_STATUS_SYNC_TIMEOUT_SECONDS,
                )
                results.update(png_results)
            except Exception as exc:
                png_export_warning = (
                    "PNG 图片导出失败，转录和总结已完成；可先下载 Markdown/文本结果。"
                )
                logger.warning("后处理及文件导出失败（不影响转录结果）: %s", exc)
                _append_job_log(
                    job_id,
                    f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [WARNING] b2t.pipeline: 后处理及文件导出失败（不影响转录结果）: {_redact_text(str(exc))}",
                )

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

        # Extract metadata. Non-Bilibili platforms only get a resource ID after
        # download (e.g. xiaoyuzhou_<eid>), so backfill bvid from pipeline
        # metadata before history / locks / UI fields are written.
        metadata = results.get("_metadata")
        if bvid is None and metadata is not None:
            metadata_bvid = getattr(metadata, "bvid", None)
            if isinstance(metadata_bvid, str) and metadata_bvid.strip():
                bvid = metadata_bvid.strip()

        metadata_fields = {}
        if metadata:
            metadata_fields["author"] = metadata.author
            metadata_fields["pubdate"] = metadata.pubdate
            if getattr(metadata, "title", None):
                metadata_fields["title"] = metadata.title
        if bvid and not ephemeral_upload:
            metadata_fields["bvid"] = bvid

        try:
            all_artifacts = _collect_all_artifacts_for_bvid(
                storage_backend,
                None if ephemeral_upload else transcription_id,
                results,
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
            notice=png_export_warning,
            all_downloads=all_downloads,
            error=None,
            is_ephemeral_upload=ephemeral_upload,
            expires_at=ephemeral_upload_expires_at() if ephemeral_upload else None,
            ephemeral_artifacts=(
                serialize_ephemeral_artifacts(all_artifacts) if ephemeral_upload else []
            ),
            **success_fields,
            **metadata_fields,
        )
        if ephemeral_upload:
            _update_job(
                job_id,
                notice="临时上传转录结果将在完成后 2 小时自动删除。",
                fancy_html_status="idle",
            )
        elif bvid is not None:
            _run_id = _record_history(
                bvid=bvid,
                results=results,
                config=config,
                summary_preset=summary_preset,
                summary_profile=summary_profile,
            )
            if _run_id:
                _update_job(job_id, history_run_id=_run_id)
            postprocess_scheduler.trigger_stock_status_refresh(
                bvid=bvid,
                results=results,
                config=config,
                storage_backend=storage_backend,
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
        if acquired_bvid_lock and transcription_id is not None:
            bvid_transcription_locks.release(transcription_id, job_id)
        root_logger.removeHandler(log_handler)
        log_handler.close()
        _cleanup_upload_temp_dir(upload_temp_dir)
