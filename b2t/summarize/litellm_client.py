"""LiteLLM summarize client helpers."""

import os
from typing import Any

# 禁止 litellm 在每次调用时从 raw.githubusercontent.com 拉取最新模型定价数据（在网络受限环境下
# 这个请求会阻塞 30 秒以上才超时）；改用包内自带的本地定价文件。
# 同时关闭 litellm 默认开启的遥测上报，避免额外出站请求。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
os.environ.setdefault("LITELLM_TELEMETRY", "false")

from litellm import completion

from b2t.config import (
    SummarizeConfig,
    SummarizeModelProfile,
    resolve_summarize_api_base,
)


def _resolve_openrouter_max_tokens(model: str) -> int | None:
    normalized = model.strip().lower()
    if "qwen3-max-thinking" in normalized:
        return 32768
    if "qwen3-max" in normalized:
        return 32768
    return None


def _normalized_model_name(model: str) -> str:
    return model.strip().lower()


def _is_groq_qwen3_model(model: str) -> bool:
    return "qwen3" in _normalized_model_name(model)


def _is_groq_gpt_oss_model(model: str) -> bool:
    return "gpt-oss" in _normalized_model_name(model)


def _to_litellm_model_name(model: str, provider: str) -> str:
    normalized = model.strip()
    if not normalized:
        raise ValueError("模型名不能为空")

    # 统一按目标 provider 显式前缀，避免 LiteLLM 错判 provider。
    if provider == "openrouter":
        if normalized.startswith("openrouter/"):
            return normalized
        return f"openrouter/{normalized}"

    if provider == "bailian":
        if normalized.startswith("dashscope/"):
            return normalized
        return f"dashscope/{normalized}"

    if provider == "groq":
        if normalized.startswith("groq/"):
            return normalized
        return f"groq/{normalized}"

    return normalized


def get_message_field(message: object, field: str) -> object | None:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def to_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                parts.append(str(item))
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def extract_reasoning_text(delta: object) -> str:
    reasoning_content = get_message_field(delta, "reasoning_content")
    reasoning_content_text = to_text(reasoning_content)
    if reasoning_content_text:
        return reasoning_content_text

    reasoning_alias = get_message_field(delta, "reasoning")
    reasoning_alias_text = to_text(reasoning_alias)
    if reasoning_alias_text:
        return reasoning_alias_text

    reasoning_details = get_message_field(delta, "reasoning_details")
    parts: list[str] = []
    if isinstance(reasoning_details, list):
        for item in reasoning_details:
            detail_text = to_text(get_message_field(item, "text"))
            if detail_text:
                if not parts or parts[-1] != detail_text:
                    parts.append(detail_text)
                continue

            summary = get_message_field(item, "summary")
            summary_text = to_text(summary)
            if summary_text:
                if not parts or parts[-1] != summary_text:
                    parts.append(summary_text)

    return "".join(parts)


def collect_stream_result(stream: object) -> tuple[str, str]:
    reasoning_parts: list[str] = []
    content_parts: list[str] = []

    for chunk in stream:
        choices = get_message_field(chunk, "choices")
        if not isinstance(choices, list) or not choices:
            continue

        choice = choices[0]
        delta = get_message_field(choice, "delta")
        if delta is None:
            continue

        reasoning_piece = extract_reasoning_text(delta)
        content_piece = to_text(get_message_field(delta, "content"))

        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
        if content_piece:
            content_parts.append(content_piece)

    return "".join(reasoning_parts), "".join(content_parts)


def _build_extra_body(
    summarize_config: SummarizeConfig,
    model_profile: SummarizeModelProfile,
    selected_model: str,
) -> dict[str, object]:
    provider = model_profile.provider
    if provider == "openrouter":
        if summarize_config.enable_thinking:
            extra_body: dict[str, object] = {
                "reasoning": {"enabled": True},
                "include_reasoning": True,
            }
        else:
            extra_body = {
                "reasoning": {"effort": "none", "exclude": True},
                "include_reasoning": False,
            }

        if model_profile.providers:
            extra_body["provider"] = {"order": list(model_profile.providers)}
        return extra_body

    if provider == "bailian":
        return {"enable_thinking": summarize_config.enable_thinking}

    if provider == "groq":
        # Groq reasoning 参数按模型能力启用：
        # - qwen3: reasoning_effort 支持 none/default/low/medium/high
        # - gpt-oss: reasoning_effort 支持 low/medium/high
        # 非 reasoning 模型（如 llama、kimi）不发送 reasoning 参数，避免 400。
        extra_body: dict[str, object] = {}
        model_name = selected_model
        if _is_groq_qwen3_model(model_name):
            extra_body["include_reasoning"] = summarize_config.enable_thinking
            extra_body["reasoning_effort"] = (
                "default" if summarize_config.enable_thinking else "none"
            )
        elif _is_groq_gpt_oss_model(model_name):
            extra_body["include_reasoning"] = summarize_config.enable_thinking
            extra_body["reasoning_effort"] = (
                "medium" if summarize_config.enable_thinking else "low"
            )
        return extra_body

    return {}


def stream_summary_completion(
    *,
    prompt: str,
    summarize_config: SummarizeConfig,
    model_profile: SummarizeModelProfile,
    model_override: str | None = None,
    include_usage: bool = True,
) -> object:
    selected_model = (model_override or model_profile.model).strip()
    if not selected_model:
        raise ValueError("模型名不能为空")

    kwargs: dict[str, Any] = {
        "model": _to_litellm_model_name(selected_model, model_profile.provider),
        "messages": [{"role": "user", "content": prompt}],
        "api_key": model_profile.api_key,
        "api_base": resolve_summarize_api_base(model_profile),
        "stream": True,
        "extra_body": _build_extra_body(
            summarize_config, model_profile, selected_model
        ),
    }
    if include_usage:
        kwargs["stream_options"] = {"include_usage": True}

    if model_profile.provider == "openrouter":
        max_tokens = _resolve_openrouter_max_tokens(selected_model)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

    try:
        return completion(**kwargs)
    except Exception as exc:
        # 某些 Groq 模型会对 include_reasoning / reasoning_effort 返回不支持错误，
        # 这里做一次自动降级重试，避免整次总结失败。
        if model_profile.provider != "groq":
            raise

        message = str(exc)
        lowered = message.lower()
        extra_body = kwargs.get("extra_body")
        if not isinstance(extra_body, dict):
            raise

        retried = False
        patched_extra_body = dict(extra_body)
        if (
            "include_reasoning" in lowered
            and "not supported" in lowered
            and "include_reasoning" in patched_extra_body
        ):
            patched_extra_body.pop("include_reasoning", None)
            retried = True

        if (
            "reasoning_effort" in lowered
            and "not supported" in lowered
            and "reasoning_effort" in patched_extra_body
        ):
            patched_extra_body.pop("reasoning_effort", None)
            retried = True

        if not retried:
            raise

        kwargs["extra_body"] = patched_extra_body
        return completion(**kwargs)
