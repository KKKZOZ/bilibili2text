"""Runtime mode / feature flags and open-public API key management."""

from fastapi import APIRouter, HTTPException, Query
from litellm import completion

from b2t.config import resolve_summarize_api_base
from b2t.summarize.litellm_client import _to_litellm_model_name
from backend.schemas import (
    OpenPublicApiKeyStatusResponse,
    OpenPublicApiKeyTestRequest,
    OpenPublicApiKeyTestResponse,
    OpenPublicApiKeyUpdateRequest,
    OpenPublicCustomLlmTestRequest,
    OpenPublicCustomLlmTestResponse,
    RuntimeFeaturesResponse,
)
from backend.settings import (
    _pick_bailian_summary_profile,
    _pick_deepseek_summary_profile,
    clear_public_api_key,
    clear_public_deepseek_api_key,
    get_app_config,
    get_public_api_key,
    get_public_deepseek_api_key,
    is_open_public_mode,
    mask_api_key,
    set_public_api_key,
    set_public_deepseek_api_key,
)
from backend.settings import (
    get_runtime_features as get_runtime_feature_flags,
)

router = APIRouter()


def _ensure_open_public_mode() -> None:
    if not is_open_public_mode():
        raise HTTPException(status_code=404, detail="当前并非 open-public 模式")


def _build_api_key_status(provider: str = "alibaba") -> OpenPublicApiKeyStatusResponse:
    if provider == "deepseek":
        api_key = get_public_deepseek_api_key()
    else:
        api_key = get_public_api_key()
    masked = mask_api_key(api_key) if api_key else None
    return OpenPublicApiKeyStatusResponse(
        provider=provider,  # type: ignore[arg-type]
        configured=bool(api_key),
        masked_key=masked,
    )


@router.get("/api/runtime", response_model=RuntimeFeaturesResponse)
def get_runtime_features() -> RuntimeFeaturesResponse:
    return RuntimeFeaturesResponse(**get_runtime_feature_flags())


@router.get(
    "/api/open-public/api-key",
    response_model=OpenPublicApiKeyStatusResponse,
)
def get_open_public_api_key_status(
    provider: str = Query(default="alibaba", description="服务商：alibaba 或 deepseek"),
) -> OpenPublicApiKeyStatusResponse:
    _ensure_open_public_mode()
    return _build_api_key_status(provider)


@router.put(
    "/api/open-public/api-key",
    response_model=OpenPublicApiKeyStatusResponse,
)
def update_open_public_api_key(
    payload: OpenPublicApiKeyUpdateRequest,
) -> OpenPublicApiKeyStatusResponse:
    _ensure_open_public_mode()
    cleaned = payload.api_key.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if payload.provider == "deepseek":
        set_public_deepseek_api_key(cleaned)
    else:
        set_public_api_key(cleaned)
    return _build_api_key_status(payload.provider)


@router.delete(
    "/api/open-public/api-key",
    response_model=OpenPublicApiKeyStatusResponse,
)
def clear_open_public_api_key(
    provider: str = Query(default="alibaba", description="服务商：alibaba 或 deepseek"),
) -> OpenPublicApiKeyStatusResponse:
    _ensure_open_public_mode()
    if provider == "deepseek":
        clear_public_deepseek_api_key()
    else:
        clear_public_api_key()
    return _build_api_key_status(provider)


@router.post(
    "/api/open-public/api-key/test",
    response_model=OpenPublicApiKeyTestResponse,
)
def test_open_public_api_key(
    payload: OpenPublicApiKeyTestRequest,
) -> OpenPublicApiKeyTestResponse:
    _ensure_open_public_mode()
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    app_config = get_app_config()
    if payload.provider == "deepseek":
        profile = _pick_deepseek_summary_profile(app_config.summarize)
    else:
        profile = _pick_bailian_summary_profile(app_config.summarize)

    model = profile.model.strip()
    api_base = resolve_summarize_api_base(profile).rstrip("/")
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if not api_base:
        raise HTTPException(status_code=400, detail="api_base 不能为空")

    try:
        resp = completion(
            model=_to_litellm_model_name(model, profile.provider),
            messages=[{"role": "user", "content": "hi"}],
            api_key=api_key,
            api_base=api_base,
            stream=False,
        )
        content = str(resp.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"测试连接失败：{exc}",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=502,
            detail="测试连接失败：模型返回了空响应",
        )
    return OpenPublicApiKeyTestResponse(ok=True, content=content)


@router.post(
    "/api/open-public/custom-llm/test",
    response_model=OpenPublicCustomLlmTestResponse,
)
def test_open_public_custom_llm(
    payload: OpenPublicCustomLlmTestRequest,
) -> OpenPublicCustomLlmTestResponse:
    _ensure_open_public_mode()
    base_url = payload.base_url.strip().rstrip("/")
    api_key = payload.api_key.strip()
    model = payload.model.strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url 不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="base_url 必须以 http:// 或 https:// 开头",
        )
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    try:
        resp = completion(
            model=_to_litellm_model_name(model, "openai_compatible"),
            messages=[{"role": "user", "content": "hi"}],
            api_key=api_key,
            api_base=base_url,
            stream=False,
        )
        content = str(resp.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"测试连接失败：{exc}",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=502,
            detail="测试连接失败：模型返回了空响应",
        )
    return OpenPublicCustomLlmTestResponse(ok=True, content=content)
