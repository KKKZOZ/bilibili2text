"""Pydantic schemas for RAG endpoints."""

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    filter_authors: list[str] = Field(default_factory=list)
    llm_profile: str | None = None
    api_key: str | None = None
    deepseek_api_key: str | None = None


class RagSourceItem(BaseModel):
    run_id: str
    title: str
    bvid: str
    text: str
    score: float


class RagQueryResponse(BaseModel):
    answer: str
    sources: list[RagSourceItem]
    question: str


class RagIndexRequest(BaseModel):
    force: bool = False


class RagIndexResponse(BaseModel):
    run_id: str
    chunk_count: int


class RagIndexAllResponse(BaseModel):
    results: dict[str, str]
    total_runs: int
    succeeded: int
    failed: int


class RagIndexedItem(BaseModel):
    run_id: str
    bvid: str
    title: str
    author: str
    source_kind: str
    source_filename: str
    chunk_count: int


class RagStatusResponse(BaseModel):
    enabled: bool
    total_chunks: int
    indexed_run_ids: list[str]
    total_indexed_runs: int
    total_history_runs: int
    pending_index_runs: int
    indexed_items: list[RagIndexedItem]


class RagAuthorItem(BaseModel):
    author: str
    indexed_run_count: int


class RagAuthorsResponse(BaseModel):
    authors: list[RagAuthorItem]
