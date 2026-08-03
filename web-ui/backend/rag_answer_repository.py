"""Persistence boundary for completed RAG answers."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from b2t.history import HistoryArtifact, record_rag_query

logger = logging.getLogger(__name__)


class RagAnswerRepository:
    """Store a RAG answer artifact and record its history row."""

    def __init__(self, storage_backend_factory: Callable[[], Any]) -> None:
        self._storage_backend_factory = storage_backend_factory

    def persist(
        self,
        *,
        history_db: Any,
        question: str,
        answer_bytes: bytes,
        filename: str,
    ) -> None:
        tmp_path: Path | None = None
        storage = self._storage_backend_factory()
        artifact = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".md", delete=False, prefix="rag_answer_"
            ) as tmp:
                tmp.write(answer_bytes)
                tmp_path = Path(tmp.name)

            artifact = storage.store_file(
                tmp_path,
                object_key=f"rag_answers/{uuid4().hex}/{filename}",
            )
            record_rag_query(
                db=history_db,
                question=question,
                answer_artifact=HistoryArtifact(
                    kind="rag_answer",
                    filename=filename,
                    storage_key=artifact.storage_key,
                    backend=artifact.backend,
                ),
            )
        except Exception:
            if artifact is not None:
                try:
                    storage.delete_file(artifact.storage_key)
                except Exception as cleanup_exc:  # noqa: BLE001
                    logger.warning(
                        "清理未归档的 RAG 答案失败: %s: %s",
                        artifact.storage_key,
                        cleanup_exc,
                    )
            raise
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
