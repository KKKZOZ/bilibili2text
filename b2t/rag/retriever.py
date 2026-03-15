"""RAG retrieval and answer generation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

import litellm  # noqa: E402

from b2t.config import RagConfig  # noqa: E402
from b2t.rag.embedder import embed_texts  # noqa: E402
from b2t.rag.store import RagStore  # noqa: E402

_ANSWER_PROMPT_TEMPLATE = """\
你是一个金融行业报告助手。你的任务不是写泛泛的摘要，而是基于检索结果形成一份结构化、信息充分、面向投资研究场景的中文金融报告。

写作要求：
1. 检索出来的关键信息都应尽量体现在最终报告中，不能只挑少量片段泛泛概括。
2. 在使用某个检索片段的信息后，请在对应句末用方括号标注来源编号，例如「公司现金水平较高 [1]」。
3. 在不与检索内容冲突的前提下，你可以结合你已有的通用金融知识，对行业背景、商业模式、估值框架、风险点、催化因素等做必要补充和完善。
4. 如果某些判断主要来自你自身知识而非检索内容，不要伪造引用；应明确区分“检索片段显示”与“结合常识补充”。
5. 输出应尽量组织成一份金融报告，可包含但不限于：公司/主题概览、业务模式、财务与估值、增长驱动、风险因素、结论。
6. 如果检索内容不足以支撑某个结论，请如实说明，不要编造。

[视频内容片段]
{chunks}

[用户问题]
{question}

请用中文回答："""


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
    rag_config: RagConfig,
    store: RagStore,
) -> RagAnswer:
    """Embed question, retrieve top-k chunks, and generate an answer with LLM."""
    # 1. Embed question
    query_embeddings = embed_texts([question], config=rag_config.embedding)
    query_embedding = query_embeddings[0]

    # 2. Retrieve top-k chunks
    raw_results = store.query(query_embedding, top_k=rag_config.top_k)

    sources: list[SourceChunk] = []
    chunk_texts: list[str] = []
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
        chunk_texts.append(result.get("document", ""))

    # 3. Build prompt
    chunks_str = (
        "\n---\n".join(f"[{i + 1}] {t}" for i, t in enumerate(chunk_texts))
        if chunk_texts else "（未检索到相关内容）"
    )
    prompt = _ANSWER_PROMPT_TEMPLATE.format(chunks=chunks_str, question=question)

    # 4. Call LLM
    llm_cfg = rag_config.llm
    provider = llm_cfg.provider.strip().lower()
    model = llm_cfg.model.strip()
    if provider == "bailian":
        model = f"dashscope/{model}"

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        api_key=llm_cfg.api_key.strip() or None,
        api_base=llm_cfg.api_base.strip() or None,
    )
    answer = response.choices[0].message.content or ""

    return RagAnswer(answer=answer, sources=sources, question=question)
