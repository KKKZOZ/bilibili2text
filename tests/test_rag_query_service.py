import asyncio
import json
import sys
from pathlib import Path

import pytest
from backend.rag_answer_repository import RagAnswerRepository

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.rag_query import RagQueryService
from backend.routes import rag
from backend.schemas_rag import RagQueryRequest

from b2t.config import (
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    RagConfig,
    StorageConfig,
    STTConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPresetsConfig,
)
from b2t.storage import StoredArtifact


def _config() -> AppConfig:
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(),
        summarize=SummarizeConfig(
            profile="default",
            profiles={
                "default": SummarizeModelProfile(
                    provider="bailian",
                    model="default-model",
                    api_key="default-key",
                ),
                "alternate": SummarizeModelProfile(
                    provider="openrouter",
                    model="alternate-model",
                    api_key="alternate-key",
                ),
            },
        ),
        fancy_html=FancyHtmlConfig(profile="default"),
        summary_presets=SummaryPresetsConfig(
            default="default",
            presets={},
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(enabled=True),
    )


class _History:
    def __init__(self) -> None:
        self.author_queries: list[list[str]] = []

    def get_run_ids_for_authors(self, authors: list[str]) -> list[str]:
        self.author_queries.append(authors)
        return ["run-author-a"]


class _Store:
    def __init__(self) -> None:
        self.queries: list[dict] = []

    def query(self, embedding, *, top_k: int, where: dict | None):
        self.queries.append({"embedding": embedding, "top_k": top_k, "where": where})
        return [
            {
                "document": "relevant transcript",
                "metadata": {
                    "run_id": "run-author-a",
                    "title": "Video title",
                    "bvid": "BV1test",
                },
                "distance": 0.2,
            }
        ]


class _Repository:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def persist(self, **kwargs) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


async def _events(service: RagQueryService):
    return [event async for event in service.events()]


async def _stream_payloads(response):
    chunks = [chunk async for chunk in response.body_iterator]
    return [
        json.loads(
            (chunk.decode() if isinstance(chunk, bytes) else chunk)
            .removeprefix("data: ")
            .strip()
        )
        for chunk in chunks
    ]


def test_normal_and_streaming_queries_share_author_filter_and_profile(
    monkeypatch,
) -> None:
    history = _History()
    store = _Store()
    repository = _Repository()
    profile_models: list[str] = []

    monkeypatch.setattr(
        "backend.rag_query.embed_texts", lambda *args, **kwargs: [[1.0]]
    )

    def fake_generate_answer(prompt, profile) -> str:
        profile_models.append(profile.model)
        assert "relevant transcript" in prompt
        return "shared answer"

    monkeypatch.setattr("backend.rag_query.generate_answer", fake_generate_answer)

    def make_service(request: RagQueryRequest) -> RagQueryService:
        return RagQueryService(
            request=request,
            config=_config(),
            store=store,
            history_db=history,
            answer_repository=repository,
            download_store=lambda content, filename: "download-id",
        )

    monkeypatch.setattr(rag, "_create_rag_query_service", make_service)
    request = RagQueryRequest(
        question="What changed?",
        filter_authors=[" author-a "],
        llm_profile="alternate",
    )

    normal = asyncio.run(rag.rag_query(request))
    stream_response = asyncio.run(rag.rag_query_stream_post(request))
    streamed = asyncio.run(_stream_payloads(stream_response))

    assert normal.answer == "shared answer"
    assert streamed[-1]["stage"] == "done"
    assert streamed[-1]["answer"] == normal.answer
    assert streamed[-1]["sources"] == [source.model_dump() for source in normal.sources]
    assert history.author_queries == [["author-a"], ["author-a"]]
    assert [query["where"] for query in store.queries] == [
        {"run_id": {"$in": ["run-author-a"]}},
        {"run_id": {"$in": ["run-author-a"]}},
    ]
    assert profile_models == ["alternate-model", "alternate-model"]
    assert repository.calls == 2


def test_query_events_are_ordered_and_end_in_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.rag_query.embed_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("embedding failed")),
    )
    service = RagQueryService(
        request=RagQueryRequest(question="question"),
        config=_config(),
        store=_Store(),
        history_db=_History(),
        answer_repository=_Repository(),
        download_store=lambda content, filename: "download-id",
    )

    events = asyncio.run(_events(service))

    assert [event.stage for event in events] == ["embedding", "error"]
    assert events[-1].message == "embedding failed"


def test_persistence_failure_does_not_replace_the_done_event(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.rag_query.embed_texts", lambda *args, **kwargs: [[1.0]]
    )
    monkeypatch.setattr(
        "backend.rag_query.generate_answer", lambda prompt, profile: "answer"
    )
    repository = _Repository(error=OSError("storage unavailable"))
    service = RagQueryService(
        request=RagQueryRequest(question="question"),
        config=_config(),
        store=_Store(),
        history_db=_History(),
        answer_repository=repository,
        download_store=lambda content, filename: "download-id",
    )

    events = asyncio.run(_events(service))

    assert [event.stage for event in events] == [
        "embedding",
        "retrieving",
        "retrieved",
        "done",
    ]
    assert events[-1].result is not None
    assert events[-1].result.answer == "answer"
    assert repository.calls == 1


def test_query_stream_has_no_get_route() -> None:
    query_stream_methods = [
        route.methods
        for route in rag.router.routes
        if route.path == "/api/rag/query-stream"
    ]

    assert query_stream_methods == [{"POST"}]


def test_rag_answer_repository_removes_object_when_history_write_fails(
    monkeypatch,
) -> None:
    deleted: list[str] = []

    class FakeStorage:
        def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
            return StoredArtifact(
                filename=local_path.name,
                storage_key=object_key,
                backend="memory",
            )

        def delete_file(self, storage_key: str) -> None:
            deleted.append(storage_key)

    monkeypatch.setattr(
        "backend.rag_answer_repository.record_rag_query",
        lambda **kwargs: (_ for _ in ()).throw(OSError("database unavailable")),
    )
    repository = RagAnswerRepository(FakeStorage)

    with pytest.raises(OSError, match="database unavailable"):
        repository.persist(
            history_db=object(),
            question="question",
            answer_bytes=b"answer",
            filename="rag_answer.md",
        )

    assert len(deleted) == 1
    assert deleted[0].endswith("/rag_answer.md")
