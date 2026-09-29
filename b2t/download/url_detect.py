"""URL platform detection and ID extraction."""

import re
from urllib.parse import SplitResult, parse_qs, urlsplit

from b2t.download.platform import Platform

_BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_XIAOYUZHOU_EPISODE_PATH = re.compile(
    r"^/episode/([a-zA-Z0-9]{24})(?:/|$)", re.IGNORECASE
)
_XIMALAYA_ALBUM_PATH = re.compile(r"^/album/(\d+)(?:/|$)", re.IGNORECASE)
_XIMALAYA_SOUND_PATH = re.compile(r"^/sound/(\d+)(?:/|$)", re.IGNORECASE)
_XIMA_TV_PATH = re.compile(r"^/([a-zA-Z0-9_-]+)/?$", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;!?)]}>，。；！？）】》"

BILIBILI_SHORT_HOSTS = frozenset({"b23.tv", "www.b23.tv"})
XIAOYUZHOU_HOSTS = frozenset({"xiaoyuzhoufm.com", "www.xiaoyuzhoufm.com"})
XIMALAYA_HOSTS = frozenset({"ximalaya.com", "www.ximalaya.com", "m.ximalaya.com"})
XIMALAYA_SHORT_HOSTS = frozenset({"xima.tv", "www.xima.tv"})
YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)


def extract_youtube_id(parsed: SplitResult) -> str | None:
    """Accept single-video URLs only; never pass playlist/channel URLs to yt-dlp."""
    if (parsed.hostname or "").lower() not in YOUTUBE_HOSTS:
        return None
    if parsed.hostname.lower() in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/")
    elif parsed.path.rstrip("/") == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        candidate = values[0] if len(values) == 1 else ""
    else:
        match = re.fullmatch(r"/(?:shorts|embed|live)/([\w-]{11})/?", parsed.path)
        candidate = match.group(1) if match else ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def normalize_youtube_url(raw: str) -> str:
    parsed = parse_http_url(raw)
    video_id = extract_youtube_id(parsed) if parsed is not None else None
    if video_id is None:
        raise ValueError("请使用 YouTube 单个视频链接，不支持频道或播放列表")
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_http_url(raw: str) -> SplitResult | None:
    """Parse the first HTTP(S) URL in input and reject ambiguous authorities."""
    match = _HTTP_URL_PATTERN.search(raw.strip())
    if match is None:
        return None

    candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        return None

    return parsed


def _is_bilibili_host(hostname: str) -> bool:
    return (
        hostname == "bilibili.com"
        or hostname.endswith(".bilibili.com")
        or hostname in BILIBILI_SHORT_HOSTS
    )


def detect_platform(url: str) -> Platform | None:
    """Detect which platform a URL belongs to, or None if unknown."""
    url_clean = url.strip()
    if re.fullmatch(r"BV[a-zA-Z0-9]{10}", url_clean):
        return Platform.BILIBILI

    parsed = parse_http_url(url_clean)
    if parsed is None or parsed.hostname is None:
        return None

    hostname = parsed.hostname.lower()
    if extract_youtube_id(parsed):
        return Platform.YOUTUBE
    if _is_bilibili_host(hostname):
        return Platform.BILIBILI
    if hostname in XIAOYUZHOU_HOSTS and _XIAOYUZHOU_EPISODE_PATH.match(parsed.path):
        return Platform.XIAOYUZHOU
    if hostname in XIMALAYA_HOSTS and (
        _XIMALAYA_SOUND_PATH.match(parsed.path)
        or _XIMALAYA_ALBUM_PATH.match(parsed.path)
    ):
        return Platform.XIMALAYA
    if hostname in XIMALAYA_SHORT_HOSTS and _XIMA_TV_PATH.match(parsed.path):
        return Platform.XIMALAYA

    return None


def extract_platform_id(url: str, platform: Platform) -> str | None:
    """Extract a platform resource ID after validating the URL authority."""
    url_clean = url.strip()

    if platform == Platform.BILIBILI:
        if re.fullmatch(r"BV[a-zA-Z0-9]{10}", url_clean):
            return "BV" + url_clean[2:]

        parsed = parse_http_url(url_clean)
        if parsed is None or parsed.hostname is None:
            return None
        if not _is_bilibili_host(parsed.hostname.lower()):
            return None
        match = _BVID_PATTERN.search(f"{parsed.path}?{parsed.query}")
        if match is None:
            return None
        bvid = match.group(1)
        return "BV" + bvid[2:]

    parsed = parse_http_url(url_clean)
    if parsed is None or parsed.hostname is None:
        return None
    hostname = parsed.hostname.lower()

    if platform == Platform.YOUTUBE:
        return extract_youtube_id(parsed)

    if platform == Platform.XIAOYUZHOU:
        if hostname not in XIAOYUZHOU_HOSTS:
            return None
        match = _XIAOYUZHOU_EPISODE_PATH.match(parsed.path)
        return match.group(1) if match else None

    if platform == Platform.XIMALAYA:
        if hostname in XIMALAYA_HOSTS:
            match = _XIMALAYA_SOUND_PATH.match(parsed.path)
            if match:
                return match.group(1)
            match = _XIMALAYA_ALBUM_PATH.match(parsed.path)
            return match.group(1) if match else None
        if hostname in XIMALAYA_SHORT_HOSTS:
            match = _XIMA_TV_PATH.match(parsed.path)
            return match.group(1) if match else None

    return None
