import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from b2t.bilibili_credentials import read_credentials, save_credentials
from b2t.bilibili_login import terminal_login
from b2t.config import BilibiliConfig, build_bilibili_cookie

VALUES = {"SESSDATA": "new-session", "bili_jct": "new-csrf", "DedeUserID": "123"}


class FakeLogin:
    def __init__(self, events=None):
        self.events = list(events or ["scan", "confirm", "done"])
        self.done = False

    async def generate_qrcode(self):
        pass

    def get_qrcode_terminal(self):
        return "TEST QR BLOCKS"

    def has_done(self):
        return self.done

    async def check_state(self):
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        self.done = event == "done"
        return SimpleNamespace(value=event)

    def get_credential(self):
        return SimpleNamespace(
            get_cookies=lambda: VALUES, ac_time_value="refresh-secret"
        )


@pytest.fixture
def config(tmp_path):
    return SimpleNamespace(
        bilibili=BilibiliConfig(
            credentials_file=str(tmp_path / "credentials.json"),
            SESSDATA="manual",
            DedeUserID__ckMd5="old-account-hash",
            buvid3="configured-device",
        )
    )


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    async def sleep(_):
        pass

    monkeypatch.setattr("b2t.bilibili_login.asyncio.sleep", sleep)


def run(config, login):
    output = io.StringIO()
    code = asyncio.run(
        terminal_login(config, Console(file=output, width=120), factory=lambda: login)
    )
    return code, output.getvalue()


def test_terminal_confirmation_saves_and_exits(config):
    code, output = run(config, FakeLogin())
    assert code == 0
    assert "TEST QR BLOCKS" in output
    assert "已扫码" in output
    assert "登录成功" in output
    assert "new-session" not in output
    assert "refresh-secret" not in output
    assert (
        read_credentials(config.bilibili.credentials_file)["refresh_token"]
        == "refresh-secret"
    )
    assert Path(config.bilibili.credentials_file).stat().st_mode & 0o777 == 0o600
    cookie = build_bilibili_cookie(config)
    assert "SESSDATA=new-session" in cookie
    assert "buvid3=configured-device" in cookie
    assert "old-account-hash" not in cookie
    save_credentials(config.bilibili.credentials_file, {**VALUES, "SESSDATA": "second"})
    assert "SESSDATA=second" in build_bilibili_cookie(config)


def test_expiration_preserves_previous_login(config):
    save_credentials(config.bilibili.credentials_file, VALUES)
    code, output = run(config, FakeLogin(["timeout"]))
    assert code == 1
    assert "已过期" in output
    assert (
        read_credentials(config.bilibili.credentials_file)["SESSDATA"] == "new-session"
    )


def test_transient_timeout_retries(config):
    code, output = run(config, FakeLogin([TimeoutError("secret URL"), "done"]))
    assert code == 0
    assert "超时" in output
    assert "稍后自动重试" in output
    assert "secret URL" not in output


def test_repeated_failure_reports_safe_error_code(config, caplog):
    class UpstreamFailure(Exception):
        code = -123

    code, output = run(config, FakeLogin([UpstreamFailure("SESSDATA=secret")] * 3))
    assert code == 1
    assert "UpstreamFailure" in output
    assert "-123" in output
    assert "连续查询失败" in output
    assert "SESSDATA=secret" not in output + caplog.text
    assert read_credentials(config.bilibili.credentials_file) is None


def test_save_failure_is_distinct_from_network_failure(config, monkeypatch):
    def fail(*args):
        raise PermissionError("secret-path")

    monkeypatch.setattr("b2t.bilibili_login.save_credentials", fail)
    code, output = run(config, FakeLogin(["done"]))
    assert code == 1
    assert "写入权限" in output
    assert "secret-path" not in output


def test_generation_error_is_sanitized(config):
    class BrokenLogin(FakeLogin):
        async def generate_qrcode(self):
            raise RuntimeError("private-login-key")

    code, output = run(config, BrokenLogin())
    assert code == 1
    assert "RuntimeError" in output
    assert "private-login-key" not in output


def test_atomic_write_failure_preserves_login(config, monkeypatch):
    save_credentials(config.bilibili.credentials_file, VALUES)

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr("b2t.bilibili_credentials.os.replace", fail)
    with pytest.raises(OSError):
        save_credentials(
            config.bilibili.credentials_file, {**VALUES, "SESSDATA": "other"}
        )
    assert (
        read_credentials(config.bilibili.credentials_file)["SESSDATA"] == "new-session"
    )
    assert not list(Path(config.bilibili.credentials_file).parent.glob(".bilibili-*"))


def test_incomplete_credentials_never_overwrite_existing_login(config):
    save_credentials(config.bilibili.credentials_file, VALUES)
    with pytest.raises(ValueError):
        save_credentials(config.bilibili.credentials_file, {"SESSDATA": "incomplete"})
    assert (
        read_credentials(config.bilibili.credentials_file)["SESSDATA"] == "new-session"
    )


@pytest.mark.parametrize("source", ["headers", "url", "both"])
def test_login_response_credentials(config, source):
    import httpx

    from b2t.bilibili_qr import BilibiliQrLogin

    states = iter([86101, 86090, 0])

    def handler(request):
        if request.url.path.endswith("generate"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"qrcode_key": "test-key", "url": "https://example.com/qr"},
                },
            )
        assert request.url.params["qrcode_key"] == "test-key"
        code = next(states)
        data = {"code": code}
        headers = []
        if code == 0:
            data.update(
                url="https://passport.bilibili.com/callback",
                refresh_token="test-refresh",
            )
            if source in {"url", "both"}:
                data["url"] += (
                    "?SESSDATA=url-session%2Cabc&bili_jct=csrf&DedeUserID=123"
                )
            if source in {"headers", "both"}:
                headers = [
                    (
                        "Set-Cookie",
                        f"{key}={value}; Domain=.bilibili.com; Path=/; Secure; HttpOnly",
                    )
                    for key, value in {
                        "SESSDATA": "header-session%2Cabc",
                        "bili_jct": "csrf",
                        "DedeUserID": "123",
                    }.items()
                ]
        return httpx.Response(200, json={"code": 0, "data": data}, headers=headers)

    code, output = run(config, BilibiliQrLogin(transport=httpx.MockTransport(handler)))
    assert code == 0
    saved = read_credentials(config.bilibili.credentials_file)
    assert saved["SESSDATA"] == (
        "url-session%2Cabc" if source == "url" else "header-session%2Cabc"
    )
    assert saved["refresh_token"] == "test-refresh"
    assert "session%2Cabc" not in output


@pytest.mark.parametrize("code", [86095, None, -1])
def test_unknown_poll_status_never_becomes_success(config, code):
    import httpx

    from b2t.bilibili_qr import BilibiliQrLogin

    def handler(request):
        if request.url.path.endswith("generate"):
            data = {"qrcode_key": "test-key", "url": "https://example.com/qr"}
        else:
            data = {
                "code": code,
                "url": "https://example.com/?SESSDATA=s&bili_jct=c&DedeUserID=1",
            }
        return httpx.Response(200, json={"code": 0, "data": data})

    result, output = run(
        config, BilibiliQrLogin(transport=httpx.MockTransport(handler))
    )
    assert result == 1
    assert "LoginResponseError" in output
    assert read_credentials(config.bilibili.credentials_file) is None


def test_compact_qr_preserves_modules_and_quiet_zone():
    import re

    import qrcode
    from qrcode_terminal import qr_terminal_str

    from b2t.bilibili_login import compact_terminal_qr

    payload = "https://example.com/login?test=" + "a" * 64
    original = qr_terminal_str(payload)
    compact = compact_terminal_qr(original)
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in compact.splitlines()]
    qr = qrcode.QRCode(version=1, border=4)
    qr.add_data(payload)
    qr.make()
    expected = qr.get_matrix()
    decoded = []
    for line in lines:
        decoded.append([char in "▀█" for char in line])
        decoded.append([char in "▄█" for char in line])
    assert decoded[: len(expected)] == expected
    assert not any(cell for row in decoded[len(expected) :] for cell in row)
    original_width = len(re.sub(r"\x1b\[[0-9;]*m", "", original.splitlines()[0]))
    assert len(lines[0]) < original_width
    assert len(lines) < len(original.splitlines())


def test_missing_login_fields_report_names_once_and_preserve_old_credentials(config):
    save_credentials(config.bilibili.credentials_file, VALUES)

    class IncompleteLogin(FakeLogin):
        def get_credential(self):
            return SimpleNamespace(
                get_cookies=lambda: {"SESSDATA": "private-session"},
                ac_time_value="private-refresh",
            )

    code, output = run(config, IncompleteLogin(["done"]))
    assert code == 1
    assert "bili_jct" in output
    assert "DedeUserID" in output
    assert "private-session" not in output
    assert "private-refresh" not in output
    assert "稍后自动重试" not in output
    assert (
        read_credentials(config.bilibili.credentials_file)["SESSDATA"]
        == VALUES["SESSDATA"]
    )
