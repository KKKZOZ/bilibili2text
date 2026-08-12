"""Ximalaya downloader with safe short-link resolution."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from b2t.download.platform import (
    Platform,
    PlatformDownloader,
    PlatformMetadata,
    build_filename_component,
    sanitize_filename_component,
)
from b2t.download.url_detect import (
    XIMALAYA_HOSTS,
    XIMALAYA_SHORT_HOSTS,
    extract_platform_id,
    parse_http_url,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HTTP_TIMEOUT = httpx.Timeout(30.0, read=600.0)
_MAX_REDIRECTS = 8
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_TRUSTED_REDIRECT_HOSTS = XIMALAYA_HOSTS | XIMALAYA_SHORT_HOSTS


def _resolve_hostname_addresses(hostname: str) -> set[str]:
    """Resolve all addresses for a hostname so private destinations can be blocked."""
    try:
        return {str(ipaddress.ip_address(hostname))}
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"无法解析喜马拉雅链接主机: {hostname}") from exc

    return {item[4][0].split("%", 1)[0] for item in addr_info}


def _ensure_public_hostname(hostname: str) -> None:
    addresses = _resolve_hostname_addresses(hostname)
    if not addresses:
        raise ValueError(f"喜马拉雅链接主机没有可用地址: {hostname}")

    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError(
                f"喜马拉雅链接主机返回了无效地址: {hostname} -> {raw_address}"
            ) from exc
        if not address.is_global:
            raise ValueError(f"拒绝访问非公网喜马拉雅链接地址: {hostname} -> {address}")


def _validate_redirect_url(url: str) -> str:
    """Validate a redirect target before issuing a request to it."""
    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"无效的喜马拉雅重定向 URL: {url}") from exc

    hostname = parsed.hostname.lower() if parsed.hostname else None
    if parsed.scheme.lower() != "https" or hostname is None:
        raise ValueError(f"喜马拉雅重定向仅允许绝对 HTTPS URL: {url}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"喜马拉雅重定向 URL 不允许包含用户信息: {url}")
    if port not in {None, 443}:
        raise ValueError(f"喜马拉雅重定向 URL 不允许自定义端口: {url}")
    if hostname not in _TRUSTED_REDIRECT_HOSTS:
        raise ValueError(f"喜马拉雅重定向到不可信主机: {hostname}")

    _ensure_public_hostname(hostname)
    return urlunsplit(parsed._replace(fragment=""))


def _create_redirect_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
        follow_redirects=False,
    )


def _follow_safe_redirects(
    client: httpx.Client,
    method: str,
    start_url: str,
) -> tuple[str, int]:
    """Follow redirects manually, validating every target before requesting it."""
    current_url = start_url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        current_url = _validate_redirect_url(current_url)
        request = client.build_request(method, current_url)
        response = client.send(request, stream=True, follow_redirects=False)
        status_code = response.status_code
        location = response.headers.get("location")
        response.close()

        if status_code not in _REDIRECT_STATUS_CODES:
            return current_url, status_code
        if not location:
            raise RuntimeError("喜马拉雅短链返回重定向状态但缺少 Location")
        if redirect_count == _MAX_REDIRECTS:
            break
        current_url = urljoin(current_url, location)

    raise RuntimeError(f"喜马拉雅短链重定向次数超过 {_MAX_REDIRECTS} 次")


def _extract_sound_id(url: str) -> str | None:
    parsed = parse_http_url(url)
    if parsed is None or parsed.hostname is None:
        return None
    if parsed.hostname.lower() not in XIMALAYA_HOSTS:
        return None
    if not parsed.path.lower().startswith("/sound/"):
        return None
    return extract_platform_id(url, Platform.XIMALAYA)


def _raise_unsupported_ximalaya_url(url: str) -> None:
    parsed = parse_http_url(url)
    if (
        parsed is not None
        and parsed.hostname is not None
        and parsed.hostname.lower() in XIMALAYA_HOSTS
        and parsed.path.lower().startswith("/album/")
    ):
        raise ValueError("暂不支持喜马拉雅专辑链接，请提供具体的 sound 单集链接")
    raise ValueError(f"无法从喜马拉雅链接中提取 sound ID: {url}")


def _resolve_xima_short_url(url: str) -> str:
    logger.info("Resolving Ximalaya short link: %s", url)
    with _create_redirect_client() as client:
        try:
            head_url, head_status = _follow_safe_redirects(client, "HEAD", url)
        except httpx.HTTPError as exc:
            logger.info("Ximalaya HEAD resolution failed, retrying with GET: %s", exc)
        else:
            if 200 <= head_status < 400 and _extract_sound_id(head_url) is not None:
                logger.info("Resolved to: %s", head_url)
                return head_url
            logger.info(
                "Ximalaya HEAD did not resolve to a usable sound URL "
                "(status=%s); retrying with GET",
                head_status,
            )

        final_url, final_status = _follow_safe_redirects(client, "GET", url)

    if not 200 <= final_status < 400:
        raise RuntimeError(f"喜马拉雅短链解析失败，HTTP 状态码: {final_status}")
    logger.info("Resolved to (GET): %s", final_url)
    return final_url


def resolve_ximalaya_sound_url(url: str) -> tuple[str, str]:
    """Return a canonical Ximalaya sound URL and stable track ID.

    Direct ``ximalaya.com/sound`` URLs are normalized without a network request.
    Exact ``xima.tv`` hosts are resolved through a validated redirect chain.
    Album URLs are rejected because their track ordering is not a stable contract.
    """
    parsed = parse_http_url(url)
    if parsed is None or parsed.hostname is None:
        _raise_unsupported_ximalaya_url(url)

    hostname = parsed.hostname.lower()
    if hostname in XIMALAYA_HOSTS:
        track_id = _extract_sound_id(parsed.geturl())
        if track_id is None:
            _raise_unsupported_ximalaya_url(parsed.geturl())
        return f"https://www.ximalaya.com/sound/{track_id}", track_id

    if hostname not in XIMALAYA_SHORT_HOSTS:
        _raise_unsupported_ximalaya_url(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("喜马拉雅短链仅支持 HTTPS")
    if extract_platform_id(parsed.geturl(), Platform.XIMALAYA) is None:
        _raise_unsupported_ximalaya_url(parsed.geturl())

    resolved_url = _resolve_xima_short_url(parsed.geturl())
    track_id = _extract_sound_id(resolved_url)
    if track_id is None:
        _raise_unsupported_ximalaya_url(resolved_url)
    return f"https://www.ximalaya.com/sound/{track_id}", track_id


def _resolve_ximalaya_url(url: str) -> str:
    """Backward-compatible wrapper returning only the canonical sound URL."""
    resolved_url, _ = resolve_ximalaya_sound_url(url)
    return resolved_url


def _parse_create_date_format(raw: str) -> tuple[str, int]:
    """Parse ximalaya createDateFormat like '2025-06-26' or '2025-06'."""
    cleaned = (raw or "").strip()
    parts = cleaned.split("-")
    if len(parts) == 3:
        return cleaned, 0
    if len(parts) == 2:
        return f"{cleaned}-01", 0
    return cleaned, 0


def _http_get_json(url: str) -> dict:
    resp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"喜马拉雅接口返回非 JSON 对象: {url}")
    return data


def _download_audio_file(audio_url: str, audio_path: Path) -> None:
    if audio_url.startswith("http://"):
        audio_url = "https://" + audio_url[7:]

    logger.info("Downloading audio from: [REDACTED_URL]")
    with httpx.stream(
        "GET",
        audio_url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as stream:
        stream.raise_for_status()
        with open(audio_path, "wb") as file_obj:
            for chunk in stream.iter_bytes(chunk_size=1024 * 1024):
                file_obj.write(chunk)

    file_size_mb = audio_path.stat().st_size / 1024 / 1024
    logger.info("Audio downloaded: %.1f MB", file_size_mb)


def _fetch_track_audio_url(track_id: str | int) -> str:
    audio_api_url = f"https://www.ximalaya.com/revision/play/tracks?trackIds={track_id}"
    audio_data = _http_get_json(audio_api_url)
    if audio_data.get("ret") != 200:
        raise RuntimeError(f"喜马拉雅音频地址获取失败: {audio_data.get('msg')}")

    tracks_audio = audio_data.get("data", {}).get("tracksForAudioPlay", [])
    if not tracks_audio:
        raise RuntimeError("喜马拉雅未返回音频播放地址")

    audio_url = tracks_audio[0].get("src", "")
    if not audio_url:
        raise RuntimeError("喜马拉雅音频地址为空")
    return str(audio_url)


def _fetch_track_info(track_id: str | int) -> dict:
    """Best-effort track detail for title/author when only a sound URL is given."""
    detail_url = f"https://www.ximalaya.com/revision/track/simple?trackId={track_id}"
    try:
        data = _http_get_json(detail_url)
    except Exception as exc:
        logger.warning(
            "Failed to fetch Ximalaya track detail for %s: %s", track_id, exc
        )
        return {}

    if data.get("ret") != 200:
        logger.warning(
            "Ximalaya track detail failed for %s: %s", track_id, data.get("msg")
        )
        return {}

    payload = data.get("data") or {}
    return payload if isinstance(payload, dict) else {}


class XimalayaDownloader(PlatformDownloader):
    """Download audio and metadata from a concrete Ximalaya sound URL."""

    def download_audio(
        self, url: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        _, track_id = resolve_ximalaya_sound_url(url)
        return self._download_sound(track_id, output_dir)

    def _download_sound(
        self, track_id: str, output_dir: Path
    ) -> tuple[Path, PlatformMetadata]:
        logger.info("Fetching Ximalaya sound/track: %s", track_id)

        track_info = _fetch_track_info(track_id)
        track_title = (
            str(track_info.get("title") or track_info.get("trackTitle") or "").strip()
            or f"track_{track_id}"
        )
        album_title = str(
            track_info.get("albumTitle")
            or (track_info.get("album") or {}).get("title")
            or ""
        ).strip()
        author = (
            str(
                track_info.get("nickname")
                or track_info.get("anchorName")
                or (track_info.get("user") or {}).get("nickname")
                or "Unknown"
            ).strip()
            or "Unknown"
        )
        duration = int(
            track_info.get("duration") or track_info.get("trackDuration") or 0
        )
        create_date = str(
            track_info.get("createDateFormat") or track_info.get("createdAt") or ""
        )
        description = str(track_info.get("intro") or track_info.get("richIntro") or "")

        audio_url = _fetch_track_audio_url(track_id)

        safe_album = sanitize_filename_component(album_title, 30) if album_title else ""
        safe_track = sanitize_filename_component(track_title, 50)
        audio_name = f"{safe_album}_{safe_track}" if safe_album else safe_track
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / build_filename_component(
            audio_name,
            suffix=".m4a",
        )
        _download_audio_file(audio_url, audio_path)

        pubdate_str, _ = _parse_create_date_format(create_date)
        metadata = PlatformMetadata(
            platform=Platform.XIMALAYA,
            platform_id=str(track_id),
            title=f"{album_title} — {track_title}" if album_title else track_title,
            author=author,
            pubdate=pubdate_str,
            duration_seconds=duration,
            description=description,
            extra={
                "album_title": album_title,
                "track_id": track_id,
                "track_title": track_title,
                "source": "sound",
            },
        )
        return audio_path, metadata


__all__ = ["XimalayaDownloader", "resolve_ximalaya_sound_url"]
