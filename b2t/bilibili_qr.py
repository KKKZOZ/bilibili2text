"""Web QR login with explicit status handling and response-cookie extraction."""

from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import httpx

from b2t.bilibili_credentials import COOKIE_FIELDS, InvalidLoginCredentials
from b2t.config import DEFAULT_BILIBILI_USER_AGENT


class LoginResponseError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("B 站登录接口返回非成功状态")


@dataclass
class LoginCredential:
    cookies: dict[str, str]
    ac_time_value: str

    def get_cookies(self):
        return dict(self.cookies)


class BilibiliQrLogin:
    BASE = "https://passport.bilibili.com/x/passport-login/web/qrcode"

    def __init__(self, *, transport=None):
        self.transport = transport
        self.key = ""
        self.qr = ""
        self.credential = None

    async def _request(self, action, params):
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=15,
            follow_redirects=False,
            headers={
                "User-Agent": DEFAULT_BILIBILI_USER_AGENT,
                "Referer": "https://www.bilibili.com/",
            },
        ) as client:
            response = await client.get(f"{self.BASE}/{action}", params=params)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise LoginResponseError(payload.get("code"))
            data = payload.get("data")
            if not isinstance(data, dict):
                raise TypeError("登录响应缺少 data")
            return response, data

    async def generate_qrcode(self):
        from qrcode_terminal import qr_terminal_str

        _, data = await self._request("generate", {"source": "main-fe-header"})
        key, url = data.get("qrcode_key"), data.get("url")
        if not isinstance(key, str) or not key or not isinstance(url, str) or not url:
            raise ValueError("二维码响应不完整")
        self.key = key
        self.qr = qr_terminal_str(url)

    def get_qrcode_terminal(self):
        return self.qr

    def has_done(self):
        return self.credential is not None

    def get_credential(self):
        if self.credential is None:
            raise ValueError("登录尚未完成")
        return self.credential

    async def check_state(self):
        response, data = await self._request(
            "poll", {"qrcode_key": self.key, "source": "main-fe-header"}
        )
        code = data.get("code")
        states = {86101: "scan", 86090: "confirm", 86038: "timeout"}
        if code in states:
            return SimpleNamespace(value=states[code])
        if code != 0:
            raise LoginResponseError(code)

        values = {}
        # Compatibility with older responses. Do not follow the callback URL or
        # unquote cookie values: SESSDATA may intentionally be percent-encoded.
        callback = data.get("url", "")
        if isinstance(callback, str):
            for part in urlsplit(callback).query.split("&"):
                key, _, value = part.partition("=")
                key = unquote(key)
                if key in COOKIE_FIELDS and value:
                    values[key] = value
        # Current login responses can deliver credentials only via Set-Cookie.
        # These take precedence over callback parameters.
        for cookie in response.cookies.jar:
            domain = cookie.domain.lstrip(".")
            if (
                domain == "bilibili.com" or domain.endswith(".bilibili.com")
            ) and cookie.name in COOKIE_FIELDS:
                values[cookie.name] = cookie.value
        missing = [
            key for key in ("SESSDATA", "bili_jct", "DedeUserID") if not values.get(key)
        ]
        if missing:
            raise InvalidLoginCredentials("登录成功响应缺少字段：" + ", ".join(missing))
        refresh = data.get("refresh_token", "")
        self.credential = LoginCredential(
            values, refresh if isinstance(refresh, str) else ""
        )
        return SimpleNamespace(value="done")
