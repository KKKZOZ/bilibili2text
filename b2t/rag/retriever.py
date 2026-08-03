"""RAG retrieval and answer generation."""

from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

import litellm

from b2t.config import (
    AppConfig,
    resolve_rag_llm_profile,
    resolve_summarize_api_base,
)
from b2t.rag.embedder import embed_texts
from b2t.rag.store import RagStore
from b2t.summarize.litellm_client import _to_litellm_model_name

_ANSWER_PROMPT_TEMPLATE = """\
You are a financial industry report assistant. Your task is not to write a generic summary, but to form a structured, information-rich financial report based on retrieved results.

Writing requirements:
1. Key information from the retrieval should be reflected in the final report as much as possible; do not only pick a few fragments for a general overview.
2. After using information from a retrieved snippet, mark the source number in square brackets at the end of the corresponding sentence, e.g. "The company's cash level is relatively high [1]".
3. As long as it does not conflict with the retrieved content, you may incorporate your existing general financial knowledge to supplement and improve industry background, business models, valuation frameworks, risk points, catalysts, etc.
4. If certain judgments come mainly from your own knowledge rather than the retrieved content, do not fabricate citations; clearly distinguish between "retrieved snippet indicates" and "supplemented based on general knowledge".
5. The output should be organized as a financial report, which may include but is not limited to: company/topic overview, business model, financials and valuation, growth drivers, risk factors, and conclusions.
6. If the retrieved content is insufficient to support a conclusion, state this honestly; do not fabricate.

[Video Content Snippets]
{chunks}

[User Question]
{question}

Please answer in Chinese:"""


@dataclass(frozen=True)
class SourceChunk:
    run_id: str
    title: str
    bvid: str
    text: str
    score: float  # similarity score (1 - distance for cosine)


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    sources: list[SourceChunk]
    question: str


def retrieve_and_answer(
    question: str,
    *,
    config: AppConfig,
    store: RagStore,
    llm_profile_override: str | None = None,
    where: dict | None = None,
) -> RagAnswer:
    """Embed question, retrieve top-k chunks, and generate an answer with LLM."""
    sources = retrieve_sources(question, config=config, store=store, where=where)
    prompt = build_answer_prompt(question, sources)
    profile = resolve_rag_llm_profile(config, override=llm_profile_override)
    answer = generate_answer(prompt, profile)

    return RagAnswer(answer=answer, sources=sources, question=question)


def retrieve_sources(
    question: str,
    *,
    config: AppConfig,
    store: RagStore,
    where: dict | None = None,
) -> list[SourceChunk]:
    """Embed a question and retrieve its closest source chunks."""
    query_embeddings = embed_texts([question], config=config.rag.embedding)
    raw_results = store.query(query_embeddings[0], top_k=config.rag.top_k, where=where)

    sources: list[SourceChunk] = []
    for result in raw_results:
        meta = result.get("metadata") or {}
        distance = result.get("distance", 1.0)
        score = max(0.0, 1.0 - float(distance))
        sources.append(
            SourceChunk(
                run_id=str(meta.get("run_id", "")),
                title=str(meta.get("title", "")),
                bvid=str(meta.get("bvid", "")),
                text=result.get("document", ""),
                score=score,
            )
        )

    return sources


def build_answer_prompt(question: str, sources: list[SourceChunk]) -> str:
    """Build the LLM prompt from a question and retrieved source chunks."""
    chunk_texts = [source.text for source in sources]

    chunks_str = (
        "\n---\n".join(f"[{i + 1}] {t}" for i, t in enumerate(chunk_texts))
        if chunk_texts
        else "(No relevant content retrieved)"
    )
    return _ANSWER_PROMPT_TEMPLATE.format(chunks=chunks_str, question=question)


def generate_answer(prompt: str, profile) -> str:
    """Generate an answer with a resolved summarize-model profile."""
    model = _to_litellm_model_name(profile.model, profile.provider)

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        api_key=profile.api_key.strip() or None,
        api_base=resolve_summarize_api_base(profile) or None,
    )
    return response.choices[0].message.content or ""
