"""History endpoints: list, detail, and delete transcription records."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from b2t.config import resolve_summarize_model_profile, resolve_summary_preset_name
from b2t.download.bilibili_categories import (
    get_bilibili_category_filter_tids,
    get_bilibili_parent_tid,
    get_bilibili_parent_tname,
    get_bilibili_tname,
)
from b2t.download.metadata import VideoMetadata
from b2t.download.yutto_cli import extract_bilibili_page_from_target_id
from b2t.history import build_history_artifacts
from b2t.storage import SUMMARY_ARTIFACT_KINDS, StoredArtifact
from backend.artifacts import summary_artifact_group_ids
from backend.artifacts import (
    summary_family_storage_keys as _summary_family_storage_keys,
)
from backend.dependencies import get_history_db, get_storage_backend
from backend.download_registry import download_registry
from backend.event_stream import event_broker, history_channel
from backend.schemas import (
    HistoryAuthorFilterOptionResponse,
    HistoryCategoryFilterOptionResponse,
    HistoryDetailArtifactResponse,
    HistoryDetailResponse,
    HistoryFilterOptionsResponse,
    HistoryItemResponse,
    HistoryListResponse,
    HistoryPlatformFilterOptionResponse,
    HistoryRegenerateSummaryRequest,
)
from backend.services import _run_summary_only_from_existing
from backend.settings import get_runtime_app_config, is_delete_enabled

router = APIRouter()
CUSTOM_SUMMARY_PRESET_VALUE = "__user_custom__"
logger = logging.getLogger(__name__)
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_PLATFORM_NAMES = {
    "bilibili": "Bilibili",
    "xiaoyuzhou": "小宇宙",
    "ximalaya": "喜马拉雅",
    "upload": "本地上传",
    "knowledge_base": "知识库查询",
}


def _summary_config_storage_keys(
    detail,
    summary_preset: str,
    summary_profile: str,
) -> set[str]:
    """Return every artifact belonging to a generated summary configuration."""
    matching_summaries = [
        artifact
        for artifact in detail.artifacts
        if artifact.kind == "summary"
        and artifact.summary_preset.strip() == summary_preset
        and artifact.summary_profile.strip() == summary_profile
    ]
    if not matching_summaries:
        return set()

    storage_keys = {
        artifact.storage_key
        for artifact in detail.artifacts
        if artifact.kind in SUMMARY_ARTIFACT_KINDS
        and artifact.summary_preset.strip() == summary_preset
        and artifact.summary_profile.strip() == summary_profile
    }
    for summary_artifact in matching_summaries:
        storage_keys.update(_summary_family_storage_keys(detail, summary_artifact))
    return storage_keys


def _to_history_detail_response(
    detail,
) -> HistoryDetailResponse:
    artifacts: list[HistoryDetailArtifactResponse] = []
    summary_group_ids = summary_artifact_group_ids(detail.artifacts)
    for artifact in detail.artifacts:
        stored = StoredArtifact(
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
            kind=artifact.kind,
            derived_from=artifact.derived_from,
            summary_preset=artifact.summary_preset,
            summary_profile=artifact.summary_profile,
        )
        download_id = download_registry.store_artifact(stored)
        artifacts.append(
            HistoryDetailArtifactResponse(
                kind=artifact.kind,
                filename=artifact.filename,
                download_url=f"/api/download/{download_id}",
                summary_preset=artifact.summary_preset,
                summary_profile=artifact.summary_profile,
                derived_from=artifact.derived_from,
                summary_group_id=summary_group_ids.get(artifact.storage_key, ""),
            )
        )

    return HistoryDetailResponse(
        run_id=detail.run_id,
        bvid=detail.bvid,
        page=extract_bilibili_page_from_target_id(detail.run_id),
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=detail.has_summary,
        artifacts=artifacts,
        record_type=getattr(detail, "record_type", "transcription") or "transcription",
        fancy_html_status=getattr(detail, "fancy_html_status", "idle") or "idle",
        fancy_html_error=(getattr(detail, "fancy_html_error", "") or ""),
        summary_regenerations=[
            {
                "summary_preset": task.summary_preset,
                "summary_profile": task.summary_profile,
                "status": task.status,
                "error": task.error,
            }
            for task in getattr(detail, "summary_regenerations", [])
        ],
    )


def _resolve_regenerate_summary_preset(
    *,
    config,
    summary_preset: str | None,
    summary_prompt_template: str | None,
) -> str:
    if summary_preset == CUSTOM_SUMMARY_PRESET_VALUE:
        if not summary_prompt_template:
            raise ValueError("用户自定义总结模板不能为空")
        return CUSTOM_SUMMARY_PRESET_VALUE
    return resolve_summary_preset_name(
        summarize=config.summarize,
        summary_presets=config.summary_presets,
        override=summary_preset,
    )


def _persist_regenerated_summary(
    *,
    db,
    detail,
    storage_backend,
    new_summary_artifacts: dict[str, object],
    replaced_storage_keys: set[str],
    resolved_preset: str,
    resolved_profile: str,
) -> None:
    appended = build_history_artifacts(
        {
            key: artifact
            for key, artifact in new_summary_artifacts.items()
            if not key.startswith("_")
        },
        summary_preset=resolved_preset,
        summary_profile=resolved_profile,
    )
    metadata = new_summary_artifacts.get("_metadata")
    author = detail.author
    pubdate = detail.pubdate
    if isinstance(metadata, VideoMetadata):
        if not author.strip() or author.strip().lower() == "unknown":
            author = metadata.author
        if not pubdate.strip() or pubdate.strip().lower() == "unknown":
            pubdate = metadata.pubdate

    db.replace_summary_artifacts(
        detail.run_id,
        artifacts=appended,
        replaced_storage_keys=replaced_storage_keys,
        author=author,
        pubdate=pubdate,
    )

    if not replaced_storage_keys:
        return
    download_registry.remove_artifacts_by_storage_keys(replaced_storage_keys)
    for artifact in detail.artifacts:
        if artifact.storage_key not in replaced_storage_keys:
            continue
        try:
            storage_backend.delete_file(artifact.storage_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "清理被覆盖的总结文件 %s 失败: %s",
                artifact.filename,
                exc,
            )


@router.get("/api/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    record_type: str = Query(default=""),
    platform: Annotated[list[str] | None, Query()] = None,
    category_tid: Annotated[list[int] | None, Query()] = None,
    author: Annotated[list[str] | None, Query()] = None,
) -> HistoryListResponse:
    try:
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    selected_category_tids = category_tid if isinstance(category_tid, list) else []
    selected_authors = author if isinstance(author, list) else []
    selected_platforms = platform if isinstance(platform, list) else []
    expanded_category_tids = tuple(
        sorted(
            {
                expanded_tid
                for selected_tid in selected_category_tids
                if selected_tid > 0
                for expanded_tid in get_bilibili_category_filter_tids(selected_tid)
            }
        )
    )
    result = db.list_runs(
        page=page,
        page_size=page_size,
        search=search,
        record_type=record_type,
        platforms=tuple(selected_platforms),
        category_tids=expanded_category_tids,
        authors=tuple(selected_authors),
    )
    return HistoryListResponse(
        items=[
            HistoryItemResponse(
                run_id=item.run_id,
                bvid=item.bvid,
                page=extract_bilibili_page_from_target_id(item.run_id),
                title=item.title,
                author=item.author,
                pubdate=item.pubdate,
                created_at=item.created_at,
                has_summary=item.has_summary,
                file_count=item.file_count,
                tid=item.tid,
                tname=get_bilibili_tname(item.tid),
                parent_tname=get_bilibili_parent_tname(item.tid),
                record_type=item.record_type,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@router.get("/api/history/filters", response_model=HistoryFilterOptionsResponse)
def history_filter_options() -> HistoryFilterOptionsResponse:
    try:
        db = get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    category_counts = dict(db.list_history_category_counts())
    grouped_tids: dict[int, list[int]] = {}
    standalone_tids: list[int] = []
    for tid in category_counts:
        parent_tid = get_bilibili_parent_tid(tid)
        if parent_tid > 0:
            grouped_tids.setdefault(parent_tid, []).append(tid)
        else:
            standalone_tids.append(tid)

    def group_count(tid: int) -> int:
        return category_counts.get(tid, 0) + sum(
            category_counts[child_tid] for child_tid in grouped_tids.get(tid, [])
        )

    top_level_tids = set(standalone_tids) | set(grouped_tids)
    ordered_top_level_tids = sorted(
        (tid for tid in top_level_tids if get_bilibili_tname(tid)),
        key=lambda tid: (-group_count(tid), get_bilibili_tname(tid)),
    )

    categories: list[HistoryCategoryFilterOptionResponse] = []
    for parent_tid in ordered_top_level_tids:
        child_tids = sorted(
            grouped_tids.get(parent_tid, []),
            key=lambda tid: (-category_counts[tid], get_bilibili_tname(tid)),
        )
        categories.append(
            HistoryCategoryFilterOptionResponse(
                tid=parent_tid,
                tname=get_bilibili_tname(parent_tid),
                count=group_count(parent_tid),
                is_parent=bool(child_tids),
            )
        )
        for child_tid in child_tids:
            categories.append(
                HistoryCategoryFilterOptionResponse(
                    tid=child_tid,
                    tname=get_bilibili_tname(child_tid),
                    parent_tid=parent_tid,
                    parent_tname=get_bilibili_tname(parent_tid),
                    count=category_counts[child_tid],
                )
            )
    authors = [
        HistoryAuthorFilterOptionResponse(author=author, count=count)
        for author, count in db.list_history_author_counts()
    ]
    platforms = [
        HistoryPlatformFilterOptionResponse(
            platform=platform,
            name=_PLATFORM_NAMES[platform],
            count=count,
        )
        for platform, count in db.list_history_platform_counts()
        if platform in _PLATFORM_NAMES
    ]
    return HistoryFilterOptionsResponse(
        platforms=platforms,
        categories=categories,
        authors=authors,
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


@router.get("/api/history/{run_id}/events")
async def history_events(run_id: str) -> StreamingResponse:
    db = get_history_db()
    if db.get_run_detail(run_id) is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    async def stream() -> AsyncIterator[str]:
        subscription = event_broker.subscribe([history_channel(run_id)])
        try:
            while True:
                detail = db.get_run_detail(run_id)
                if detail is None:
                    yield f'event: deleted\ndata: {{"run_id": {json.dumps(run_id)} }}\n\n'
                    return
                response = _to_history_detail_response(detail)
                yield (
                    "event: history\ndata: "
                    f"{json.dumps(response.model_dump(mode='json'), ensure_ascii=False)}"
                    "\n\n"
                )
                has_active_update = response.fancy_html_status in {
                    "pending",
                    "running",
                } or any(
                    task.status == "running" for task in response.summary_regenerations
                )
                if not has_active_update:
                    return
                if not await subscription.wait():
                    yield ": keep-alive\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


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
        config = get_runtime_app_config(
            require_public_api_key=True,
            **payload.runtime_config_kwargs(),
        )
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

    summary_preset = payload.summary_preset
    summary_profile = payload.summary_profile
    summary_prompt_template = payload.summary_prompt_template
    try:
        resolved_preset = _resolve_regenerate_summary_preset(
            config=config,
            summary_preset=summary_preset,
            summary_prompt_template=summary_prompt_template,
        )
        resolved_profile = summary_profile or config.summarize.profile.strip()
        model_profile = resolve_summarize_model_profile(
            config.summarize,
            override=resolved_profile,
        )
        if not model_profile.api_key.strip():
            provider_label = (
                "DeepSeek"
                if model_profile.provider.strip().lower() == "deepseek"
                else model_profile.provider
            )
            raise ValueError(
                f"模型 {resolved_profile}（{provider_label}）需要 API Key，"
                "但你未提供。请在「API Key」页面配置对应的 Key 后再试。"
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    replaced_storage_keys = _summary_config_storage_keys(
        detail,
        resolved_preset,
        resolved_profile,
    )
    if replaced_storage_keys and not payload.overwrite_existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"已存在使用模型配置 {resolved_profile} 与总结模板 {resolved_preset} "
                "生成的总结。覆盖前需要用户确认。"
            ),
        )

    existing_results: dict[str, StoredArtifact] = {}
    for artifact in detail.artifacts:
        if artifact.kind in existing_results:
            continue
        existing_results[artifact.kind] = StoredArtifact(
            filename=artifact.filename,
            storage_key=artifact.storage_key,
            backend=artifact.backend,
            kind=artifact.kind,
            derived_from=artifact.derived_from,
            summary_preset=artifact.summary_preset,
            summary_profile=artifact.summary_profile,
        )

    if "markdown" not in existing_results:
        raise HTTPException(
            status_code=400,
            detail="历史转录结果中缺少 Markdown 文件，无法重新生成总结",
        )

    started = db.try_start_summary_regeneration(
        run_id,
        summary_preset=resolved_preset,
        summary_profile=resolved_profile,
    )
    if not started:
        raise HTTPException(
            status_code=409,
            detail=(
                f"模型配置 {resolved_profile} 与总结模板 {resolved_preset} "
                "正在生成中，请等待当前任务完成。"
            ),
        )
    event_broker.publish(history_channel(run_id))

    try:
        new_summary_artifacts = _run_summary_only_from_existing(
            bvid=detail.bvid,
            storage_backend=storage_backend,
            config=config,
            existing_results=existing_results,
            summary_preset=resolved_preset,
            summary_profile=resolved_profile,
            summary_prompt_template=summary_prompt_template,
            title=detail.title,
            author=detail.author,
            pubdate=detail.pubdate,
        )
        _persist_regenerated_summary(
            db=db,
            detail=detail,
            storage_backend=storage_backend,
            new_summary_artifacts=new_summary_artifacts,
            replaced_storage_keys=replaced_storage_keys,
            resolved_preset=resolved_preset,
            resolved_profile=resolved_profile,
        )
    except Exception as exc:
        error = str(exc) or "重新生成总结失败"
        db.update_summary_regeneration_status(
            run_id,
            summary_preset=resolved_preset,
            summary_profile=resolved_profile,
            status="failed",
            error=error,
        )
        event_broker.publish(history_channel(run_id))
        raise HTTPException(
            status_code=500,
            detail=error,
        ) from exc

    db.update_summary_regeneration_status(
        run_id,
        summary_preset=resolved_preset,
        summary_profile=resolved_profile,
        status="succeeded",
        error="",
    )
    event_broker.publish(history_channel(run_id))

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
        (
            item
            for item in detail.artifacts
            if item.storage_key == target_stored.storage_key
        ),
        None,
    )
    if target_artifact is None:
        raise HTTPException(status_code=404, detail="文件不属于该历史记录")

    # Allow deleting summary Markdown (cascading to derived files) or deleting fancy HTML individually.
    if target_artifact.kind not in ("summary", "summary_fancy_html"):
        raise HTTPException(
            status_code=400, detail="仅支持删除总结 Markdown 或 Fancy HTML 文件"
        )

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
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除文件 %s 失败: %s", artifact.filename, exc)
            failed_files.append(artifact.filename)
    if failed_files:
        raise HTTPException(
            status_code=500,
            detail=f"删除部分文件失败: {', '.join(failed_files)}",
        )

    download_registry.remove_artifacts_by_storage_keys(storage_keys_to_delete)

    remained_artifacts = [
        item
        for item in detail.artifacts
        if item.storage_key not in storage_keys_to_delete
    ]
    has_summary = any(
        item.kind in SUMMARY_ARTIFACT_KINDS for item in remained_artifacts
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
        except Exception as exc:  # noqa: BLE001
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
