"""Generate a reading report directly from a historical transcript."""

from dataclasses import replace
from threading import Lock

from fastapi import APIRouter, HTTPException

from b2t.config import resolve_summarize_model_profile
from b2t.download.yutto_cli import extract_bilibili_page_from_target_id
from b2t.report.pi import check_runtime, model_config, safe_error_detail
from b2t.storage import ArtifactKind, StoredArtifact
from backend.dependencies import get_history_db, get_storage_backend
from backend.event_stream import event_broker, history_channel
from backend.report_service import generate_stored_report
from backend.schemas import HistoryDetailResponse, HistoryReportRequest
from backend.services import _merge_history_artifact
from backend.settings import get_runtime_app_config
from backend.task_queue import TaskQueueFull, submit_report

from .history import _to_history_detail_response

router = APIRouter()
_report_lock = Lock()


def _stored(artifact) -> StoredArtifact:
    return StoredArtifact(
        filename=artifact.filename,
        storage_key=artifact.storage_key,
        backend=artifact.backend,
        kind=artifact.kind,
        derived_from=artifact.derived_from,
    )


@router.post("/api/history/{run_id}/report", response_model=HistoryDetailResponse)
def generate_history_report(run_id: str, payload: HistoryReportRequest):
    db = get_history_db()
    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")
    source = next(
        (a for a in detail.artifacts if a.kind == ArtifactKind.MARKDOWN), None
    )
    if detail.record_type == "rag_query" or source is None:
        raise HTTPException(status_code=400, detail="缺少完整转录，无法生成阅读报告")
    json_source = next(
        (a for a in detail.artifacts if a.kind == ArtifactKind.JSON), None
    )
    try:
        config = get_runtime_app_config(
            require_public_api_key=False,
            user_credentials_only=True,
            **payload.runtime_config_kwargs(),
        )
        options = payload.report_options
        profile = resolve_summarize_model_profile(
            config.summarize,
            override=options.profile.strip() or config.fancy_html.profile,
        )
        model_config(profile)
        check_runtime()
        storage = get_storage_backend()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    def publish_change():
        event_broker.publish(history_channel(run_id))

    def generate():
        try:
            metadata = {
                "title": detail.title,
                "author": detail.author,
                "url": payload.source_url,
            }
            if not metadata["url"] and detail.bvid.startswith("BV"):
                metadata["url"] = f"https://www.bilibili.com/video/{detail.bvid}/"
                page = extract_bilibili_page_from_target_id(run_id)
                if page and page > 1:
                    metadata["url"] += f"?p={page}"
            artifact = generate_stored_report(
                source_artifact=_stored(source),
                json_artifact=_stored(json_source) if json_source else None,
                storage_backend=storage,
                config=config,
                options=options,
                metadata=metadata,
            )
            if db.get_run_detail(run_id) is None:
                storage.delete_file(artifact.storage_key)
                return
            _merge_history_artifact(
                run_id=run_id,
                bvid=detail.bvid,
                artifact=artifact,
                title=detail.title,
                author=detail.author,
                pubdate=detail.pubdate,
                created_at=detail.created_at,
                summary_profile=artifact.summary_profile,
                fancy_html_status="succeeded",
                fancy_html_error="",
            )
        except Exception as exc:  # noqa: BLE001
            db.update_run_fancy_html_status(
                run_id,
                status="failed",
                error=safe_error_detail(str(exc), profile.api_key),
            )
        finally:
            publish_change()

    with _report_lock:
        current = db.get_run_detail(run_id)
        if current is None:
            raise HTTPException(status_code=404, detail="转录记录不存在")
        if current.fancy_html_status in {"pending", "running"}:
            return _to_history_detail_response(current)
        db.update_run_fancy_html_status(run_id, status="running", error="")
        try:
            submit_report(generate)
        except TaskQueueFull:
            db.update_run_fancy_html_status(
                run_id, status="failed", error="阅读报告队列已满，请稍后重试"
            )
            publish_change()
            raise HTTPException(
                status_code=503, detail="阅读报告队列已满，请稍后重试"
            ) from None
        publish_change()
        return _to_history_detail_response(
            replace(current, fancy_html_status="running", fancy_html_error="")
        )
