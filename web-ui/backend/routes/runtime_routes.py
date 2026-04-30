"""Runtime mode / feature flags and open-public API key management."""

from fastapi import APIRouter, HTTPException, Query

from backend.schemas import (
    OpenPublicApiKeyStatusResponse,
    OpenPublicApiKeyUpdateRequest,
    RuntimeFeaturesResponse,
)
from backend.settings import (
    clear_public_api_key,
    clear_public_deepseek_api_key,
    get_public_api_key,
    get_public_deepseek_api_key,
    get_runtime_features as get_runtime_feature_flags,
    is_open_public_mode,
    mask_api_key,
    set_public_api_key,
    set_public_deepseek_api_key,
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
