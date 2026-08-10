"""Configuration endpoints: summary presets and model profiles."""

from fastapi import APIRouter, HTTPException

from b2t.config import (
    resolve_summarize_api_base,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from backend.schemas import (
    STTProfileItemResponse,
    STTProfileListResponse,
    SummaryPresetItemResponse,
    SummaryPresetListResponse,
    SummaryProfileItemResponse,
    SummaryProfileListResponse,
)
from backend.settings import get_runtime_app_config

router = APIRouter()


@router.get("/api/summary-presets", response_model=SummaryPresetListResponse)
def summary_presets() -> SummaryPresetListResponse:
    try:
        config = get_runtime_app_config()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None

    try:
        selected = resolve_summary_preset_name(
            summarize=config.summarize,
            summary_presets=config.summary_presets,
            override=config.summarize.preset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    presets = [
        SummaryPresetItemResponse(
            name=name,
            label=preset.label,
            prompt_template=preset.prompt_template,
        )
        for name, preset in config.summary_presets.presets.items()
    ]

    return SummaryPresetListResponse(
        default_preset=config.summary_presets.default,
        selected_preset=selected,
        presets=presets,
    )


@router.get("/api/summarize-profiles", response_model=SummaryProfileListResponse)
def summarize_profiles() -> SummaryProfileListResponse:
    try:
        config = get_runtime_app_config()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None

    try:
        resolve_summarize_model_profile(config.summarize)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    profiles = [
        SummaryProfileItemResponse(
            name=name,
            provider=profile.provider,
            model=profile.model,
            api_base=resolve_summarize_api_base(profile),
        )
        for name, profile in config.summarize.profiles.items()
    ]
    return SummaryProfileListResponse(
        default_profile=config.summarize.profile,
        selected_profile=config.summarize.profile,
        profiles=profiles,
    )


def _stt_profile_model(profile) -> str:
    """Extract the model name from an STTProfile based on its provider."""
    provider = profile.provider.strip().lower()
    if provider == "qwen":
        return profile.qwen_model
    if provider == "groq":
        return profile.groq_model
    return profile.volc_resource_id  # volc


def _stt_profile_has_api_key(profile) -> bool:
    """Check whether an STTProfile has a usable API key for its provider."""
    provider = profile.provider.strip().lower()
    if provider == "qwen":
        return bool(profile.qwen_api_key.strip())
    if provider == "groq":
        return bool(profile.groq_api_key.strip())
    if provider == "volc":
        return bool(profile.volc_api_key.strip())
    return False


_DEFAULT_STT_PROFILE_NAMES = {"qwen", "groq", "volc"}


@router.get("/api/stt-profiles", response_model=STTProfileListResponse)
def stt_profiles() -> STTProfileListResponse:
    try:
        config = get_runtime_app_config()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None

    profiles = [
        STTProfileItemResponse(
            name=name,
            provider=profile.provider,
            model=_stt_profile_model(profile),
            language=profile.language,
        )
        for name, profile in config.stt.profiles.items()
        # Hide bare default profiles that have no API key configured.
        if not (
            name in _DEFAULT_STT_PROFILE_NAMES
            and not _stt_profile_has_api_key(profile)
        )
    ]
    return STTProfileListResponse(
        default_profile=config.stt.profile,
        selected_profile=config.stt.profile,
        profiles=profiles,
    )
