import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.settings import (
    OPEN_PUBLIC_CUSTOM_LLM_PROFILE,
    build_open_public_config,
)

from b2t.config import (
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    RagConfig,
    StorageConfig,
    STTConfig,
    STTProfile,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPresetsConfig,
)


def _config() -> AppConfig:
    stt_profile = STTProfile(
        provider="qwen",
        qwen_model="fun-asr",
        diarization_enabled=True,
        speaker_count=4,
    )
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(
            profile="qwen-main",
            profiles={"qwen-main": stt_profile},
            provider="qwen",
            qwen_model="fun-asr",
            diarization_enabled=True,
            speaker_count=4,
        ),
        summarize=SummarizeConfig(
            profile="bailian-main",
            profiles={
                "bailian-main": SummarizeModelProfile(
                    provider="bailian",
                    model="qwen3-max",
                    api_key="",
                    api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    providers=(),
                ),
                "deepseek-main": SummarizeModelProfile(
                    provider="deepseek",
                    model="deepseek-chat",
                    api_key="",
                    api_base="https://api.deepseek.com",
                    providers=(),
                ),
            },
            preset="default",
            presets_file="summary_presets.toml",
        ),
        fancy_html=FancyHtmlConfig(profile="bailian-main"),
        summary_presets=SummaryPresetsConfig(
            default="default",
            presets={},
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(),
    )


def test_open_public_custom_llm_adds_default_profile_without_changing_stt() -> None:
    config = build_open_public_config(
        _config(),
        api_key="sk-dashscope",
        deepseek_api_key="sk-deepseek",
        custom_llm_base_url="https://llm.example.com/v1/",
        custom_llm_api_key="sk-custom",
        custom_llm_model="custom-model",
    )

    assert config.stt.provider == "qwen"
    assert config.stt.qwen_api_key == "sk-dashscope"
    assert config.stt.diarization_enabled is True
    assert config.stt.speaker_count == 4
    assert config.stt.profiles["open_public_qwen"].diarization_enabled is True
    assert config.stt.profiles["open_public_qwen"].speaker_count == 4
    assert config.summarize.profile == OPEN_PUBLIC_CUSTOM_LLM_PROFILE
    assert config.fancy_html.profile == OPEN_PUBLIC_CUSTOM_LLM_PROFILE
    assert config.rag.llm_profile == OPEN_PUBLIC_CUSTOM_LLM_PROFILE

    profile = config.summarize.profiles[OPEN_PUBLIC_CUSTOM_LLM_PROFILE]
    assert profile.provider == "openai_compatible"
    assert profile.model == "custom-model"
    assert profile.api_key == "sk-custom"
    assert profile.api_base == "https://llm.example.com/v1"


def test_open_public_without_custom_llm_keeps_existing_deepseek_priority() -> None:
    config = build_open_public_config(
        _config(),
        api_key="sk-dashscope",
        deepseek_api_key="sk-deepseek",
    )

    assert config.summarize.profile == "deepseek-main"
    assert OPEN_PUBLIC_CUSTOM_LLM_PROFILE not in config.summarize.profiles
