import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import runtime_routes
from backend.schemas import (
    OpenPublicApiKeyTestRequest,
    OpenPublicCustomLlmTestRequest,
)

from b2t.config import (
    AnalyticsConfig,
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    StorageConfig,
    STTConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPresetsConfig,
)


def _app_config() -> AppConfig:
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(),
        summarize=SummarizeConfig(
            profile="bailian-main",
            profiles={
                "bailian-main": SummarizeModelProfile(
                    provider="bailian",
                    model="qwen-plus",
                    api_key="",
                    api_base="https://dashscope.example.com/v1/",
                ),
                "deepseek-main": SummarizeModelProfile(
                    provider="deepseek",
                    model="deepseek-chat",
                    api_key="",
                    api_base="https://deepseek.example.com/",
                ),
            },
        ),
        fancy_html=FancyHtmlConfig(),
        summary_presets=SummaryPresetsConfig(
            default="default",
            presets={},
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        analytics=AnalyticsConfig(),
    )


def test_open_public_custom_llm_test_route_calls_litellm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_routes, "is_open_public_mode", lambda: True)

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )

    monkeypatch.setattr(runtime_routes, "completion", fake_completion)

    response = runtime_routes.test_open_public_custom_llm(
        OpenPublicCustomLlmTestRequest(
            base_url="https://llm.example.com/v1/",
            api_key="sk-custom",
            model="custom-model",
        )
    )

    assert response.ok is True
    assert response.content == "hello"
    assert captured["model"] == "openai/custom-model"
    assert captured["api_base"] == "https://llm.example.com/v1"
    assert captured["api_key"] == "sk-custom"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_open_public_api_key_test_route_calls_bailian_litellm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_routes, "is_open_public_mode", lambda: True)
    monkeypatch.setattr(runtime_routes, "get_app_config", _app_config)

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )

    monkeypatch.setattr(runtime_routes, "completion", fake_completion)

    response = runtime_routes.test_open_public_api_key(
        OpenPublicApiKeyTestRequest(
            provider="alibaba",
            api_key="sk-dashscope",
        )
    )

    assert response.ok is True
    assert response.content == "hello"
    assert captured["model"] == "dashscope/qwen-plus"
    assert captured["api_base"] == "https://dashscope.example.com/v1"
    assert captured["api_key"] == "sk-dashscope"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_open_public_api_key_test_route_calls_deepseek_litellm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_routes, "is_open_public_mode", lambda: True)
    monkeypatch.setattr(runtime_routes, "get_app_config", _app_config)

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )

    monkeypatch.setattr(runtime_routes, "completion", fake_completion)

    response = runtime_routes.test_open_public_api_key(
        OpenPublicApiKeyTestRequest(
            provider="deepseek",
            api_key="sk-deepseek",
        )
    )

    assert response.ok is True
    assert response.content == "hello"
    assert captured["model"] == "deepseek/deepseek-chat"
    assert captured["api_base"] == "https://deepseek.example.com"
    assert captured["api_key"] == "sk-deepseek"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
