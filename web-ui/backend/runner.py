"""Background job execution: the ``_run_job`` orchestrator."""

import logging
from pathlib import Path
import shutil
from datetime import datetime
from threading import Thread, get_ident

from b2t.download.yutto_cli import extract_bvid
from b2t.pipeline import run_pipeline

from backend.jobs import _append_job_log, _get_job, _update_job
from backend.logging_config import (
    JOB_LOG_DATE_FORMAT,
    _JobLogHandler,
    _redact_text,
)
from backend.services import (
    _build_all_download_items,
    _build_success_download_fields,
    _collect_all_artifacts_for_bvid,
    _artifact_download_item,
    _merge_history_artifact,
    _record_history,
    _run_fancy_html_only_from_summary,
    _run_summary_only_from_existing,
)
from backend.state import (
    _get_app_config,
    _get_history_db,
    _get_rag_store,
    _get_runtime_app_config,
    _get_storage_backend,
    _get_stt_storage_backend,
)

logger = logging.getLogger(__name__)


def _cleanup_upload_temp_dir(temp_dir: Path | None) -> None:
    if temp_dir is None:
        return
    shutil.rmtree(temp_dir, ignore_errors=True)


def _trigger_rag_index(run_id: str | None, config) -> None:
    """Trigger background RAG indexing for a completed run."""
    if run_id is None or not config.rag.enabled:
        return

    def _do_index() -> None:
        try:
            from b2t.rag.indexer import index_run  # noqa: PLC0415
            count = index_run(
                run_id=run_id,
                history_db=_get_history_db(),
                storage_backend=_get_storage_backend(),
                rag_config=config.rag,
                store=_get_rag_store(),
                force=True,
            )
            logger.info("RAG 索引完成: run_id=%s, chunks=%d", run_id, count)
        except Exception as exc:
            logger.warning("RAG 索引失败（不影响转录结果）: %s", exc)

    Thread(target=_do_index, daemon=True).start()


def _trigger_fancy_html_generation(
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
    if not hasattr(summary_artifact, "storage_key") or not hasattr(summary_artifact, "filename"):
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
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [WARNING] b2t.pipeline: {_redact_text(f'Fancy HTML 生成失败: {exc}')}",
            )

    Thread(target=_do_generate, daemon=True).start()


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
        config = _get_runtime_app_config(require_public_api_key=True)
        storage_backend = _get_storage_backend()
        stt_storage_backend = _get_stt_storage_backend()
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
                    _run_id = _record_history(
                        bvid=bvid,
                        results=existing_results,
                        config=config,
                    )
                    _trigger_rag_index(_run_id, config)
                    _cleanup_upload_temp_dir(upload_temp_dir)
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
                    _cleanup_upload_temp_dir(upload_temp_dir)
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
                    _cleanup_upload_temp_dir(upload_temp_dir)
                    return

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
                _append_job_log(
                    job_id,
                    f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.pipeline: {_redact_text(notice)}",
                )
                _run_id = _record_history(
                    bvid=bvid,
                    results=combined_results,
                    config=config,
                    summary_preset=summary_preset,
                    summary_profile=summary_profile,
                )
                if auto_generate_fancy_html:
                    _trigger_fancy_html_generation(
                        job_id=job_id,
                        bvid=bvid,
                        results=combined_results,
                        config=config,
                        storage_backend=storage_backend,
                        run_id=_run_id,
                        summary_preset=summary_preset,
                        summary_profile=summary_profile,
                    )
                else:
                    _update_job(job_id, fancy_html_status="idle")
                _trigger_rag_index(_run_id, config)
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

        # 提取元信息
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
                _trigger_fancy_html_generation(
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
            _trigger_rag_index(_run_id, config)
        else:
            _update_job(job_id, fancy_html_status="idle")
    finally:
        root_logger.removeHandler(log_handler)
        log_handler.close()
        _cleanup_upload_temp_dir(upload_temp_dir)
