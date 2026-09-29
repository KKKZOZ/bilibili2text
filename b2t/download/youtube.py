"""YouTube single-video audio and original-language captions via yt-dlp."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import RequestError

from b2t.cancellation import CancellationToken, PipelineCancelled
from b2t.download.platform import Platform, PlatformDownloader, PlatformMetadata
from b2t.download.subtitle import Subtitle, SubtitleItem
from b2t.download.url_detect import normalize_youtube_url
from b2t.timezone import SHANGHAI_TZ

logger = logging.getLogger(__name__)
_MAX_SUBTITLE_BYTES = 20 * 1024 * 1024


class SubtitleFetchError(RuntimeError):
    """Captions exist, but could not be downloaded or parsed."""


def _language_base(language: str) -> str:
    return language.removesuffix("-orig").lower().split("-")[0]


def subtitle_candidates(info: dict, language: str = "") -> list[tuple[str, str, dict]]:
    """Rank original manual then automatic captions; exclude auto-translations."""
    automatic = info.get("automatic_captions") or {}
    original = (
        next(
            (key.removesuffix("-orig") for key in automatic if key.endswith("-orig")),
            "",
        )
        or info.get("language")
        or ""
    )
    preferred = language.strip() or original
    candidates = []
    for source, tracks in (
        ("youtube_subtitle", info.get("subtitles") or {}),
        ("youtube_auto_subtitle", automatic),
    ):
        for code, formats in tracks.items():
            if code == "live_chat":
                continue
            if preferred and _language_base(code) != _language_base(preferred):
                continue
            for track in formats:
                if track.get("ext") != "json3" or not track.get("url"):
                    continue
                # yt-dlp exposes auto-translations alongside original ASR tracks.
                if "tlang" in parse_qs(urlsplit(track["url"]).query):
                    continue
                candidates.append((source, code, track))
                break
    return sorted(
        candidates,
        key=lambda item: (
            item[0] != "youtube_subtitle",
            item[1].removesuffix("-orig").lower() != preferred.lower(),
            # Older videos may provide many manual tracks with no audio language.
            # Prefer English, then Chinese, over an arbitrary alphabetic choice.
            {"en": 0, "zh": 1}.get(_language_base(item[1]), 2) if not preferred else 0,
            not item[1].endswith("-orig"),
            item[1],
        ),
    )


def parse_json3(payload: dict, *, source: str, language: str) -> Subtitle | None:
    """Normalize JSON3 events, merging append events and overlapping roll-up text.

    Repeated words in separate, non-overlapping cues are intentionally preserved.
    """
    items: list[SubtitleItem] = []
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        segments = event.get("segs")
        if not isinstance(segments, list):
            continue
        text = "".join(
            seg.get("utf8", "")
            for seg in segments
            if isinstance(seg, dict) and isinstance(seg.get("utf8", ""), str)
        )
        text = " ".join(text.split())
        if not text:
            continue
        try:
            start = float(event["tStartMs"])
            duration = float(event.get("dDurationMs", 0))
            if not math.isfinite(start) or not math.isfinite(duration):
                continue
            start_ms = max(0, round(start))
            end_ms = start_ms + max(0, round(duration))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if items and start_ms >= items[-1].start_ms and start_ms < items[-1].end_ms:
            previous = items[-1]
            if event.get("aAppend"):
                items[-1] = SubtitleItem(
                    previous.start_ms,
                    max(previous.end_ms, end_ms),
                    f"{previous.text} {text}",
                )
                continue
            if text == previous.text or text.startswith(previous.text + " "):
                items[-1] = SubtitleItem(
                    previous.start_ms,
                    max(previous.end_ms, end_ms),
                    text,
                )
                continue
            # Rolling captions can repeat the previous line at the start of a cue.
            old_words, new_words = previous.text.split(), text.split()
            for size in range(min(len(old_words), len(new_words)), 0, -1):
                if old_words[-size:] == new_words[:size]:
                    text = " ".join(new_words[size:])
                    break
            if not text:
                continue
        items.append(SubtitleItem(start_ms, end_ms, text))
    items.sort(key=lambda item: item.start_ms)
    if not items:
        return None
    return Subtitle(
        text="\n".join(item.text for item in items),
        items=tuple(items),
        source=source,
        language=language.removesuffix("-orig"),
    )


class YoutubeDownloader(PlatformDownloader):
    def __init__(self, *, cancellation_token: CancellationToken | None = None):
        self.token = cancellation_token or CancellationToken()
        self._url: str | None = None
        self._info: dict | None = None

    def _progress(self, _status: dict) -> None:
        self.token.raise_if_cancelled()

    def _options(self) -> dict:
        return {
            "noplaylist": True,
            "quiet": True,
            "logger": logger,
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
            "extractor_retries": 2,
            "format": "bestaudio/best",
            "progress_hooks": [self._progress],
            "postprocessor_hooks": [self._progress],
            # Deno is preferred; Node is a useful fallback on existing deployments.
            "js_runtimes": {"deno": {}, "node": {}},
        }

    def _extract(self, url: str) -> dict:
        self.token.raise_if_cancelled()
        canonical = normalize_youtube_url(url)
        if self._url == canonical and self._info is not None:
            return self._info
        with YoutubeDL({**self._options(), "ignore_no_formats_error": True}) as ydl:
            info = ydl.extract_info(canonical, download=False)
        self.token.raise_if_cancelled()
        if not info or info.get("_type", "video") != "video":
            raise ValueError("无法获取 YouTube 单视频信息")
        if info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
            raise ValueError("暂不支持 YouTube 直播、预告或仍在处理的直播回放")
        if not any(
            info.get(key) for key in ("formats", "subtitles", "automatic_captions")
        ):
            raise RuntimeError(
                "无法获取 YouTube 视频音轨或字幕，请确认视频可公开访问，并检查网络和 yt-dlp 日志"
            )
        self._url, self._info = canonical, info
        return info

    def get_metadata(self, url: str) -> PlatformMetadata:
        info = self._extract(url)
        timestamp = int(info.get("timestamp") or info.get("release_timestamp") or 0)
        pubdate = (
            datetime.fromtimestamp(timestamp, tz=SHANGHAI_TZ).isoformat()
            if timestamp
            else ""
        )
        if not pubdate and info.get("upload_date"):
            try:
                pubdate = (
                    datetime.strptime(info["upload_date"], "%Y%m%d")
                    .replace(tzinfo=SHANGHAI_TZ)
                    .date()
                    .isoformat()
                )
            except ValueError:
                pass
        return PlatformMetadata(
            platform=Platform.YOUTUBE,
            platform_id=info["id"],
            title=info.get("title") or info["id"],
            author=info.get("channel") or info.get("uploader") or "",
            author_uid=info.get("channel_id") or "",
            pubdate=pubdate,
            pubdate_timestamp=timestamp,
            description=info.get("description") or "",
            duration_seconds=int(info.get("duration") or 0),
        )

    def fetch_subtitle(self, url: str, *, language: str = "") -> Subtitle | None:
        info = self._extract(url)
        candidates = subtitle_candidates(info, language)
        if not candidates:
            return None
        attempted_urls: set[str] = set()
        with YoutubeDL(self._options()) as ydl:
            for source, code, track in candidates:
                self.token.raise_if_cancelled()
                if track["url"] in attempted_urls:
                    continue
                attempted_urls.add(track["url"])
                try:
                    request = Request(
                        track["url"], headers=info.get("http_headers") or {}
                    )
                    with ydl.urlopen(request) as response:
                        raw = response.read(_MAX_SUBTITLE_BYTES + 1)
                    self.token.raise_if_cancelled()
                    if len(raw) > _MAX_SUBTITLE_BYTES:
                        raise ValueError("字幕文件过大")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise TypeError("字幕 JSON 顶层必须是对象")
                    subtitle = parse_json3(payload, source=source, language=code)
                    if subtitle is not None:
                        return subtitle
                except PipelineCancelled:
                    raise
                except (OSError, ValueError, TypeError, RequestError) as exc:
                    logger.warning("YouTube 字幕 %s 获取或解析失败: %s", code, exc)
        raise SubtitleFetchError("YouTube 有字幕轨道，但获取或解析失败，将尝试音频 ASR")

    def download_audio(
        self, url: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        metadata = self.get_metadata(url)
        self.token.raise_if_cancelled()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"youtube_{metadata.platform_id}"
        options = {
            **self._options(),
            "outtmpl": str(output_dir / f"{stem}.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "128",
                }
            ],
        }
        with YoutubeDL(options) as ydl:
            ydl.process_ie_result(dict(self._extract(url)), download=True)
        self.token.raise_if_cancelled()
        audio = output_dir / f"{stem}.m4a"
        if not audio.is_file():
            raise RuntimeError("YouTube 音频下载未生成预期的 M4A 文件，请检查 FFmpeg")
        return audio, metadata
