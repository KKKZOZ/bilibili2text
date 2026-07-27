"""Xiaoyuzhou FM downloader — extract metadata and audio from episode pages."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from b2t.download.platform import (
    Platform,
    PlatformMetadata,
    PlatformDownloader,
    build_filename_component,
    sanitize_filename_component,
)
from b2t.download.url_detect import extract_platform_id

logger = logging.getLogger(__name__)

_NEXT_DATA_PATTERN = re.compile(
    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*(.*?)\s*</script>',
    re.DOTALL,
)
_SCHEMA_JSON_PATTERN = re.compile(
    r"<script\b(?=[^>]*\btype=[\"']application/ld\+json[\"'])[^>]*>"
    r"\s*(.*?)\s*</script>",
    re.DOTALL,
)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BVID_PREFIX = f"{Platform.XIAOYUZHOU.value}_"


@dataclass(frozen=True)
class _EpisodeInfo:
    metadata: PlatformMetadata
    audio_url: str
    podcast_title: str
    episode_title: str


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _name_from_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _first_non_empty(
            value.get("name"),
            value.get("nickname"),
            value.get("title"),
            value.get("author"),
        )
    if isinstance(value, list):
        for item in value:
            candidate = _name_from_value(item)
            if candidate:
                return candidate
        return ""
    return _clean_text(value)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        candidate = (
            _name_from_value(value)
            if isinstance(value, (Mapping, list))
            else _clean_text(value)
        )
        if candidate:
            return candidate
    return ""


def _first_non_empty_value(*values: Any) -> Any:
    for value in values:
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        if value not in (None, ""):
            return value
    return ""


def _parse_datetime_value(value: Any) -> tuple[str, int]:
    """Parse ISO or timestamp-like datetime to (formatted_str, timestamp)."""
    if isinstance(value, (int, float)) and value > 0:
        timestamp = int(value / 1000) if value > 10_000_000_000 else int(value)
        return datetime.fromtimestamp(timestamp).strftime(
            "%Y-%m-%d %H:%M:%S"
        ), timestamp

    cleaned = _clean_text(value)
    if not cleaned:
        return "", 0
    if cleaned.isdigit():
        return _parse_datetime_value(int(cleaned))

    normalized = cleaned.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        ts = int(dt.timestamp())
        return dt.strftime("%Y-%m-%d %H:%M:%S"), ts
    except (ValueError, TypeError):
        return cleaned, 0


def _extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA_PATTERN.search(html)
    if match is None:
        raise RuntimeError("无法从小宇宙页面中提取 __NEXT_DATA__ JSON")

    next_data = json.loads(match.group(1))
    if not isinstance(next_data, dict):
        raise RuntimeError("小宇宙页面 __NEXT_DATA__ 不是 JSON 对象")
    return next_data


def _extract_schema_items(html: str) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    for match in _SCHEMA_JSON_PATTERN.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, Mapping):
            items.append(data)
        elif isinstance(data, list):
            items.extend(item for item in data if isinstance(item, Mapping))
    return items


def _extract_episode(next_data: Mapping[str, Any]) -> Mapping[str, Any]:
    props = _as_mapping(next_data.get("props"))
    page_props = _as_mapping(props.get("pageProps"))
    episode = _as_mapping(page_props.get("episode"))
    if not episode:
        raise RuntimeError("小宇宙页面 JSON 中未找到 episode 数据")
    return episode


def _schema_date_published(schema_items: list[Mapping[str, Any]]) -> Any:
    for item in schema_items:
        value = _first_non_empty_value(
            item.get("datePublished"),
            item.get("uploadDate"),
            item.get("dateCreated"),
        )
        if value:
            return value
    return ""


def _schema_author(schema_items: list[Mapping[str, Any]]) -> str:
    for item in schema_items:
        author = _first_non_empty(
            item.get("author"),
            item.get("creator"),
            _as_mapping(item.get("partOfSeries")).get("name"),
        )
        if author:
            return author
    return ""


def _extract_episode_info(
    *,
    eid: str,
    episode: Mapping[str, Any],
    schema_items: list[Mapping[str, Any]],
) -> _EpisodeInfo:
    podcast = _as_mapping(episode.get("podcast"))
    podcasters = _as_list(episode.get("podcasters")) or _as_list(
        podcast.get("podcasters")
    )

    podcast_title = _first_non_empty(
        podcast.get("title"),
        podcast.get("name"),
        episode.get("podcastTitle"),
    )
    episode_title = _first_non_empty(episode.get("title"), "Untitled")
    author = _first_non_empty(
        podcast.get("author"),
        episode.get("author"),
        podcasters,
        podcast.get("owner"),
        _schema_author(schema_items),
        podcast_title,
        "Unknown",
    )

    pubdate_raw = _first_non_empty_value(
        episode.get("pubDate"),
        episode.get("publishedAt"),
        episode.get("published_at"),
        episode.get("publishDate"),
        episode.get("datePublished"),
        episode.get("createdAt"),
        episode.get("created_at"),
        _schema_date_published(schema_items),
    )
    pubdate, pubdate_ts = _parse_datetime_value(pubdate_raw)

    description_raw = _first_non_empty(
        episode.get("description"),
        episode.get("summary"),
    )
    shownotes = _first_non_empty(episode.get("shownotes"), episode.get("showNotes"))
    duration = int(episode.get("duration", 0) or 0)

    enclosure = _as_mapping(episode.get("enclosure"))
    media = _as_mapping(episode.get("media"))
    media_source = _as_mapping(media.get("source"))
    audio = _as_mapping(episode.get("audio"))
    audio_url = _first_non_empty(
        enclosure.get("url"),
        media_source.get("url"),
        media.get("url"),
        audio.get("url"),
        episode.get("audioUrl"),
        episode.get("audio_url"),
    )

    metadata = PlatformMetadata(
        platform=Platform.XIAOYUZHOU,
        platform_id=eid,
        title=f"{podcast_title} — {episode_title}" if podcast_title else episode_title,
        author=author,
        pubdate=pubdate,
        pubdate_timestamp=pubdate_ts,
        description=description_raw,
        duration_seconds=duration,
        extra={
            "podcast_title": podcast_title,
            "podcasters": [
                {
                    "nickname": _first_non_empty(p.get("nickname"), p.get("name")),
                    "bio": _clean_text(p.get("bio")),
                }
                for p in podcasters
                if isinstance(p, Mapping)
            ],
            "shownotes": shownotes,
        },
    )
    return _EpisodeInfo(
        metadata=metadata,
        audio_url=audio_url,
        podcast_title=podcast_title,
        episode_title=episode_title,
    )


class XiaoyuzhouDownloader(PlatformDownloader):
    """Download audio and metadata from a Xiaoyuzhou FM episode."""

    def fetch_metadata(self, url_or_eid: str) -> PlatformMetadata:
        """Fetch episode metadata without downloading audio."""
        info = self._fetch_episode_info(url_or_eid)
        return info.metadata

    def _fetch_episode_info(self, url_or_eid: str) -> _EpisodeInfo:
        cleaned = url_or_eid.strip()
        fallback_eid = cleaned.removeprefix(_BVID_PREFIX)
        eid = extract_platform_id(cleaned, Platform.XIAOYUZHOU) or fallback_eid
        if not eid:
            raise ValueError(f"无法从小宇宙链接中提取 episode ID: {url_or_eid}")

        page_url = f"https://www.xiaoyuzhoufm.com/episode/{eid}"
        logger.info("Fetching Xiaoyuzhou episode: %s", page_url)

        resp = httpx.get(
            page_url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        )
        resp.raise_for_status()
        html = resp.text

        next_data = _extract_next_data(html)
        episode = _extract_episode(next_data)
        schema_items = _extract_schema_items(html)
        return _extract_episode_info(
            eid=eid,
            episode=episode,
            schema_items=schema_items,
        )

    def download_audio(
        self, url: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        info = self._fetch_episode_info(url)
        metadata = info.metadata
        if not info.audio_url:
            raise RuntimeError("小宇宙页面中未找到音频 URL")

        logger.info(
            "Xiaoyuzhou episode: %s — %s (%s)",
            info.podcast_title or "Unknown Podcast",
            info.episode_title,
            metadata.author,
        )

        # Download audio — use podcast + episode title in filename
        # (eid is already in the bvid prefix added by the pipeline)
        safe_podcast = (
            sanitize_filename_component(info.podcast_title, 30)
            if info.podcast_title
            else ""
        )
        safe_title = sanitize_filename_component(info.episode_title, 50)
        audio_name = f"{safe_podcast}_{safe_title}" if safe_podcast else safe_title
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / build_filename_component(
            audio_name,
            suffix=".m4a",
        )
        logger.info("Downloading audio from: [REDACTED_URL]")
        with httpx.stream(
            "GET", info.audio_url, headers={"User-Agent": _USER_AGENT}
        ) as stream:
            stream.raise_for_status()
            with open(audio_path, "wb") as f:
                for chunk in stream.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        logger.info("Audio downloaded: %.1f MB", file_size_mb)

        return audio_path, metadata


def fetch_xiaoyuzhou_metadata(url_or_eid: str) -> PlatformMetadata:
    """Fetch Xiaoyuzhou episode metadata without downloading audio."""
    return XiaoyuzhouDownloader().fetch_metadata(url_or_eid)


__all__ = ["XiaoyuzhouDownloader", "fetch_xiaoyuzhou_metadata"]
