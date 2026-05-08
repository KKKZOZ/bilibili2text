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
    SummaryPresetsConfig,
    SummaryPreset,
)
from b2t.history import HistoryArtifact, HistoryDetail  # noqa: E402
from b2t.storage.base import StoredArtifact  # noqa: E402
from backend.existing_transcriptions import ExistingTranscriptionService  # noqa: E402


def _config() -> AppConfig:
    summarize = SummarizeConfig(
        profile="qwen3-5-plus",
        profiles={
            "qwen3-5-plus": SummarizeModelProfile(
                provider="bailian",
                model="qwen3.5-plus",
                api_key="dummy-test-key",
                api_base="https://example.com/v1",
                providers=(),
            )
        },
        enable_thinking=False,
        preset="financial_timeline_merge",
        presets_file="summary_presets.toml",
    )
    return AppConfig(
        download=DownloadConfig(),
        storage=StorageConfig(),
        stt=STTConfig(),
        summarize=summarize,
        fancy_html=FancyHtmlConfig(profile="qwen3-5-plus"),
        summary_presets=SummaryPresetsConfig(
            default="financial_timeline_merge",
            presets={
                "financial_timeline_merge": SummaryPreset(
                    label="金融时间线主题归并",
                    prompt_template="Summarize: {content}",
                )
            },
            source_path=Path("summary_presets.toml"),
        ),
        converter=ConverterConfig(),
        rag=RagConfig(),
    )


def test_existing_transcription_reuses_same_summary_config_without_regenerating(
    monkeypatch,
) -> None:
    service = ExistingTranscriptionService()
    config = _config()
    markdown = StoredArtifact(
        filename="BV1bLdgBEEKu_demo_transcription.md",
        storage_key="b2t/BV1bLdgBEEKu-11111111/BV1bLdgBEEKu_demo_transcription.md",
        backend="minio",
    )
    json_artifact = StoredArtifact(
        filename="BV1bLdgBEEKu_demo_transcription.json",
        storage_key="b2t/BV1bLdgBEEKu-11111111/BV1bLdgBEEKu_demo_transcription.json",
        backend="minio",
    )
    existing_results = {
        "markdown": markdown,
        "json": json_artifact,
    }

    class FakeStorage:
        def find_existing_transcription(self, bvid: str):
            return existing_results

    detail = HistoryDetail(
        run_id="BV1bLdgBEEKu-11111111",
        bvid="BV1bLdgBEEKu",
        title="demo",
        author="up主",
        pubdate="2026-05-01 12:00:00",
        created_at="2026-05-02T00:00:00+00:00",
        has_summary=True,
        artifacts=[
            HistoryArtifact(
                kind="markdown",
                filename=markdown.filename,
                storage_key=markdown.storage_key,
                backend="minio",
            ),
            HistoryArtifact(
                kind="json",
                filename=json_artifact.filename,
                storage_key=json_artifact.storage_key,
                backend="minio",
            ),
            HistoryArtifact(
                kind="summary",
                filename="BV1bLdgBEEKu_demo_summary.md",
                storage_key="b2t/BV1bLdgBEEKu-22222222/BV1bLdgBEEKu_demo_summary.md",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-5-plus",
            ),
            HistoryArtifact(
                kind="summary_table_md",
                filename="BV1bLdgBEEKu_demo_summary_table.md",
                storage_key="b2t/BV1bLdgBEEKu-22222222/BV1bLdgBEEKu_demo_summary_table.md",
                backend="minio",
                summary_preset="financial_timeline_merge",
                summary_profile="qwen3-5-plus",
            ),
        ],
    )

    class FakeHistoryDB:
        def get_run_detail(self, run_id: str):
            assert run_id == "BV1bLdgBEEKu-11111111"
            return detail

    captured_update = {}
    captured_success_summary = {}
    triggered_run_ids = []

    monkeypatch.setattr(
        "backend.existing_transcriptions.get_history_db",
        lambda: FakeHistoryDB(),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._run_summary_only_from_existing",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not regenerate")),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._record_history",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not record history")),
    )
    def fake_build_success_download_fields(results):
        captured_success_summary["summary_key"] = results["summary"].storage_key
        return {
            "download_url": "/api/download/md",
            "filename": results["markdown"].filename,
            "txt_download_url": None,
            "txt_filename": None,
            "summary_download_url": "/api/download/summary",
            "summary_filename": results["summary"].filename,
            "summary_txt_download_url": None,
            "summary_txt_filename": None,
            "summary_table_pdf_download_url": None,
            "summary_table_pdf_filename": None,
        }

    monkeypatch.setattr(
        "backend.existing_transcriptions._build_success_download_fields",
        fake_build_success_download_fields,
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._collect_all_artifacts_for_bvid",
        lambda storage_backend, bvid, fallback_results: list(fallback_results.values()),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._build_all_download_items",
        lambda artifacts: [{"filename": artifact.filename} for artifact in artifacts],
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._update_job",
        lambda job_id, **kwargs: captured_update.update(kwargs),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._append_job_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions.postprocess_scheduler.trigger_rag_index",
        lambda run_id, cfg: triggered_run_ids.append(run_id),
    )

    handled = service.handle_if_existing(
        job_id="job-1",
        bvid="BV1bLdgBEEKu",
        storage_backend=FakeStorage(),
        config=config,
        skip_summary=False,
        summary_preset="financial_timeline_merge",
        summary_profile="qwen3-5-plus",
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
    )

    assert handled is True
    assert captured_success_summary["summary_key"] == (
        "b2t/BV1bLdgBEEKu-22222222/BV1bLdgBEEKu_demo_summary.md"
    )
    assert captured_update["status"] == "succeeded"
    assert captured_update["stage_label"] == "已命中历史总结结果"
    assert "已存在使用模型配置 qwen3-5-plus 与总结模板 financial_timeline_merge" in captured_update["notice"]
    assert triggered_run_ids == ["BV1bLdgBEEKu-11111111"]
