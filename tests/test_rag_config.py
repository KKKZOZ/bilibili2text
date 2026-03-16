from pathlib import Path

import pytest

from b2t.config import (
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    RagConfig,
    STTConfig,
    StorageConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPresetsConfig,
    _load_rag_config,
    resolve_rag_llm_profile,
)


def _app_config(*, summarize_profile: str = "summary-default", rag_llm_profile: str = "") -> AppConfig:
    summarize = SummarizeConfig(
        profile=summarize_profile,
        profiles={
            "summary-default": SummarizeModelProfile(
                provider="bailian",
                model="qwen3-max",
                api_key="k1",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                providers=(),
            ),
            "openrouter-alt": SummarizeModelProfile(
                provider="openrouter",
                model="moonshotai/kimi-k2.5",
                api_key="k2",
                api_base="https://openrouter.ai/api/v1",
                providers=(),
            ),
        },
        enable_thinking=False,
        preset="default",
        presets_file="summary_presets.toml",
    )
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(),
        summarize=summarize,
        fancy_html=FancyHtmlConfig(profile="summary-default"),
        summary_presets=SummaryPresetsConfig(
            default="default",
            presets={},
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(llm_profile=rag_llm_profile),
    )


def test_resolve_rag_llm_profile_prefers_rag_profile_then_summarize_default() -> None:
    config = _app_config(rag_llm_profile="openrouter-alt")
    profile = resolve_rag_llm_profile(config)
    assert profile.model == "moonshotai/kimi-k2.5"

    fallback_config = _app_config()
    fallback_profile = resolve_rag_llm_profile(fallback_config)
    assert fallback_profile.model == "qwen3-max"


def test_load_rag_config_rejects_legacy_llm_block(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rag 包含未知字段: llm"):
        _load_rag_config({"llm": {}}, base_dir=tmp_path)
