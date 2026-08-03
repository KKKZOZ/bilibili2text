"""Shared RAG query execution and stage events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from b2t.config import resolve_rag_llm_profile
from b2t.rag.embedder import embed_texts
from b2t.rag.retriever import SourceChunk, build_answer_prompt, generate_answer
from backend.rag_answer_repository import RagAnswerRepository
from backend.schemas_rag import RagQueryRequest, RagQueryResponse, RagSourceItem

logger = logging.getLogger(__name__)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RagQueryEvent:
    """One observable stage in RAG query execution."""

    stage: str
    message: str | None = None
    sources: list[RagSourceItem] | None = None
    result: RagQueryResponse | None = None
    download_id: str | None = None
    filename: str | None = None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"stage": self.stage}
        if self.message is not None:
            payload["message"] = self.message
        if self.sources is not None:
            payload["sources"] = [source.model_dump() for source in self.sources]
        if self.result is not None:
            payload["answer"] = self.result.answer
        if self.download_id is not None:
            payload["download_id"] = self.download_id
        if self.filename is not None:
            payload["filename"] = self.filename
        return payload


class RagQueryService:
    """Execute normal and streamed RAG queries through one event sequence."""

    def __init__(
        self,
        *,
        request: RagQueryRequest,
        config: Any,
        store: Any,
        history_db: Any,
        answer_repository: RagAnswerRepository,
        download_store: Callable[[bytes, str], str],
    ) -> None:
        self._request = request
        self._config = config
        self._store = store
        self._history_db = history_db
        self._answer_repository = answer_repository
        self._download_store = download_store

    async def events(self) -> AsyncIterator[RagQueryEvent]:
        """Yield progress, terminal success, or terminal error events."""
        try:
            question = self._request.question
            where_filter = self._author_filter()

            yield RagQueryEvent(stage="embedding", message="正在向量化问题…")
            query_embedding = (
                await asyncio.to_thread(
                    embed_texts, [question], config=self._config.rag.embedding
                )
            )[0]

            yield RagQueryEvent(stage="retrieving", message="正在向量数据库检索…")
            raw_results = await asyncio.to_thread(
                self._store.query,
                query_embedding,
                top_k=self._config.rag.top_k,
                where=where_filter,
            )
            sources = self._shape_sources(raw_results)
            source_chunks = self._source_chunks(raw_results)
            yield RagQueryEvent(
                stage="retrieved",
                sources=sources,
                message=f"找到 {len(sources)} 个相关片段，正在生成回答…",
            )

            prompt = build_answer_prompt(question, source_chunks)
            profile = resolve_rag_llm_profile(
                self._config, override=(self._request.llm_profile or "").strip()
            )
            answer = await asyncio.to_thread(generate_answer, prompt, profile)
            result = RagQueryResponse(
                answer=answer,
                sources=sources,
                question=question,
            )
            filename, answer_bytes = self._build_answer_artifact(result)
            download_id = await asyncio.to_thread(
                self._download_store, answer_bytes, filename
            )

            try:
                await asyncio.to_thread(
                    self._answer_repository.persist,
                    history_db=self._history_db,
                    question=question,
                    answer_bytes=answer_bytes,
                    filename=filename,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG 答案持久化失败（不影响回答）: %s", exc)

            yield RagQueryEvent(
                stage="done",
                result=result,
                sources=sources,
                download_id=download_id,
                filename=filename,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("RAG 查询失败: %s", exc)
            yield RagQueryEvent(stage="error", message=str(exc))

    def _author_filter(self) -> dict[str, dict[str, list[str]]] | None:
        authors = [
            author.strip() for author in self._request.filter_authors if author.strip()
        ]
        if not authors:
            return None
        run_ids = self._history_db.get_run_ids_for_authors(authors)
        return {"run_id": {"$in": run_ids or ["__no_match__"]}}

    @staticmethod
    def _shape_sources(raw_results: list[dict[str, Any]]) -> list[RagSourceItem]:
        sources: list[RagSourceItem] = []
        for result in raw_results:
            metadata = result.get("metadata") or {}
            sources.append(
                RagSourceItem(
                    run_id=str(metadata.get("run_id", "")),
                    title=str(metadata.get("title", "")),
                    bvid=str(metadata.get("bvid", "")),
                    text=str(result.get("document", ""))[:500],
                    score=max(0.0, 1.0 - float(result.get("distance", 1.0))),
                )
            )
        return sources

    @staticmethod
    def _source_chunks(raw_results: list[dict[str, Any]]) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        for result in raw_results:
            metadata = result.get("metadata") or {}
            chunks.append(
                SourceChunk(
                    run_id=str(metadata.get("run_id", "")),
                    title=str(metadata.get("title", "")),
                    bvid=str(metadata.get("bvid", "")),
                    text=str(result.get("document", "")),
                    score=max(0.0, 1.0 - float(result.get("distance", 1.0))),
                )
            )
        return chunks

    @staticmethod
    def _build_answer_artifact(result: RagQueryResponse) -> tuple[str, bytes]:
        query_time = datetime.now(tz=_SHANGHAI_TZ)
        safe_question = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in result.question[:40]
        )
        filename = f"rag_{query_time.strftime('%Y%m%d_%H%M%S')}_{safe_question}.md"
        if result.sources:
            rows = ["| 编号 | 标题 | BV号 | 相关度 |", "| --- | --- | --- | --- |"]
            for index, source in enumerate(result.sources, 1):
                rows.append(
                    "| "
                    f"{index} | "
                    f"{_escape_markdown_table_cell(source.title or source.bvid or '未知')} | "
                    f"{_escape_markdown_table_cell(source.bvid or '-')} | "
                    f"{round(source.score * 100)}% |"
                )
            sources_markdown = "\n".join(rows)
        else:
            sources_markdown = "（无参考来源）"
        content = (
            f"# 知识库查询\n\n"
            f"**问题：** {result.question}\n\n"
            f"**查询时间：** {query_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"## AI 回答\n\n{result.answer}\n\n"
            f"## 参考来源\n\n{sources_markdown}\n"
        )
        return filename, content.encode("utf-8")


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br />").strip()
