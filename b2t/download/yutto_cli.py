"""Download Bilibili audio using yutto"""

import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

from b2t.download.metadata import VideoMetadata, get_video_metadata

logger = logging.getLogger(__name__)

_BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_TARGET_ID_PAGE_PATTERN = re.compile(
    r"BV[0-9A-Za-z]{10}_p([1-9][0-9]*)(?:[-_/]|$)", re.IGNORECASE
)
_B23_SHORT_URL_PATTERN = re.compile(r"b23\.tv/", re.IGNORECASE)
_HTTP_URL_PATTERN = re.compile(r"https?://\S+")


def extract_bvid(raw: str) -> str | None:
    """Extract a BV ID from input, returns None on failure."""
    match = _BVID_PATTERN.search(raw.strip())
    if match is None:
        return None
    bvid = match.group(1)
    return "BV" + bvid[2:]


def extract_bilibili_page(raw: str) -> int | None:
    """Extract a positive Bilibili multipart page number from a URL."""
    url_match = _HTTP_URL_PATTERN.search(raw.strip())
    target = url_match.group(0) if url_match else raw.strip()
    try:
        values = parse_qs(urlsplit(target).query).get("p", [])
    except ValueError:
        return None
    if not values or not values[0].isdigit():
        return None
    page = int(values[0])
    return page if page > 0 else None


def extract_bilibili_target_id(raw: str) -> str | None:
    """Build the storage identity for a video, separating multipart pages."""
    bvid = extract_bvid(raw)
    if bvid is None:
        return None
    page = extract_bilibili_page(raw)
    if page is None or page == 1:
        return bvid
    return f"{bvid}_p{page}"


def extract_bilibili_page_from_target_id(raw: str) -> int | None:
    """Extract a multipart page from an internal transcription or run ID."""
    match = _TARGET_ID_PAGE_PATTERN.search(raw.strip())
    return int(match.group(1)) if match else None


def _resolve_b23_short_url(url: str, timeout: float = 5.0) -> str:
    """Resolve b23.tv short URL, follow redirects and return the real URL. Returns original URL on failure."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        final = resp.url
        logger.debug("b23.tv 解析: %s -> %s", url, final)
        return final
    except Exception as exc:
        logger.warning("解析 b23.tv 短链接失败: %s，继续使用原始 URL", exc)
        return url


def normalize_bilibili_target(raw: str) -> str:
    """Normalize input to a target string that yutto can process directly.

    Supported input formats:
    - Full Bilibili URL (with query params)
    - Plain BV ID
    - b23.tv short URL (auto-follows redirects to resolve)
    - Bilibili default share text (e.g. "title-Bilibili" https://b23.tv/xxx)
    """
    target = raw.strip()
    if not target:
        raise ValueError("URL 不能为空")

    # Extract URL from share text (handles "title-Bilibili" https://... format)
    url_match = _HTTP_URL_PATTERN.search(target)
    if url_match:
        target = url_match.group(0)

    # Resolve b23.tv short URL
    if _B23_SHORT_URL_PATTERN.search(target):
        target = _resolve_b23_short_url(target)

    bvid = extract_bvid(target)
    if bvid is None:
        return target

    normalized = f"https://www.bilibili.com/video/{bvid}"
    page = extract_bilibili_page(target)
    if page is not None:
        return f"{normalized}?p={page}"
    return normalized


def download_audio(
    url: str,
    output_dir: Path | str,
    audio_quality: str = "30216",
    fetch_metadata: bool = True,
) -> tuple[Path, VideoMetadata | None]:
    """Download audio file using yutto

    Args:
        url: Bilibili video URL
        output_dir: Output directory
        audio_quality: Audio quality code, default 30216
        fetch_metadata: Whether to fetch video metadata

    Returns:
        (Audio file path, Video metadata)
        Metadata is None if fetch_metadata is False or fetching fails

    Raises:
        FileNotFoundError: Downloaded audio file not found
        subprocess.CalledProcessError: yutto download failed
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_target = normalize_bilibili_target(url)
    logger.info("正在从 %s 下载音频...", normalized_target)

    # Fetch metadata (if needed)
    metadata = None
    if fetch_metadata:
        bvid = extract_bvid(normalized_target)
        if bvid:
            try:
                metadata = get_video_metadata(bvid)
            except Exception as e:
                logger.warning("Failed to fetch video metadata: %s", e)

    cmd = [
        "yutto",
        normalized_target,
        "--audio-only",
        "--audio-quality",
        audio_quality,
        "--dir",
        str(output_dir),
    ]

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    logger.debug("yutto stdout: %s", result.stdout)
    logger.info("Download complete")

    # Find downloaded audio file
    audio_files = (
        list(output_dir.glob("*.m4a"))
        + list(output_dir.glob("*.mp3"))
        + list(output_dir.glob("*.flac"))
    )

    if not audio_files:
        raise FileNotFoundError(f"No downloaded audio files found: {output_dir}")

    audio_file = audio_files[0]
    logger.info("Audio file: %s", audio_file)

    return audio_file, metadata
