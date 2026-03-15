"""Embedding wrapper using litellm."""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

import litellm  # noqa: E402

from b2t.config import RagEmbeddingConfig  # noqa: E402


def _prefix_model(config: RagEmbeddingConfig) -> str:
    """Prefix model name with provider prefix expected by litellm."""
    provider = config.provider.strip().lower()
    model = config.model.strip()
    if provider == "bailian":
        # DashScope exposes an OpenAI-compatible endpoint; use openai/ prefix
        # so litellm routes correctly to the custom api_base.
        return f"openai/{model}"
    return model


def embed_texts(
    texts: list[str],
    *,
    config: RagEmbeddingConfig,
    batch_size: int = 10,
) -> list[list[float]]:
    """Embed a list of texts using the configured provider.

    Returns a list of embedding vectors in the same order as the input texts.
    """
    model = _prefix_model(config)
    api_key = config.api_key.strip() or None
    api_base = config.api_base.strip() or None

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = litellm.embedding(
            model=model,
            input=batch,
            api_key=api_key,
            api_base=api_base,
            encoding_format="float",
        )
        for item in response.data:
            all_embeddings.append(item["embedding"])

    return all_embeddings
