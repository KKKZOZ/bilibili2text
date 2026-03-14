"""Runtime mode / feature flags and open-public API key management."""

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    OpenPublicApiKeyStatusResponse,
    OpenPublicApiKeyUpdateRequest,
    RuntimeFeaturesResponse,
)
from backend.state import (
    _clear_public_api_key,
    _get_public_api_key,
    _get_runtime_features,
    _is_open_public_mode,
    _mask_api_key,
    _set_public_api_key,
)

router = APIRouter()


def _ensure_open_public_mode() -> None:
    if not _is_open_public_mode():
        raise HTTPException(status_code=404, detail="当前并非 open-public 模式")


def _build_api_key_status() -> OpenPublicApiKeyStatusResponse:
    api_key = _get_public_api_key()
    masked = _mask_api_key(api_key) if api_key else None
    return OpenPublicApiKeyStatusResponse(
        configured=bool(api_key),
        masked_key=masked,
    )


@router.get("/api/runtime", response_model=RuntimeFeaturesResponse)
def get_runtime_features() -> RuntimeFeaturesResponse:
    return RuntimeFeaturesResponse(**_get_runtime_features())


@router.get(
    "/api/open-public/api-key",
    response_model=OpenPublicApiKeyStatusResponse,
)
def get_open_public_api_key_status() -> OpenPublicApiKeyStatusResponse:
    _ensure_open_public_mode()
    return _build_api_key_status()


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
    _set_public_api_key(cleaned)
    return _build_api_key_status()


@router.delete(
    "/api/open-public/api-key",
    response_model=OpenPublicApiKeyStatusResponse,
)
def clear_open_public_api_key() -> OpenPublicApiKeyStatusResponse:
    _ensure_open_public_mode()
    _clear_public_api_key()
    return _build_api_key_status()
