"""Index pipeline run artifacts into the RAG store."""

from __future__ import annotations

import logging

from b2t.config import RagConfig
from b2t.rag.chunker import chunk_markdown
from b2t.rag.embedder import embed_texts
from b2t.rag.store import RagStore

logger = logging.getLogger(__name__)


def select_index_artifact(detail) -> tuple[object, str]:
    """Pick the artifact used for indexing: summary first, markdown fallback."""
    for kind in ("summary", "markdown"):
        for artifact in detail.artifacts:
            if artifact.kind == kind:
                return artifact, kind
    raise ValueError(
        f"run_id={detail.run_id} has no indexable markdown or summary file"
    )


def index_run(
    *,
    run_id: str,
    history_db,
    storage_backend,
    rag_config: RagConfig,
    store: RagStore,
    force: bool = False,
) -> int:
    """Index a single run into the RAG store.

    Returns the number of chunks indexed.
    """
    detail = history_db.get_run_detail(run_id)
    if detail is None:
        raise ValueError(f"run_id={run_id} does not exist in history database")

    target_artifact, preferred_kind = select_index_artifact(detail)

    if force:
        store.delete_run(run_id)

    with storage_backend.open_stream(target_artifact.storage_key) as stream:
        content = stream.read().decode("utf-8", errors="replace")

    chunks = chunk_markdown(
        content,
        run_id=run_id,
        kind=preferred_kind,
        title=detail.title or detail.bvid,
        bvid=detail.bvid,
        chunk_size=rag_config.chunk_size,
        chunk_overlap=rag_config.chunk_overlap,
    )

    if not chunks:
        logger.warning(
            "run_id=%s resulted in 0 chunks after splitting, skipping indexing", run_id
        )
        return 0

    texts = [chunk.text for chunk in chunks]
    embeddings = embed_texts(texts, config=rag_config.embedding)
    store.upsert_chunks(chunks, embeddings)

    logger.info("run_id=%s indexing complete, %d chunks total", run_id, len(chunks))
    return len(chunks)


def index_all_runs(
    *,
    history_db,
    storage_backend,
    rag_config: RagConfig,
    store: RagStore,
    force: bool = False,
) -> dict[str, int | str]:
    """Index all runs in history. Returns dict mapping run_id → chunk count or error string."""
    results: dict[str, int | str] = {}

    page = 1
    page_size = 50
    while True:
        page_result = history_db.list_runs(page=page, page_size=page_size)
        for item in page_result.items:
            try:
                count = index_run(
                    run_id=item.run_id,
                    history_db=history_db,
                    storage_backend=storage_backend,
                    rag_config=rag_config,
                    store=store,
                    force=force,
                )
                results[item.run_id] = count
            except Exception as exc:
                logger.warning("Indexing run_id=%s failed: %s", item.run_id, exc)
                results[item.run_id] = str(exc)

        if not page_result.has_more:
            break
        page += 1

    return results
