"""History endpoints: list, detail, and delete transcription records."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from b2t.config import resolve_summarize_model_profile, resolve_summary_preset_name
from b2t.history import build_history_artifacts
from b2t.storage import StoredArtifact

from backend.download_registry import download_registry
from backend.dependencies import get_history_db, get_storage_backend
from backend.services import _run_summary_only_from_existing
from backend.schemas import (
    HistoryRegenerateSummaryRequest,
    HistoryDetailArtifactResponse,
    HistoryDetailResponse,
    HistoryItemResponse,
    HistoryListResponse,
)
from backend.settings import get_runtime_app_config, is_delete_enabled

router = APIRouter()
logger = logging.getLogger(__name__)


def _storage_parent_key(storage_key: str) -> str:
    normalized = storage_key.replace("\\", "/").strip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _summary_family_storage_keys(detail, summary_artifact) -> set[str]:
    summary_stem = Path(summary_artifact.filename).stem
    expected_filenames = {
        summary_artifact.filename,
        f"{summary_stem}.txt",
        f"{summary_stem}_fancy.html",
        f"{summary_stem}_table.md",
        f"{summary_stem}_table.pdf",
    }
    parent_key = _storage_parent_key(summary_artifact.storage_key)
    summary_kinds = {
        "summary",
        "summary_text",
        "summary_fancy_html",
        "summary_table_md",
        "summary_table_pdf",
    }

    related: set[str] = set()
    for artifact in detail.artifacts:
        if artifact.kind not in summary_kinds:
            continue
        if artifact.storage_key == summary_artifact.storage_key:
            related.add(artifact.storage_key)
            continue
        if _storage_parent_key(artifact.storage_key) != parent_key:
            continue
        if artifact.filename in expected_filenames:
            related.add(artifact.storage_key)
    return related


def _to_history_detail_response(
    detail,
) -> HistoryDetailResponse:
    artifacts: list[HistoryDetailArtifactResponse] = []
    for artifact in detail.artifacts:
        stored = StoredArtifact(
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
        )
        download_id = download_registry.store_artifact(stored)
        artifacts.append(
            HistoryDetailArtifactResponse(
                kind=artifact.kind,
                filename=artifact.filename,
                download_url=f"/api/download/{download_id}",
                summary_preset=artifact.summary_preset,
                summary_profile=artifact.summary_profile,
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
        record_type=getattr(detail, "record_type", "transcription") or "transcription",
        fancy_html_status=getattr(detail, "fancy_html_status", "idle") or "idle",
        fancy_html_error=(getattr(detail, "fancy_html_error", "") or ""),
    )


@router.get("/api/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    record_type: str = Query(default=""),
) -> HistoryListResponse:
    try:
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    result = db.list_runs(page=page, page_size=page_size, search=search, record_type=record_type)
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
                record_type=item.record_type,
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
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    return _to_history_detail_response(detail)


@router.post(
    "/api/history/{run_id}/regenerate-summary",
    response_model=HistoryDetailResponse,
)
def regenerate_history_summary(
    run_id: str,
    payload: HistoryRegenerateSummaryRequest,
) -> HistoryDetailResponse:
    try:
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    try:
        config = get_runtime_app_config(require_public_api_key=True)
        storage_backend = get_storage_backend()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"初始化配置或存储后端失败: {exc}",
        ) from exc

    summary_preset = (payload.summary_preset or "").strip() or None
    summary_profile = (payload.summary_profile or "").strip() or None
    try:
        resolved_preset = resolve_summary_preset_name(
            summarize=config.summarize,
            summary_presets=config.summary_presets,
            override=summary_preset,
        )
        resolved_profile = summary_profile or config.summarize.profile.strip()
        resolve_summarize_model_profile(
            config.summarize,
            override=resolved_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_results: dict[str, StoredArtifact] = {}
    for artifact in detail.artifacts:
        if artifact.kind in existing_results:
            continue
        existing_results[artifact.kind] = StoredArtifact(
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
        )

    if "markdown" not in existing_results:
        raise HTTPException(
            status_code=400,
            detail="历史转录结果中缺少 Markdown 文件，无法重新生成总结",
        )

    try:
        new_summary_artifacts = _run_summary_only_from_existing(
            bvid=detail.bvid,
            storage_backend=storage_backend,
            config=config,
            existing_results=existing_results,
            summary_preset=resolved_preset,
            summary_profile=resolved_profile,
            title=detail.title,
            author=detail.author,
            pubdate=detail.pubdate,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc) or "重新生成总结失败",
        ) from exc

    appended = build_history_artifacts(
        new_summary_artifacts,
        summary_preset=resolved_preset,
        summary_profile=resolved_profile,
    )
    merged_artifacts = list(detail.artifacts)
    merged_artifacts.extend(appended)

    deduped_artifacts = []
    seen_storage_keys: set[str] = set()
    for artifact in merged_artifacts:
        if artifact.storage_key in seen_storage_keys:
            continue
        seen_storage_keys.add(artifact.storage_key)
        deduped_artifacts.append(artifact)

    db.record_run(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=True,
        artifacts=deduped_artifacts,
    )

    updated = db.get_run_detail(run_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="写入历史记录后读取失败")
    return _to_history_detail_response(updated)


@router.delete(
    "/api/history/{run_id}/artifacts/{download_id}",
    response_model=HistoryDetailResponse,
)
def delete_history_artifact(run_id: str, download_id: str) -> HistoryDetailResponse:
    if not is_delete_enabled():
        raise HTTPException(
            status_code=403,
            detail="open-public 模式不允许删除文件",
        )
    try:
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    target_stored = download_registry.get_artifact(download_id)
    if target_stored is None:
        raise HTTPException(status_code=404, detail="文件下载链接不存在或已过期")

    target_artifact = next(
        (item for item in detail.artifacts if item.storage_key == target_stored.storage_key),
        None,
    )
    if target_artifact is None:
        raise HTTPException(status_code=404, detail="文件不属于该历史记录")

    # Allow deleting summary Markdown (cascading to derived files) or deleting fancy HTML individually.
    if target_artifact.kind not in ("summary", "summary_fancy_html"):
        raise HTTPException(status_code=400, detail="仅支持删除总结 Markdown 或 Fancy HTML 文件")

    if target_artifact.kind == "summary_fancy_html":
        storage_keys_to_delete = {target_artifact.storage_key}
    else:
        storage_keys_to_delete = _summary_family_storage_keys(detail, target_artifact)
        if not storage_keys_to_delete:
            storage_keys_to_delete = {target_artifact.storage_key}

    storage_backend = get_storage_backend()
    failed_files: list[str] = []
    for artifact in detail.artifacts:
        if artifact.storage_key not in storage_keys_to_delete:
            continue
        try:
            storage_backend.delete_file(artifact.storage_key)
        except Exception as exc:
            logger.warning("删除文件 %s 失败: %s", artifact.filename, exc)
            failed_files.append(artifact.filename)
    if failed_files:
        raise HTTPException(
            status_code=500,
            detail=f"删除部分文件失败: {', '.join(failed_files)}",
        )

    download_registry.remove_artifacts_by_storage_keys(storage_keys_to_delete)

    remained_artifacts = [
        item for item in detail.artifacts if item.storage_key not in storage_keys_to_delete
    ]
    has_summary = any(
        item.kind
        in {
            "summary",
            "summary_text",
            "summary_fancy_html",
            "summary_table_md",
            "summary_table_pdf",
        }
        for item in remained_artifacts
    )
    db.record_run(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=has_summary,
        artifacts=remained_artifacts,
        record_type=detail.record_type,
    )

    updated = db.get_run_detail(run_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="删除文件后读取历史记录失败")
    return _to_history_detail_response(updated)


@router.delete("/api/history/{run_id}")
def delete_history(run_id: str) -> dict[str, str]:
    """Delete a history record and its associated files."""
    if not is_delete_enabled():
        raise HTTPException(
            status_code=403,
            detail="open-public 模式不允许删除历史记录",
        )
    try:
        db = get_history_db()
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
    storage_backend = get_storage_backend()
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
