"""Summary-specific generation endpoints."""

from concurrent.futures import ThreadPoolExecutor
import re

from fastapi import APIRouter, HTTPException

from b2t.history import infer_run_id
from b2t.storage import StoredArtifact
from b2t.storage.base import classify_artifact_filename

from backend.dependencies import get_history_db, get_storage_backend
from backend.download_registry import download_registry
from backend.schemas import GenerateFancyHtmlRequest, GenerateFancyHtmlResponse
from backend.services import _merge_history_artifact, _run_fancy_html_only_from_summary
from backend.settings import get_runtime_app_config

from .history import _to_history_detail_response

router = APIRouter()
_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_RAG_FANCY_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _infer_bvid_from_filename(filename: str) -> str | None:
    match = _BVID_RE.search(filename or "")
    if match is None:
        return None
    return match.group(1).upper()


@router.post("/api/summary/fancy-html", response_model=GenerateFancyHtmlResponse)
def generate_fancy_html(payload: GenerateFancyHtmlRequest) -> GenerateFancyHtmlResponse:
    source_artifact = download_registry.get_artifact(payload.download_id)

    if source_artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")
    if classify_artifact_filename(source_artifact.filename) not in (
        "summary",
        "rag_answer",
    ):
        raise HTTPException(
            status_code=400,
            detail="仅支持基于总结 Markdown 或知识库回答生成 fancy HTML",
        )

    try:
        config = get_runtime_app_config(require_public_api_key=True)
        storage_backend = get_storage_backend()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"初始化配置或存储后端失败: {exc}",
        ) from exc

    history_detail = None
    run_id = (payload.history_run_id or "").strip()
    inferred_bvid = _infer_bvid_from_filename(source_artifact.filename)
    if not run_id and inferred_bvid:
        run_id = infer_run_id(source_artifact.storage_key, bvid=inferred_bvid)

    if run_id:
        db = get_history_db()
        detail = db.get_run_detail(run_id)
        if detail is not None and detail.record_type == "rag_query":
            if detail.fancy_html_status == "running":
                return GenerateFancyHtmlResponse(
                    history_detail=_to_history_detail_response(detail),
                )

            db.update_run_fancy_html_status(run_id, status="running", error="")

            def _run_in_background() -> None:
                try:
                    fancy_artifact = _run_fancy_html_only_from_summary(
                        summary_artifact=source_artifact,
                        storage_backend=storage_backend,
                        config=config,
                        summary_profile=(payload.summary_profile or "").strip() or None,
                    )
                    _merge_history_artifact(
                        run_id=run_id,
                        bvid=inferred_bvid or detail.bvid or run_id.split("-", 1)[0],
                        artifact=fancy_artifact,
                        title=detail.title,
                        author=detail.author,
                        pubdate=detail.pubdate,
                        created_at=detail.created_at,
                        summary_preset=(payload.summary_preset or "").strip(),
                        summary_profile=(payload.summary_profile or "").strip(),
                        fancy_html_status="succeeded",
                        fancy_html_error="",
                    )
                except Exception as exc:
                    db.update_run_fancy_html_status(
                        run_id,
                        status="failed",
                        error=str(exc) or "生成 fancy HTML 失败",
                    )

            _RAG_FANCY_EXECUTOR.submit(_run_in_background)
            history_detail = db.get_run_detail(run_id)
            return GenerateFancyHtmlResponse(
                history_detail=_to_history_detail_response(history_detail)
                if history_detail is not None
                else None,
            )

    try:
        fancy_artifact = _run_fancy_html_only_from_summary(
            summary_artifact=source_artifact,
            storage_backend=storage_backend,
            config=config,
            summary_profile=(payload.summary_profile or "").strip() or None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc) or "生成 fancy HTML 失败",
        ) from exc

    if run_id and inferred_bvid:
        db = get_history_db()
        if db.get_run_detail(run_id) is not None:
            detail = _merge_history_artifact(
                run_id=run_id,
                bvid=inferred_bvid,
                artifact=fancy_artifact,
                summary_preset=(payload.summary_preset or "").strip(),
                summary_profile=(payload.summary_profile or "").strip(),
                fancy_html_status="succeeded",
                fancy_html_error="",
            )
            if detail is not None:
                history_detail = _to_history_detail_response(detail)
    elif (payload.history_run_id or "").strip():
        detail = _merge_history_artifact(
            run_id=run_id,
            bvid=inferred_bvid or run_id.split("-", 1)[0],
            artifact=fancy_artifact,
            summary_preset=(payload.summary_preset or "").strip(),
            summary_profile=(payload.summary_profile or "").strip(),
            fancy_html_status="succeeded",
            fancy_html_error="",
        )
        if detail is not None:
            history_detail = _to_history_detail_response(detail)

    download_id = download_registry.store_artifact(
        StoredArtifact(
            filename=fancy_artifact.filename,
            storage_key=fancy_artifact.storage_key,
            backend=fancy_artifact.backend,
        )
    )
    return GenerateFancyHtmlResponse(
        download_url=f"/api/download/{download_id}",
        filename=fancy_artifact.filename,
        history_detail=history_detail,
    )
