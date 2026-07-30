import json
import subprocess
from pathlib import Path

from b2t.config import create_app_config
from b2t.download.subtitle import (
    BilibiliSubtitle,
    BilibiliSubtitleItem,
    fetch_bilibili_subtitle,
)
from b2t.pipeline import run_pipeline
from b2t.storage.local import LocalStorageBackend


def test_fetch_bilibili_subtitle_parses_cli_json(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        assert cmd == [
            "bili",
            "video",
            "BV1ABcsztEcY",
            "--subtitle-timeline",
            "--json",
        ]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "data": {
                        "subtitle": {
                            "available": True,
                            "text": "第一句\n第二句",
                            "items": [
                                {"from": 1.234, "to": 2.5, "content": "第一句"},
                                {"from": 65.9, "to": 67, "content": "第二句"},
                            ],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

    monkeypatch.setattr("b2t.download.subtitle.subprocess.run", fake_run)

    subtitle = fetch_bilibili_subtitle("BV1ABcsztEcY")

    assert subtitle == BilibiliSubtitle(
        text="第一句\n第二句",
        items=(
            BilibiliSubtitleItem(start_ms=1234, end_ms=2500, text="第一句"),
            BilibiliSubtitleItem(start_ms=65900, end_ms=67000, text="第二句"),
        ),
    )


def test_fetch_bilibili_subtitle_returns_none_when_unavailable(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"data": {"subtitle": {"available": False, "text": ""}}}),
            stderr="",
        )

    monkeypatch.setattr("b2t.download.subtitle.subprocess.run", fake_run)

    assert fetch_bilibili_subtitle("BV1ABcsztEcY") is None


def test_pipeline_uses_bilibili_subtitle_before_asr(
    monkeypatch, tmp_path: Path
) -> None:
    config = create_app_config(output_dir=tmp_path)
    storage = LocalStorageBackend(tmp_path)

    monkeypatch.setattr(
        "b2t.pipeline.fetch_bilibili_subtitle",
        lambda target: BilibiliSubtitle(
            text="第一句字幕\n\n第二句字幕",
            items=(
                BilibiliSubtitleItem(
                    start_ms=1234,
                    end_ms=2500,
                    text="第一句字幕",
                ),
                BilibiliSubtitleItem(
                    start_ms=65900,
                    end_ms=67000,
                    text="第二句字幕",
                ),
            ),
        ),
    )
    monkeypatch.setattr("b2t.pipeline.get_video_metadata", lambda bvid: None)
    monkeypatch.setattr(
        "b2t.pipeline.download_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ASR fallback should not download audio")
        ),
    )
    monkeypatch.setattr(
        "b2t.pipeline.create_stt_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ASR fallback should not create STT provider")
        ),
    )

    used_callback_calls = 0

    def mark_subtitle_used() -> None:
        nonlocal used_callback_calls
        used_callback_calls += 1

    results = run_pipeline(
        "BV1ABcsztEcY",
        config,
        skip_summary=True,
        storage_backend=storage,
        stt_storage_backend=storage,
        bilibili_subtitle_used_callback=mark_subtitle_used,
    )

    assert used_callback_calls == 1
    assert "audio" not in results
    assert {"json", "markdown"} <= results.keys()

    json_path = Path(results["json"].storage_key)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["source"] == "bilibili_subtitle"
    assert payload["text"] == "第一句字幕\n\n第二句字幕"
    assert payload["timeline_schema_version"] == 1
    assert payload["segments"] == [
        {"start": 1.234, "end": 2.5, "text": "第一句字幕"},
        {"start": 65.9, "end": 67.0, "text": "第二句字幕"},
    ]

    markdown = Path(results["markdown"].storage_key).read_text(encoding="utf-8")
    assert "Speaker 00:01\n第一句字幕" in markdown
    assert "Speaker 01:05\n第二句字幕" in markdown


def test_pipeline_falls_back_to_asr_when_bilibili_subtitle_missing(
    monkeypatch, tmp_path: Path
) -> None:
    config = create_app_config(output_dir=tmp_path)
    storage = LocalStorageBackend(tmp_path)
    audio_path = tmp_path / "downloaded.m4a"
    audio_path.write_bytes(b"audio")

    class FakeSttProvider:
        def transcribe(self, audio_path, output_dir, progress_callback=None):
            json_path = output_dir / f"{Path(audio_path).stem}_transcription.json"
            json_path.write_text(
                json.dumps({"text": "ASR fallback text"}, ensure_ascii=False),
                encoding="utf-8",
            )
            return json_path

    monkeypatch.setattr("b2t.pipeline.fetch_bilibili_subtitle", lambda target: None)
    monkeypatch.setattr("b2t.pipeline.get_video_metadata", lambda bvid: None)
    monkeypatch.setattr(
        "b2t.pipeline.download_audio",
        lambda *args, **kwargs: (audio_path, None),
    )
    monkeypatch.setattr(
        "b2t.pipeline.create_stt_provider",
        lambda *args, **kwargs: FakeSttProvider(),
    )

    used_callback_calls = 0

    def mark_subtitle_used() -> None:
        nonlocal used_callback_calls
        used_callback_calls += 1

    results = run_pipeline(
        "BV1ABcsztEcY",
        config,
        skip_summary=True,
        storage_backend=storage,
        stt_storage_backend=storage,
        bilibili_subtitle_used_callback=mark_subtitle_used,
    )

    assert used_callback_calls == 0
    assert {"audio", "json", "markdown"} <= results.keys()
    payload = json.loads(Path(results["json"].storage_key).read_text(encoding="utf-8"))
    assert payload["timeline_schema_version"] == 1
    markdown = Path(results["markdown"].storage_key).read_text(encoding="utf-8")
    assert "ASR fallback text" in markdown
