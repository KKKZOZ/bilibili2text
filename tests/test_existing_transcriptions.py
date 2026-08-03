from dataclasses import replace
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.existing_transcriptions import (
    ExistingTranscriptionService,
    _has_current_timeline_schema,
    _resolve_requested_summary_selection,
    _summary_requires_video_timestamps,
)

from b2t.cancellation import CancellationToken
from b2t.config import (
    AppConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    RagConfig,
    StorageConfig,
    STTConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPreset,
    SummaryPresetsConfig,
)
from b2t.history import HistoryArtifact, HistoryDetail
from b2t.download.metadata import VideoMetadata  # noqa: E402
from b2t.download.platform import Platform, PlatformMetadata  # noqa: E402
from b2t.storage.base import StoredArtifact
from b2t.storage.local import LocalStorageBackend  # noqa: E402
from backend import services as services_module  # noqa: E402


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
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("should not record history")
        ),
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
    assert captured_update["history_run_id"] == "BV1bLdgBEEKu-11111111"
    assert (
        "已存在使用模型配置 qwen3-5-plus 与总结模板 financial_timeline_merge"
        in captured_update["notice"]
    )
    assert triggered_run_ids == ["BV1bLdgBEEKu-11111111"]


def test_custom_summary_preset_does_not_resolve_to_default_preset() -> None:
    resolved_preset, resolved_profile = _resolve_requested_summary_selection(
        config=_config(),
        summary_preset="__user_custom__",
        summary_profile="qwen3-5-plus",
    )

    assert resolved_preset == "__user_custom__"
    assert resolved_profile == "qwen3-5-plus"


def test_timeline_summary_detects_timestamp_requirement() -> None:
    config = _config()
    config.summary_presets.presets["financial_timeline_merge"] = SummaryPreset(
        label="金融时间线主题归并",
        prompt_template="视频时间必须引用 Speaker MM:SS。\n\n{content}",
    )

    assert _summary_requires_video_timestamps(
        config=config,
        summary_preset="financial_timeline_merge",
        summary_prompt_template=None,
    )


def test_old_cached_transcription_does_not_satisfy_timeline_schema() -> None:
    artifact = StoredArtifact(
        filename="demo_transcription.json",
        storage_key="demo_transcription.json",
        backend="memory",
    )

    class FakeStorage:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def open_stream(self, storage_key: str):
            stream = BytesIO(self.payload)

            class StreamContext:
                def __enter__(self):
                    return stream

                def __exit__(self, exc_type, exc, traceback):
                    stream.close()

            return StreamContext()

    results = {"json": artifact}

    assert not _has_current_timeline_schema(
        FakeStorage(b'{"source":"bilibili_subtitle"}'), results
    )
    assert _has_current_timeline_schema(
        FakeStorage(b'{"timeline_schema_version":1}'), results
    )


def test_timeline_summary_skips_old_cached_transcription() -> None:
    config = _config()
    config.summary_presets.presets["financial_timeline_merge"] = SummaryPreset(
        label="金融时间线主题归并",
        prompt_template="视频时间必须引用 Speaker MM:SS。\n\n{content}",
    )
    artifacts = {
        "json": StoredArtifact(
            filename="demo_transcription.json",
            storage_key="demo_transcription.json",
            backend="memory",
        ),
        "markdown": StoredArtifact(
            filename="demo.md",
            storage_key="demo.md",
            backend="memory",
        ),
    }

    class FakeStorage:
        def find_existing_transcription(self, bvid: str):
            return artifacts

        def open_stream(self, storage_key: str):
            stream = BytesIO(b'{"source":"bilibili_subtitle"}')

            class StreamContext:
                def __enter__(self):
                    return stream

                def __exit__(self, exc_type, exc, traceback):
                    stream.close()

            return StreamContext()

    handled = ExistingTranscriptionService().handle_if_existing(
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

    assert handled is False


def test_summary_only_fetches_xiaoyuzhou_metadata_without_redownloading_audio(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "xiaoyuzhou_episode-1-11111111"
    source_dir.mkdir()
    markdown_path = source_dir / "xiaoyuzhou_episode-1_投资实战派_E191_transcription.md"
    markdown_path.write_text("转录内容", encoding="utf-8")
    existing_results = {
        "markdown": StoredArtifact(
            filename=markdown_path.name,
            storage_key=str(markdown_path),
            backend="local",
        )
    }
    detail = HistoryDetail(
        run_id="xiaoyuzhou_episode-1-11111111",
        bvid="xiaoyuzhou_episode-1",
        title="",
        author="Unknown",
        pubdate="",
        created_at="2026-07-20T00:00:00+00:00",
        has_summary=False,
        artifacts=[],
    )

    class FakeHistoryDB:
        def get_run_detail(self, run_id: str):
            assert run_id == "xiaoyuzhou_episode-1-11111111"
            return detail

    monkeypatch.setattr(services_module, "get_history_db", lambda: FakeHistoryDB())
    monkeypatch.setattr(
        "b2t.download.xiaoyuzhou.fetch_xiaoyuzhou_metadata",
        lambda episode_id: PlatformMetadata(
            platform=Platform.XIAOYUZHOU,
            platform_id=episode_id,
            title="投资实战派 — E191 AI四大半导体新方向",
            author="wong永庆",
            pubdate="2026-07-19 23:54:05",
            pubdate_timestamp=1784505245,
        ),
    )

    captured: dict[str, object] = {}

    def fake_summarize(*args, **kwargs):
        captured["metadata"] = kwargs["metadata"]
        summary_path = Path(args[0]).with_name("xiaoyuzhou_episode-1_summary.md")
        summary_path.write_text("# 总结\n", encoding="utf-8")
        return summary_path

    monkeypatch.setattr(
        services_module,
        "summarize_with_comment_viewpoints",
        fake_summarize,
    )
    monkeypatch.setattr(
        services_module,
        "export_summary_table_without_video_time",
        lambda *args, **kwargs: None,
    )

    config = replace(
        _config(),
        download=DownloadConfig(output_dir=str(tmp_path / "outputs")),
    )
    results = services_module._run_summary_only_from_existing(
        bvid="xiaoyuzhou_episode-1",
        storage_backend=LocalStorageBackend(),
        config=config,
        existing_results=existing_results,
        summary_preset="financial_timeline_merge",
        summary_profile="qwen3-5-plus",
    )

    metadata = captured["metadata"]
    assert isinstance(metadata, VideoMetadata)
    assert metadata.author == "wong永庆"
    assert metadata.pubdate == "2026-07-19 23:54:05"
    assert isinstance(results["_metadata"], VideoMetadata)
    assert services_module._should_refresh_existing_summary_metadata(
        bvid="xiaoyuzhou_episode-1",
        existing_results=existing_results,
    )


def test_existing_transcription_cancellation_stops_before_summary_persistence(
    monkeypatch,
) -> None:
    token = CancellationToken()
    artifacts = {
        "markdown": StoredArtifact(
            filename="demo.md",
            storage_key="run/demo.md",
            backend="memory",
        )
    }

    class FakeStorage:
        def find_existing_transcription(self, bvid: str):
            return artifacts

    monkeypatch.setattr(
        "backend.existing_transcriptions._find_existing_summary_results_for_selection",
        lambda **kwargs: None,
    )

    def cancel_during_summary(**kwargs):
        assert kwargs["cancellation_token"] is token
        token.cancel()
        token.raise_if_cancelled()

    monkeypatch.setattr(
        "backend.existing_transcriptions._run_summary_only_from_existing",
        cancel_during_summary,
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._record_history",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled summary must not be persisted")
        ),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions.postprocess_scheduler.trigger_rag_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled summary must not be indexed")
        ),
    )
    monkeypatch.setattr(
        "backend.existing_transcriptions._update_job",
        lambda *args, **kwargs: None,
    )

    handled = ExistingTranscriptionService().handle_if_existing(
        job_id="job-cancelled",
        bvid="BV1bLdgBEEKu",
        storage_backend=FakeStorage(),
        config=_config(),
        skip_summary=False,
        summary_preset="financial_timeline_merge",
        summary_profile="qwen3-5-plus",
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
        cancellation_token=token,
    )

    assert handled is True
    assert token.is_cancelled()
