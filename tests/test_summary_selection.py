from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from b2t.config import (  # noqa: E402
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    RagConfig,
    STTConfig,
    StorageConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPreset,
    SummaryPresetsConfig,
)
from backend.services import _resolve_summary_selection  # noqa: E402


def _config() -> AppConfig:
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(),
        summarize=SummarizeConfig(
            profile="qwen3-6-plus",
            profiles={
                "qwen3-6-plus": SummarizeModelProfile(
                    provider="bailian",
                    model="qwen3.6-plus",
                    api_key="dummy",
                    api_base="https://example.com/v1",
                    providers=(),
                )
            },
            preset="financial_timeline_merge",
            presets_file="summary_presets.toml",
        ),
        fancy_html=FancyHtmlConfig(profile="qwen3-6-plus"),
        summary_presets=SummaryPresetsConfig(
            default="financial_timeline_merge",
            presets={
                "financial_timeline_merge": SummaryPreset(
                    label="金融主题",
                    prompt_template="Summarize: {content}",
                )
            },
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(),
    )


def test_custom_summary_preset_metadata_is_preserved() -> None:
    resolved_preset, resolved_profile = _resolve_summary_selection(
        config=_config(),
        has_summary=True,
        summary_preset="__user_custom__",
        summary_profile="qwen3-6-plus",
    )

    assert resolved_preset == "__user_custom__"
    assert resolved_profile == "qwen3-6-plus"
