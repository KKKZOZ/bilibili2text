"""RAG API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas_rag import (
    RagAuthorItem,
    RagAuthorsResponse,
    RagIndexAllResponse,
    RagIndexedItem,
    RagIndexRequest,
    RagIndexResponse,
    RagQueryRequest,
    RagQueryResponse,
    RagSourceItem,
    RagStatusResponse,
)
from backend.state import (
    _get_app_config,
    _get_history_db,
    _get_rag_store,
    _get_storage_backend,
)

router = APIRouter(prefix="/api/rag", tags=["rag"])
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br />").strip()


def _shanghai_now() -> datetime:
    return datetime.now(tz=_SHANGHAI_TZ)


def _require_rag_enabled() -> None:
    config = _get_app_config()
    if not config.rag.enabled:
        raise HTTPException(
            status_code=503,
            detail="RAG 功能未启用，请在 config.toml 中设置 [rag] enabled = true",
        )


@router.get("/authors", response_model=RagAuthorsResponse)
def rag_authors() -> RagAuthorsResponse:
    """Return UP主 list that have indexed content."""
    _require_rag_enabled()
    store = _get_rag_store()
    history_db = _get_history_db()

    indexed_ids = store.list_indexed_run_ids()
    all_authors = history_db.list_authors()

    items: list[RagAuthorItem] = []
    for author in all_authors:
        run_ids = history_db.get_run_ids_for_authors([author])
        count = sum(1 for r in run_ids if r in indexed_ids)
        if count > 0:
            items.append(RagAuthorItem(author=author, indexed_run_count=count))

    return RagAuthorsResponse(authors=items)


@router.get("/query-stream")
async def rag_query_stream(question: str, filter_authors: str = "", llm_profile: str = "") -> StreamingResponse:
    """Stream RAG query progress as Server-Sent Events."""
    _require_rag_enabled()
    config = _get_app_config()
    store = _get_rag_store()
    history_db = _get_history_db()

    # Build ChromaDB where filter from author list
    where_filter: dict | None = None
    if filter_authors.strip():
        authors = [a.strip() for a in filter_authors.split(",") if a.strip()]
        if authors:
            run_ids = history_db.get_run_ids_for_authors(authors)
            if run_ids:
                where_filter = {"run_id": {"$in": run_ids}}
            else:
                where_filter = {"run_id": {"$in": ["__no_match__"]}}

    async def _generate():
        from b2t.rag.embedder import embed_texts  # noqa: PLC0415
        from b2t.rag.retriever import _ANSWER_PROMPT_TEMPLATE  # noqa: PLC0415
        import litellm  # noqa: PLC0415

        def _sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            yield _sse({"stage": "embedding", "message": "正在向量化问题…"})

            query_embeddings = await asyncio.to_thread(
                embed_texts, [question], config=config.rag.embedding
            )
            query_embedding = query_embeddings[0]

            yield _sse({"stage": "retrieving", "message": "正在向量数据库检索…"})

            raw_results = await asyncio.to_thread(
                lambda: store.query(
                    query_embedding, top_k=config.rag.top_k, where=where_filter
                )
            )

            sources = []
            chunk_texts = []
            for result in raw_results:
                meta = result.get("metadata") or {}
                distance = result.get("distance", 1.0)
                score = max(0.0, 1.0 - float(distance))
                sources.append({
                    "run_id": str(meta.get("run_id", "")),
                    "title": str(meta.get("title", "")),
                    "bvid": str(meta.get("bvid", "")),
                    "text": result.get("document", "")[:500],
                    "score": score,
                })
                chunk_texts.append(result.get("document", ""))

            yield _sse({
                "stage": "retrieved",
                "sources": sources,
                "message": f"找到 {len(sources)} 个相关片段，正在生成回答…",
            })

            chunks_str = (
                "\n---\n".join(f"[{i + 1}] {t}" for i, t in enumerate(chunk_texts))
                if chunk_texts else "（未检索到相关内容）"
            )
            prompt = _ANSWER_PROMPT_TEMPLATE.format(chunks=chunks_str, question=question)

            from b2t.config import resolve_rag_llm_profile, resolve_summarize_api_base  # noqa: PLC0415
            from b2t.summarize.litellm_client import _to_litellm_model_name  # noqa: PLC0415

            profile = resolve_rag_llm_profile(config, override=llm_profile.strip())
            llm_model = _to_litellm_model_name(profile.model, profile.provider)
            llm_api_key = profile.api_key or None
            llm_api_base = resolve_summarize_api_base(profile) or None

            def _call_llm():
                resp = litellm.completion(
                    model=llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    api_key=llm_api_key,
                    api_base=llm_api_base,
                )
                return resp.choices[0].message.content or ""

            answer = await asyncio.to_thread(_call_llm)

            # Build markdown content for download / history
            query_time = _shanghai_now()
            now_str = query_time.strftime("%Y%m%d_%H%M%S")
            safe_q = "".join(c if c.isalnum() or c in "-_" else "_" for c in question[:40])
            answer_filename = f"rag_{now_str}_{safe_q}.md"

            if sources:
                source_rows = [
                    "| 编号 | 标题 | BV号 | 相关度 |",
                    "| --- | --- | --- | --- |",
                ]
                for i, source in enumerate(sources, 1):
                    source_rows.append(
                        "| "
                        f"{i} | "
                        f"{_escape_markdown_table_cell(source['title'] or source['bvid'] or '未知')} | "
                        f"{_escape_markdown_table_cell(source['bvid'] or '-')} | "
                        f"{round(source['score'] * 100)}% |"
                    )
                sources_md = "\n".join(source_rows)
            else:
                sources_md = "（无参考来源）"

            answer_md = (
                f"# 知识库查询\n\n"
                f"**问题：** {question}\n\n"
                f"**查询时间：** {query_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"## AI 回答\n\n{answer}\n\n"
                f"## 参考来源\n\n{sources_md}\n"
            )
            answer_bytes = answer_md.encode("utf-8")

            # Register in-memory download
            from backend.downloads import _store_content_download  # noqa: PLC0415
            download_id = await asyncio.to_thread(
                _store_content_download, answer_bytes, answer_filename
            )

            # Persist to storage and record in history (best-effort)
            try:
                import tempfile  # noqa: PLC0415
                from pathlib import Path  # noqa: PLC0415
                from b2t.history import HistoryArtifact, record_rag_query  # noqa: PLC0415
                from backend.state import _get_storage_backend  # noqa: PLC0415

                def _persist():
                    storage = _get_storage_backend()
                    with tempfile.NamedTemporaryFile(
                        suffix=".md", delete=False, prefix="rag_answer_"
                    ) as tmp:
                        tmp.write(answer_bytes)
                        tmp_path = Path(tmp.name)
                    try:
                        from uuid import uuid4  # noqa: PLC0415
                        artifact = storage.store_file(
                            tmp_path,
                            object_key=f"rag_answers/{uuid4().hex}/{answer_filename}",
                        )
                    finally:
                        tmp_path.unlink(missing_ok=True)
                    record_rag_query(
                        db=history_db,
                        question=question,
                        answer_artifact=HistoryArtifact(
                            kind="rag_answer",
                            filename=answer_filename,
                            storage_key=artifact.storage_key,
                            backend=artifact.backend,
                        ),
                    )

                await asyncio.to_thread(_persist)
            except Exception as persist_exc:
                logger.warning("RAG 答案持久化失败（不影响下载）: %s", persist_exc)

            yield _sse({"stage": "done", "answer": answer, "sources": sources, "download_id": download_id, "filename": answer_filename})

        except Exception as exc:
            logger.error("RAG 流式查询失败: %s", exc)
            yield _sse({"stage": "error", "message": str(exc)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/query", response_model=RagQueryResponse)
def rag_query(request: RagQueryRequest) -> RagQueryResponse:
    """Answer a question using RAG over indexed video transcripts."""
    _require_rag_enabled()
    config = _get_app_config()
    store = _get_rag_store()

    try:
        from b2t.rag.retriever import retrieve_and_answer
        result = retrieve_and_answer(
            request.question,
            config=config,
            store=store,
        )
    except Exception as exc:
        logger.error("RAG 查询失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    sources = [
        RagSourceItem(
            run_id=src.run_id,
            title=src.title,
            bvid=src.bvid,
            text=src.text[:500],
            score=src.score,
        )
        for src in result.sources
    ]
    return RagQueryResponse(
        answer=result.answer,
        sources=sources,
        question=result.question,
    )


@router.post("/index/{run_id}", response_model=RagIndexResponse)
def rag_index_run(run_id: str, request: RagIndexRequest) -> RagIndexResponse:
    """Index a single run into the RAG store."""
    _require_rag_enabled()
    config = _get_app_config()
    store = _get_rag_store()
    history_db = _get_history_db()
    storage_backend = _get_storage_backend()

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
    config = _get_app_config()
    store = _get_rag_store()
    history_db = _get_history_db()
    storage_backend = _get_storage_backend()

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
    config = _get_app_config()
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

    store = _get_rag_store()
    history_db = _get_history_db()
    try:
        total_chunks = store.count()
        raw_indexed_run_ids = sorted(store.list_indexed_run_ids())
        total_history_runs = history_db.count_runs(record_type="transcription")
    except Exception as exc:
        logger.error("获取 RAG 状态失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {exc}") from exc

    from b2t.rag.indexer import select_index_artifact  # noqa: PLC0415

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

    indexed_items.sort(key=lambda item: (item.author or "", item.title or "", item.run_id))
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
