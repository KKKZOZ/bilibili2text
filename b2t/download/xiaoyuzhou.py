"""Xiaoyuzhou FM downloader — extract metadata and audio from episode pages."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

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
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _parse_iso_datetime(value: str) -> tuple[str, int]:
    """Parse ISO datetime string to (formatted_str, timestamp)."""
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        ts = int(dt.timestamp())
        return dt.strftime("%Y-%m-%d %H:%M:%S"), ts
    except (ValueError, TypeError):
        return value, 0


class XiaoyuzhouDownloader(PlatformDownloader):
    """Download audio and metadata from a Xiaoyuzhou FM episode."""

    def download_audio(
        self, url: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        eid = extract_platform_id(url, Platform.XIAOYUZHOU)
        if eid is None:
            raise ValueError(f"无法从小宇宙链接中提取 episode ID: {url}")

        page_url = f"https://www.xiaoyuzhoufm.com/episode/{eid}"
        logger.info("Fetching Xiaoyuzhou episode: %s", page_url)

        resp = httpx.get(
            page_url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        )
        resp.raise_for_status()
        html = resp.text

        # Extract __NEXT_DATA__ JSON (Next.js SSR)
        match = _NEXT_DATA_PATTERN.search(html)
        if match is None:
            raise RuntimeError("无法从小宇宙页面中提取 __NEXT_DATA__ JSON")

        next_data = json.loads(match.group(1))
        episode = next_data.get("props", {}).get("pageProps", {}).get("episode", {})
        if not isinstance(episode, dict) or not episode:
            raise RuntimeError("小宇宙页面 JSON 中未找到 episode 数据")

        # Extract metadata
        podcast = episode.get("podcast", {}) or {}
        podcasters = episode.get("podcasters", []) or []
        author = (
            podcast.get("author", "")
            or (podcasters[0].get("nickname", "") if podcasters else "")
            or "Unknown"
        )
        title = episode.get("title", "") or "Untitled"
        pubdate_raw = episode.get("pubDate", "") or ""
        pubdate, pubdate_ts = _parse_iso_datetime(pubdate_raw)
        description_raw = episode.get("description", "") or ""
        shownotes = episode.get("shownotes", "") or ""
        duration = int(episode.get("duration", 0) or 0)

        # Audio URL
        enclosure = episode.get("enclosure", {}) or {}
        audio_url = enclosure.get("url", "") or ""
        if not audio_url:
            raise RuntimeError("小宇宙页面中未找到音频 URL")

        logger.info(
            "Xiaoyuzhou episode: %s — %s (%s)",
            podcast.get("title", "Unknown Podcast"),
            title,
            author,
        )

        # Download audio — use podcast + episode title in filename
        # (eid is already in the bvid prefix added by the pipeline)
        safe_podcast = sanitize_filename_component(podcast.get("title", ""), 30)
        safe_title = sanitize_filename_component(title, 50)
        audio_name = f"{safe_podcast}_{safe_title}" if safe_podcast else safe_title
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / build_filename_component(
            audio_name,
            suffix=".m4a",
        )
        logger.info("Downloading audio from: [REDACTED_URL]")
        with httpx.stream(
            "GET", audio_url, headers={"User-Agent": _USER_AGENT}
        ) as stream:
            stream.raise_for_status()
            with open(audio_path, "wb") as f:
                for chunk in stream.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        logger.info("Audio downloaded: %.1f MB", file_size_mb)

        metadata = PlatformMetadata(
            platform=Platform.XIAOYUZHOU,
            platform_id=eid,
            title=f"{podcast.get('title', '')} — {title}"
            if podcast.get("title")
            else title,
            author=author,
            pubdate=pubdate,
            pubdate_timestamp=pubdate_ts,
            description=description_raw,
            duration_seconds=duration,
            extra={
                "podcast_title": podcast.get("title", ""),
                "podcasters": [
                    {"nickname": p.get("nickname", ""), "bio": p.get("bio", "")}
                    for p in podcasters
                ],
                "shownotes": shownotes,
            },
        )

        return audio_path, metadata
