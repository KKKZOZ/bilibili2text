"""Configuration endpoints: summary presets and model profiles."""

from fastapi import APIRouter, HTTPException

from b2t.config import (
    resolve_summarize_api_base,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)

from backend.schemas import (
    SummaryPresetItemResponse,
    SummaryPresetListResponse,
    SummaryProfileItemResponse,
    SummaryProfileListResponse,
)
from backend.state import _get_runtime_app_config

router = APIRouter()


@router.get("/api/summary-presets", response_model=SummaryPresetListResponse)
def summary_presets() -> SummaryPresetListResponse:
    try:
        config = _get_runtime_app_config()
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
        SummaryPresetItemResponse(name=name, label=preset.label)
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
        config = _get_runtime_app_config()
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
