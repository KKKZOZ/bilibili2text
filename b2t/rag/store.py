"""ChromaDB vector store wrapper for RAG."""

from __future__ import annotations

import chromadb


class RagStore:
    """Thin wrapper around a ChromaDB persistent collection."""

    def __init__(self, chroma_dir: str, collection_name: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(
        self,
        chunks: list,
        embeddings: list[list[float]],
    ) -> None:
        """Upsert chunks with their embeddings into the collection."""
        if not chunks:
            return

        ids = [chunk.doc_id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "run_id": chunk.run_id,
                "kind": chunk.kind,
                "title": chunk.title,
                "bvid": chunk.bvid,
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunks
        ]

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def count_where(self, where: dict | None = None) -> int:
        """Return document count, optionally filtered by a ChromaDB where clause."""
        if where:
            return len(self._collection.get(where=where, include=[])["ids"])
        return self._collection.count()

    def query(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Query for nearest chunks by embedding.

        Returns a list of dicts with keys: id, document, metadata, distance.
        """
        available = self.count_where(where)
        if available == 0:
            return []
        kwargs: dict = dict(
            query_embeddings=[query_embedding],
            n_results=min(top_k, available),
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where
        results = self._collection.query(**kwargs)

        output: list[dict] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            output.append(
                {
                    "id": doc_id,
                    "document": doc,
                    "metadata": meta,
                    "distance": dist,
                }
            )
        return output

    def delete_run(self, run_id: str) -> None:
        """Delete all chunks belonging to a run."""
        self._collection.delete(where={"run_id": run_id})

    def count(self) -> int:
        """Return total number of documents in the collection."""
        return self._collection.count()

    def list_indexed_run_ids(self) -> set[str]:
        """Return set of run_ids that have at least one chunk indexed."""
        result = self._collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
        return {str(m["run_id"]) for m in metadatas if m and "run_id" in m}
