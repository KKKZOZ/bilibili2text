import httpx
import pytest

from b2t.download.platform import Platform
from b2t.download.url_detect import detect_platform, extract_platform_id
from b2t.download import ximalaya


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("BV1ABcsztEcY", Platform.BILIBILI),
        (
            "分享：https://www.bilibili.com/video/BV1ABcsztEcY。",
            Platform.BILIBILI,
        ),
        (
            "https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2",
            Platform.XIAOYUZHOU,
        ),
        ("https://www.ximalaya.com/sound/123456", Platform.XIMALAYA),
        ("https://xima.tv/Abc_123", Platform.XIMALAYA),
    ],
)
def test_detect_platform_uses_parsed_hostname(url: str, platform: Platform) -> None:
    assert detect_platform(url) == platform


@pytest.mark.parametrize(
    "url",
    [
        "https://ximalaya.com.evil.example/sound/123456",
        "https://evil.example/ximalaya.com/sound/123456",
        "https://xima.tv.evil.example/Abc_123",
        "https://evil.example/xima.tv/Abc_123",
        "https://user@xima.tv/Abc_123",
        "https://xima.tv:8443/Abc_123",
        "http://127.0.0.1/xima.tv/Abc_123",
    ],
)
def test_detect_platform_rejects_spoofed_ximalaya_urls(url: str) -> None:
    assert detect_platform(url) is None
    assert extract_platform_id(url, Platform.XIMALAYA) is None


def test_resolve_direct_sound_url_returns_canonical_url_and_stable_id() -> None:
    assert ximalaya.resolve_ximalaya_sound_url(
        "https://m.ximalaya.com/sound/123456?source=share"
    ) == ("https://www.ximalaya.com/sound/123456", "123456")


def test_resolve_album_url_is_explicitly_rejected() -> None:
    with pytest.raises(ValueError, match="不支持喜马拉雅专辑链接"):
        ximalaya.resolve_ximalaya_sound_url("https://www.ximalaya.com/album/123456")


def test_resolve_short_url_requires_https() -> None:
    with pytest.raises(ValueError, match="短链仅支持 HTTPS"):
        ximalaya.resolve_ximalaya_sound_url("http://xima.tv/Abc_123")


@pytest.mark.parametrize("head_status", [403, 405])
def test_short_url_head_failure_falls_back_to_get(
    monkeypatch: pytest.MonkeyPatch,
    head_status: int,
) -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if request.method == "HEAD":
            return httpx.Response(head_status, request=request)
        if request.url.host == "xima.tv":
            return httpx.Response(
                302,
                headers={"location": "https://www.ximalaya.com/sound/987654"},
                request=request,
            )
        return httpx.Response(200, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ximalaya, "_create_redirect_client", lambda: client)
    monkeypatch.setattr(
        ximalaya,
        "_resolve_hostname_addresses",
        lambda hostname: {"93.184.216.34"},
    )

    assert ximalaya.resolve_ximalaya_sound_url("https://xima.tv/Abc_123") == (
        "https://www.ximalaya.com/sound/987654",
        "987654",
    )
    assert requests == [
        ("HEAD", "https://xima.tv/Abc_123"),
        ("GET", "https://xima.tv/Abc_123"),
        ("GET", "https://www.ximalaya.com/sound/987654"),
    ]


def test_short_url_rejects_private_redirect_destination_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://www.ximalaya.com/sound/987654"},
            request=request,
        )

    def resolve_addresses(hostname: str) -> set[str]:
        if hostname == "xima.tv":
            return {"93.184.216.34"}
        return {"127.0.0.1"}

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ximalaya, "_create_redirect_client", lambda: client)
    monkeypatch.setattr(
        ximalaya,
        "_resolve_hostname_addresses",
        resolve_addresses,
    )

    with pytest.raises(ValueError, match="拒绝访问非公网"):
        ximalaya.resolve_ximalaya_sound_url("https://xima.tv/Abc_123")

    assert requests == ["https://xima.tv/Abc_123"]


def test_short_url_rejects_untrusted_redirect_host_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/sound/987654"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ximalaya, "_create_redirect_client", lambda: client)
    monkeypatch.setattr(
        ximalaya,
        "_resolve_hostname_addresses",
        lambda hostname: {"93.184.216.34"},
    )

    with pytest.raises(ValueError, match="重定向到不可信主机"):
        ximalaya.resolve_ximalaya_sound_url("https://xima.tv/Abc_123")

    assert requests == ["https://xima.tv/Abc_123"]


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1"],
)
def test_public_hostname_check_rejects_non_global_addresses(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    monkeypatch.setattr(
        ximalaya,
        "_resolve_hostname_addresses",
        lambda hostname: {address},
    )

    with pytest.raises(ValueError, match="拒绝访问非公网"):
        ximalaya._ensure_public_hostname("xima.tv")
