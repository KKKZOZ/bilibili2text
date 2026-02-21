"""History endpoints: list, detail, and delete transcription records."""

import logging

from fastapi import APIRouter, HTTPException, Query

from b2t.storage import StoredArtifact

from backend.downloads import _store_download
from backend.schemas import (
    HistoryDetailArtifactResponse,
    HistoryDetailResponse,
    HistoryItemResponse,
    HistoryListResponse,
)
from backend.state import _get_history_db, _get_storage_backend

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
) -> HistoryListResponse:
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    result = db.list_runs(page=page, page_size=page_size, search=search)
    return HistoryListResponse(
        items=[
            HistoryItemResponse(
                run_id=item.run_id,
                bvid=item.bvid,
                title=item.title,
                author=item.author,
                pubdate=item.pubdate,
                created_at=item.created_at,
                has_summary=item.has_summary,
                file_count=item.file_count,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@router.get("/api/history/{run_id}", response_model=HistoryDetailResponse)
def history_detail(run_id: str) -> HistoryDetailResponse:
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    storage_backend = _get_storage_backend()
    artifacts: list[HistoryDetailArtifactResponse] = []
    for a in detail.artifacts:
        stored = StoredArtifact(
            filename=a.filename,
            storage_key=a.storage_key,
            backend=a.backend,
        )
        download_id = _store_download(stored)
        artifacts.append(
            HistoryDetailArtifactResponse(
                kind=a.kind,
                filename=a.filename,
                download_url=f"/api/download/{download_id}",
            )
        )

    return HistoryDetailResponse(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=detail.has_summary,
        artifacts=artifacts,
    )


@router.delete("/api/history/{run_id}")
def delete_history(run_id: str) -> dict[str, str]:
    """Delete a history record and its associated files."""
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    # Check if record exists
    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    # Delete from database and get artifacts
    artifacts = db.delete_run(run_id)

    # Delete files
    storage_backend = _get_storage_backend()
    deleted_count = 0
    failed_files: list[str] = []

    for artifact in artifacts:
        try:
            storage_backend.delete_file(artifact.storage_key)
            deleted_count += 1
        except Exception as exc:
            logger.warning(
                "删除文件 %s 失败: %s",
                artifact.filename,
                exc,
            )
            failed_files.append(artifact.filename)

    if failed_files:
        logger.warning(
            "删除记录 %s 时，部分文件删除失败: %s",
            run_id,
            ", ".join(failed_files),
        )

    return {
        "message": f"已删除记录，成功删除 {deleted_count} 个文件"
        + (f"，{len(failed_files)} 个文件删除失败" if failed_files else "")
    }
