from pathlib import Path

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
)
import b2t.summarize.fancy_html as fancy_html_module


def _config() -> AppConfig:
    summarize = SummarizeConfig(
        profile="summary-default",
        profiles={
            "summary-default": SummarizeModelProfile(
                provider="openrouter",
                model="qwen/qwen3-max",
                api_key="dummy-test-key",
                api_base="https://example.com/v1",
                providers=(),
            ),
            "fancy-default": SummarizeModelProfile(
                provider="openrouter",
                model="openai/gpt-oss-120b",
                api_key="dummy-test-key",
                api_base="https://example.com/v1",
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
        fancy_html=FancyHtmlConfig(profile="fancy-default"),
        summary_presets=SummaryPresetsConfig(
            default="default",
            presets={},
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(),
    )


def test_sanitize_fragment_strips_scripts_and_inline_styles() -> None:
    raw = """
    <section class="section evil" style="color:red">
      <h2 class="section-title">结论</h2>
      <p onclick="alert(1)">保留正文</p>
      <script>alert(1)</script>
      <div class="callout callout-warning" data-x="1">风险提示</div>
    </section>
    """

    cleaned = fancy_html_module.sanitize_fragment(raw)

    assert '<script>' not in cleaned
    assert 'style=' not in cleaned
    assert 'onclick=' not in cleaned
    assert 'data-x=' not in cleaned
    assert 'evil' not in cleaned
    assert 'class="section"' in cleaned
    assert 'class="callout callout-warning"' in cleaned
    assert '保留正文' in cleaned


def test_generate_fancy_summary_html_writes_wrapped_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "BV1AB411c7mD_demo_summary.md"
    summary_path.write_text("# 核心结论\n\n- 要点一\n- 要点二\n", encoding="utf-8")

    monkeypatch.setattr(
        fancy_html_module,
        "stream_summary_completion",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        fancy_html_module,
        "collect_stream_result",
        lambda stream: (
            "",
            '<section class="hero"><div class="hero-kicker">SUMMARY</div>'
            '<h1 class="hero-title">核心结论</h1>'
            '<p class="hero-dek">要点摘要</p></section>',
        ),
    )

    output_path = fancy_html_module.generate_fancy_summary_html(
        summary_path,
        _config(),
    )

    assert output_path.name == "BV1AB411c7mD_demo_summary_fancy.html"
    content = output_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in content.lower()
    assert 'class="hero-title">核心结论<' in content
    assert "<body>" in content
    assert "@media (max-width: 680px)" in content
    assert "@media (max-width: 420px)" in content
    assert "env(safe-area-inset-top)" in content
    assert "table {\n      width: 100%;\n      border-collapse: collapse;\n      min-width: 560px;" in content


def test_generate_fancy_summary_html_uses_dedicated_fancy_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "BV1AB411c7mD_demo_summary.md"
    summary_path.write_text("# 核心结论\n\n内容。\n", encoding="utf-8")

    captured = {}

    def fake_stream_summary_completion(**kwargs):
        captured["model_profile"] = kwargs["model_profile"]
        captured["summarize_config"] = kwargs["summarize_config"]
        return object()

    monkeypatch.setattr(
        fancy_html_module,
        "stream_summary_completion",
        fake_stream_summary_completion,
    )
    monkeypatch.setattr(
        fancy_html_module,
        "collect_stream_result",
        lambda stream: (
            "",
            '<section class="section"><div class="section-body"><p>内容。</p></div></section>',
        ),
    )

    config = _config()
    fancy_html_module.generate_fancy_summary_html(summary_path, config)

    assert captured["summarize_config"] is config.summarize
    assert captured["model_profile"].model == "openai/gpt-oss-120b"
