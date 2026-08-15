"""RAG API endpoints."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.dependencies import get_history_db, get_rag_store, get_storage_backend
from backend.download_registry import download_registry
from backend.rag_answer_repository import RagAnswerRepository
from backend.rag_query import RagQueryService
from backend.schemas_rag import (
    RagAuthorItem,
    RagAuthorsResponse,
    RagIndexAllResponse,
    RagIndexedItem,
    RagIndexRequest,
    RagIndexResponse,
    RagQueryRequest,
    RagQueryResponse,
    RagStatusResponse,
)
from backend.settings import get_runtime_app_config

router = APIRouter(prefix="/api/rag", tags=["rag"])
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)


def _require_rag_enabled() -> None:
    config = get_runtime_app_config()
    if not config.rag.enabled:
        raise HTTPException(
            status_code=503,
            detail="RAG 功能未启用，请在 config.toml 中设置 [rag] enabled = true",
        )


@router.get("/authors", response_model=RagAuthorsResponse)
def rag_authors() -> RagAuthorsResponse:
    """Return the list of content creators that have indexed content."""
    _require_rag_enabled()
    store = get_rag_store()
    history_db = get_history_db()

    indexed_ids = store.list_indexed_run_ids()
    all_authors = history_db.list_authors()

    items: list[RagAuthorItem] = []
    for author in all_authors:
        run_ids = history_db.get_run_ids_for_authors([author])
        count = sum(1 for r in run_ids if r in indexed_ids)
        if count > 0:
            items.append(RagAuthorItem(author=author, indexed_run_count=count))

    return RagAuthorsResponse(authors=items)


@router.post("/query-stream")
async def rag_query_stream_post(payload: RagQueryRequest) -> StreamingResponse:
    service = _create_rag_query_service(payload)

    async def serialize_events():
        async for event in service.events():
            yield f"data: {json.dumps(event.payload(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        serialize_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _create_rag_query_service(request: RagQueryRequest) -> RagQueryService:
    config = get_runtime_app_config(
        **request.runtime_config_kwargs(),
    )
    if not config.rag.enabled:
        raise HTTPException(
            status_code=503,
            detail="RAG 功能未启用，请在 config.toml 中设置 [rag] enabled = true",
        )
    return RagQueryService(
        request=request,
        config=config,
        store=get_rag_store(),
        history_db=get_history_db(),
        answer_repository=RagAnswerRepository(get_storage_backend),
        download_store=download_registry.store_content,
    )


@router.post("/query", response_model=RagQueryResponse)
async def rag_query(request: RagQueryRequest) -> RagQueryResponse:
    """Return the terminal result from the shared RAG event sequence."""
    service = _create_rag_query_service(request)
    async for event in service.events():
        if event.stage == "done" and event.result is not None:
            return event.result
        if event.stage == "error":
            raise HTTPException(status_code=500, detail=f"查询失败: {event.message}")
    raise HTTPException(status_code=500, detail="查询失败: 未收到完成事件")


@router.post("/index/{run_id}", response_model=RagIndexResponse)
def rag_index_run(run_id: str, request: RagIndexRequest) -> RagIndexResponse:
    """Index a single run into the RAG store."""
    _require_rag_enabled()
    config = get_runtime_app_config()
    store = get_rag_store()
    history_db = get_history_db()
    storage_backend = get_storage_backend()

    try:
        from b2t.rag.indexer import index_run

        count = index_run(
            run_id=run_id,
            history_db=history_db,
            storage_backend=storage_backend,
            rag_config=config.rag,
            store=store,
            force=request.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("索引 run_id=%s 失败: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=f"索引失败: {exc}") from exc

    return RagIndexResponse(run_id=run_id, chunk_count=count)


@router.post("/index-all", response_model=RagIndexAllResponse)
def rag_index_all(request: RagIndexRequest) -> RagIndexAllResponse:
    """Index all runs in history (synchronous, runs in thread pool)."""
    _require_rag_enabled()
    config = get_runtime_app_config()
    store = get_rag_store()
    history_db = get_history_db()
    storage_backend = get_storage_backend()

    def _do_index_all():
        from b2t.rag.indexer import index_all_runs

        return index_all_runs(
            history_db=history_db,
            storage_backend=storage_backend,
            rag_config=config.rag,
            store=store,
            force=request.force,
        )

    try:
        future = _executor.submit(_do_index_all)
        raw_results = future.result(timeout=600)
    except Exception as exc:
        logger.error("全量索引失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"全量索引失败: {exc}") from exc

    # Convert int values to str for uniform schema
    str_results: dict[str, str] = {}
    succeeded = 0
    failed = 0
    for run_id, value in raw_results.items():
        if isinstance(value, int):
            str_results[run_id] = str(value)
            succeeded += 1
        else:
            str_results[run_id] = str(value)
            failed += 1

    return RagIndexAllResponse(
        results=str_results,
        total_runs=len(raw_results),
        succeeded=succeeded,
        failed=failed,
    )


@router.get("/status", response_model=RagStatusResponse)
def rag_status() -> RagStatusResponse:
    """Return RAG index status."""
    config = get_runtime_app_config()
    if not config.rag.enabled:
        return RagStatusResponse(
            enabled=False,
            total_chunks=0,
            indexed_run_ids=[],
            total_indexed_runs=0,
            total_history_runs=0,
            pending_index_runs=0,
            indexed_items=[],
        )

    store = get_rag_store()
    history_db = get_history_db()
    try:
        total_chunks = store.count()
        raw_indexed_run_ids = sorted(store.list_indexed_run_ids())
        total_history_runs = history_db.count_runs(record_type="transcription")
    except Exception as exc:
        logger.error("获取 RAG 状态失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {exc}") from exc

    from b2t.rag.indexer import select_index_artifact

    indexed_run_ids: list[str] = []
    indexed_items: list[RagIndexedItem] = []
    for run_id in raw_indexed_run_ids:
        detail = history_db.get_run_detail(run_id)
        if detail is None:
            continue
        if getattr(detail, "record_type", "transcription") != "transcription":
            continue
        try:
            target_artifact, preferred_kind = select_index_artifact(detail)
        except ValueError:
            continue
        indexed_run_ids.append(run_id)
        indexed_items.append(
            RagIndexedItem(
                run_id=run_id,
                bvid=detail.bvid,
                title=detail.title,
                author=detail.author,
                source_kind=preferred_kind,
                source_filename=target_artifact.filename,
                chunk_count=store.count_where(where={"run_id": run_id}),
            )
        )

    indexed_items.sort(
        key=lambda item: (item.author or "", item.title or "", item.run_id)
    )
    total_indexed_runs = len(indexed_run_ids)
    return RagStatusResponse(
        enabled=True,
        total_chunks=total_chunks,
        indexed_run_ids=indexed_run_ids,
        total_indexed_runs=total_indexed_runs,
        total_history_runs=total_history_runs,
        pending_index_runs=max(total_history_runs - total_indexed_runs, 0),
        indexed_items=indexed_items,
    )
