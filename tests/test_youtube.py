import json
from io import BytesIO
from pathlib import Path

import pytest

from b2t.cancellation import CancellationToken, PipelineCancelled
from b2t.config import create_app_config
from b2t.download import youtube
from b2t.download.platform import Platform, PlatformMetadata
from b2t.download.subtitle import SubtitleItem
from b2t.download.url_detect import (
    detect_platform,
    extract_platform_id,
    normalize_youtube_url,
)
from b2t.history import HistoryDB, record_pipeline_run
from b2t.pipeline import run_pipeline
from b2t.storage.local import LocalStorageBackend

VIDEO_ID = "BaW_jenozKc"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
METADATA = PlatformMetadata(
    platform=Platform.YOUTUBE,
    platform_id=VIDEO_ID,
    title="Test video",
    author="Test channel",
    duration_seconds=90,
)


@pytest.mark.parametrize(
    "url",
    [
        URL,
        URL + "&list=PLexample&t=10",
        f"https://youtu.be/{VIDEO_ID}?si=tracking",
        f"分享 https://m.youtube.com/shorts/{VIDEO_ID}。",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
    ],
)
def test_youtube_single_video_urls(url):
    assert detect_platform(url) == Platform.YOUTUBE
    assert extract_platform_id(url, Platform.YOUTUBE) == VIDEO_ID
    assert normalize_youtube_url(url) == URL


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PLexample",
        "https://www.youtube.com/@channel",
        "https://youtu.be/too-short",
        f"https://www.youtube.com.evil.example/watch?v={VIDEO_ID}",
        f"https://evil.example/youtube.com/watch?v={VIDEO_ID}",
        f"https://user@www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com:8443/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&v=abcdefghijk",
    ],
)
def test_invalid_youtube_urls_are_rejected(url):
    assert detect_platform(url) is None
    assert extract_platform_id(url, Platform.YOUTUBE) is None
    with pytest.raises(ValueError, match="单个视频"):
        normalize_youtube_url(url)


def track(query="lang=en"):
    return [{"ext": "json3", "url": f"https://www.youtube.com/api/timedtext?{query}"}]


def test_subtitles_prefer_original_manual_then_auto_and_exclude_translations():
    info = {
        "language": "en",
        "subtitles": {"zh": track("lang=zh"), "en": track(), "live_chat": track()},
        "automatic_captions": {
            "en-orig": track(),
            "zh": track("lang=en&tlang=zh"),
        },
    }
    assert [
        (source, code) for source, code, _ in youtube.subtitle_candidates(info)
    ] == [
        ("youtube_subtitle", "en"),
        ("youtube_auto_subtitle", "en-orig"),
    ]
    assert [
        (source, code) for source, code, _ in youtube.subtitle_candidates(info, "zh")
    ] == [
        ("youtube_subtitle", "zh"),
    ]
    assert youtube.subtitle_candidates(info, "ja") == []
    del info["language"]
    assert youtube.subtitle_candidates(info)[0][1] == "en"


def event(start, duration, text, **kwargs):
    return {
        "tStartMs": start,
        "dDurationMs": duration,
        "segs": [{"utf8": text}],
        **kwargs,
    }


def test_unknown_original_language_prefers_english_over_alphabetical_track():
    info = {
        "subtitles": {"de": track("lang=de"), "en": track(), "zh": track("lang=zh")}
    }
    assert youtube.subtitle_candidates(info)[0][1] == "en"


def test_json3_preserves_timing_and_removes_overlapping_rollup_only():
    result = youtube.parse_json3(
        {
            "events": [
                {"tStartMs": 0},
                event(1000, 2000, "Hello world"),
                event(1500, 2000, "Hello world again"),
                event(2000, 2000, "world again today"),
                event(5000, 1000, "today"),  # A real repetition, not a rolling cue.
                event("bad", 1000, "invalid"),
                event(6000, 1, "\n"),
            ]
        },
        source="youtube_auto_subtitle",
        language="en-orig",
    )
    assert result.text == "Hello world again\ntoday\ntoday"
    assert result.language == "en"
    assert result.items[0] == SubtitleItem(1000, 3500, "Hello world again")
    assert result.items[-1] == SubtitleItem(5000, 6000, "today")


def test_json3_handles_append_events_and_word_fragments():
    result = youtube.parse_json3(
        {
            "events": [
                {
                    "tStartMs": 0,
                    "dDurationMs": 2000,
                    "segs": [
                        {"utf8": "Hello"},
                        {"utf8": " world", "tOffsetMs": 500},
                    ],
                },
                event(1000, 2000, "again", aAppend=1),
            ]
        },
        source="youtube_auto_subtitle",
        language="en",
    )
    assert result.items == (SubtitleItem(0, 3000, "Hello world again"),)


def fake_ydl(monkeypatch, tmp_path, *, response=None, info_overrides=None):
    calls = {"extract": 0, "download": 0, "requests": [], "options": []}
    info = {
        "id": VIDEO_ID,
        "title": "Test video",
        "channel": "Test channel",
        "duration": 90,
        "upload_date": "20260102",
        "language": "en",
        "subtitles": {"en": track()},
        "formats": [{"format_id": "audio", "ext": "m4a"}],
        **(info_overrides or {}),
    }

    class FakeYoutubeDL:
        def __init__(self, options):
            calls["options"].append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            assert url == URL and download is False
            calls["extract"] += 1
            return info

        def urlopen(self, request):
            calls["requests"].append(request.url)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return BytesIO(response(request.url))
            return BytesIO(
                response or json.dumps({"events": [event(0, 1000, "Hello")]}).encode()
            )

        def process_ie_result(self, data, download):
            assert data["id"] == VIDEO_ID and download is True
            calls["download"] += 1
            (tmp_path / f"youtube_{VIDEO_ID}.m4a").write_bytes(b"audio")

    monkeypatch.setattr(youtube, "YoutubeDL", FakeYoutubeDL)
    return calls


def test_downloader_reuses_metadata_and_normalizes_audio(monkeypatch, tmp_path):
    calls = fake_ydl(monkeypatch, tmp_path)
    downloader = youtube.YoutubeDownloader()
    metadata = downloader.get_metadata(URL)
    assert metadata.pubdate == "2026-01-02"
    assert metadata.duration_seconds == 90
    assert downloader.fetch_subtitle(URL).text == "Hello"
    audio, again = downloader.download_audio(f"https://youtu.be/{VIDEO_ID}", tmp_path)
    assert audio.suffix == ".m4a" and again == metadata
    assert calls["extract"] == 1 and calls["download"] == 1
    assert all(options["noplaylist"] for options in calls["options"])
    assert calls["options"][-1]["postprocessors"][0]["preferredcodec"] == "m4a"


@pytest.mark.parametrize(
    "response", [b"not json", b"{}", b"[]", OSError("unavailable")]
)
def test_subtitle_fetch_failure_is_distinct_from_missing(
    monkeypatch, tmp_path, response
):
    fake_ydl(monkeypatch, tmp_path, response=response)
    with pytest.raises(youtube.SubtitleFetchError):
        youtube.YoutubeDownloader().fetch_subtitle(URL)


def test_missing_subtitles_does_not_request_caption_file(monkeypatch, tmp_path):
    calls = fake_ydl(monkeypatch, tmp_path, info_overrides={"subtitles": {}})
    assert youtube.YoutubeDownloader().fetch_subtitle(URL) is None
    assert calls["requests"] == []


def test_unusable_manual_subtitle_falls_back_to_original_auto(monkeypatch, tmp_path):
    def response(url):
        if "manual" in url:
            return b"{}"
        return json.dumps({"events": [event(1000, 2000, "Automatic caption")]}).encode()

    fake_ydl(
        monkeypatch,
        tmp_path,
        response=response,
        info_overrides={
            "subtitles": {"en": track("lang=en&kind=manual")},
            "automatic_captions": {"en-orig": track()},
        },
    )
    subtitle = youtube.YoutubeDownloader().fetch_subtitle(URL)
    assert subtitle.source == "youtube_auto_subtitle"
    assert subtitle.language == "en"
    assert subtitle.text == "Automatic caption"


def test_unavailable_video_is_not_treated_as_missing_subtitles(monkeypatch, tmp_path):
    fake_ydl(monkeypatch, tmp_path, info_overrides={"formats": [], "subtitles": {}})
    with pytest.raises(RuntimeError, match="可公开访问"):
        youtube.YoutubeDownloader().get_metadata(URL)


@pytest.mark.parametrize("status", ["is_live", "is_upcoming", "post_live"])
def test_live_videos_rejected(monkeypatch, tmp_path, status):
    fake_ydl(monkeypatch, tmp_path, info_overrides={"live_status": status})
    with pytest.raises(ValueError, match="直播"):
        youtube.YoutubeDownloader().get_metadata(URL)


def test_cancelled_downloader_never_starts_network(monkeypatch, tmp_path):
    calls = fake_ydl(monkeypatch, tmp_path)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(PipelineCancelled):
        youtube.YoutubeDownloader(cancellation_token=token).get_metadata(URL)
    assert calls["extract"] == 0


def test_pipeline_subtitles_skip_audio_and_asr_and_record_history(
    monkeypatch, tmp_path
):
    fake_ydl(monkeypatch, tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("Subtitle path must not download audio or call ASR")

    monkeypatch.setattr(youtube.YoutubeDownloader, "download_audio", unexpected)
    monkeypatch.setattr("b2t.pipeline.create_stt_provider", unexpected)
    used = []
    legacy = []
    results = run_pipeline(
        URL,
        create_app_config(output_dir=tmp_path),
        skip_summary=True,
        subtitle_used_callback=used.append,
        bilibili_subtitle_used_callback=lambda: legacy.append(True),
    )
    assert "audio" not in results and legacy == []
    assert used[0].source == "youtube_subtitle"
    data = json.loads(Path(results["json"].storage_key).read_text())
    assert data["source"] == "youtube_subtitle" and data["language"] == "en"
    assert data["segments"] == [{"start": 0, "end": 1, "text": "Hello"}]
    assert results["_metadata"].duration_seconds == 90
    db = HistoryDB(tmp_path / "db")
    record_pipeline_run(db=db, bvid=f"youtube_{VIDEO_ID}", results=results)
    assert db.list_runs(platforms=("youtube",)).total == 1
    assert ("youtube", 1) in db.list_history_platform_counts()


@pytest.mark.parametrize("mode", ["missing", "failed", "disabled"])
def test_pipeline_audio_fallback(monkeypatch, tmp_path, mode):
    calls = []

    class FakeDownloader:
        def __init__(self, **kwargs):
            pass

        def get_metadata(self, url):
            return METADATA

        def fetch_subtitle(self, url, **kwargs):
            calls.append("subtitle")
            if mode == "disabled":
                pytest.fail("Subtitle preference was ignored")
            if mode == "failed":
                raise youtube.SubtitleFetchError("字幕请求失败")

        def download_audio(self, url, output_dir):
            calls.append("audio")
            path = output_dir / "download.m4a"
            path.write_bytes(b"audio")
            return path, METADATA

    class FakeSTT:
        def transcribe(self, audio, work_dir, **kwargs):
            calls.append("asr")
            assert audio.is_file()
            path = work_dir / "result_transcription.json"
            path.write_text(json.dumps({"text": "ASR fallback"}))
            return path

    monkeypatch.setattr(youtube, "YoutubeDownloader", FakeDownloader)
    monkeypatch.setattr("b2t.pipeline.create_stt_provider", lambda *args: FakeSTT())
    storage = LocalStorageBackend(tmp_path)
    results = run_pipeline(
        URL,
        create_app_config(output_dir=tmp_path, stt_api_key="test-key"),
        skip_summary=True,
        storage_backend=storage,
        stt_storage_backend=storage,
        prefer_subtitles=False if mode == "disabled" else None,
    )
    assert calls == (["subtitle"] if mode != "disabled" else []) + ["audio", "asr"]
    assert "audio" in results


def test_subtitle_path_without_asr_key_is_allowed_but_missing_requires_key(
    monkeypatch, tmp_path
):
    fake_ydl(monkeypatch, tmp_path, info_overrides={"subtitles": {}})
    with pytest.raises(ValueError, match="DashScope API Key"):
        run_pipeline(URL, create_app_config(output_dir=tmp_path), skip_summary=True)


def test_local_cache_respects_youtube_id_case(tmp_path):
    directory = tmp_path / f"youtube_{VIDEO_ID}_title"
    directory.mkdir()
    (directory / f"youtube_{VIDEO_ID}_title_transcription.md").write_text("Hello")
    storage = LocalStorageBackend(tmp_path)
    assert storage.list_existing_transcription_artifacts(f"youtube_{VIDEO_ID}")
    assert (
        storage.list_existing_transcription_artifacts(f"youtube_{VIDEO_ID.lower()}")
        == []
    )


def test_cli_can_force_asr_without_changing_legacy_flag():
    from b2t.cli import _build_script_parser, _validate_script_args

    parser = _build_script_parser()
    args = _validate_script_args(parser, parser.parse_args([URL, "--no-subtitles"]))
    assert args.prefer_subtitles is False
    legacy = _validate_script_args(
        parser, parser.parse_args([URL, "--no-bilibili-subtitle"])
    )
    assert legacy.prefer_bilibili_subtitle is False and legacy.prefer_subtitles is None
