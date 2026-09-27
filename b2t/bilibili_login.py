"""Bilibili login helpers and terminal flow, independent of HTTP services."""

import asyncio
import logging
import re
import time
import traceback
from pathlib import Path

import httpx
from rich.console import Console

from b2t.bilibili_credentials import (
    COOKIE_FIELDS,
    InvalidLoginCredentials,
    save_credentials,
)
from b2t.config import AppConfig

logger = logging.getLogger(__name__)


def _login_error(exc: Exception, stage: str) -> str:
    # SDK exception messages/raw responses can contain the authenticated callback
    # URL. Report only the class and numeric status, never str(exc) or a traceback.
    kind = type(exc).__name__
    code = getattr(exc, "code", None)
    suffix = f"，接口代码 {code}" if type(code) is int else ""
    frames = traceback.extract_tb(exc.__traceback__)
    location = ""
    if frames:
        frame = frames[-1]
        location = f"，位置={Path(frame.filename).name}:{frame.lineno} ({frame.name})"
    logger.warning(
        "B 站扫码登录失败：阶段=%s，类型=%s%s%s", stage, kind, suffix, location
    )
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "B 站登录接口响应超时，请重试查询；二维码有效期内无需重新扫码"
    if isinstance(exc, (KeyError, IndexError, AttributeError)):
        return f"登录响应解析失败（{kind}{suffix}），请重新生成二维码"
    return f"{stage}失败（{kind}{suffix}），请重试或重新生成二维码"


def _new_login():
    from b2t.bilibili_qr import BilibiliQrLogin

    return BilibiliQrLogin()


def compact_terminal_qr(rendered: str) -> str:
    """Pack the SDK's two-column squares into half-block terminal characters."""
    pattern = re.compile(r"\x1b\[0;37;4([07])m  ")
    rows = []
    for line in rendered.splitlines():
        cells = pattern.findall(line)
        if not cells or pattern.sub("", line).replace("\x1b[0m", ""):
            # Preserve compatibility if the upstream renderer changes format.
            return rendered
        rows.append([cell == "0" for cell in cells])
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        return rendered
    # The SDK renderer has a one-module border; retain a four-module quiet zone.
    width = len(rows[0]) + 6
    blank = [False] * width
    rows = [blank] * 3 + [[False] * 3 + row + [False] * 3 for row in rows] + [blank] * 3
    if len(rows) % 2:
        rows.append(blank)
    output = []
    blocks = (" ", "▀", "▄", "█")
    for index in range(0, len(rows), 2):
        line = "".join(
            blocks[int(top) + 2 * int(bottom)]
            for top, bottom in zip(rows[index], rows[index + 1], strict=True)
        )
        output.append("\x1b[0;30;47m" + line + "\x1b[0m")
    return "\n".join(output)


async def terminal_login(
    config: AppConfig, console: Console, *, factory=_new_login
) -> int:
    """Show a QR code over SSH, await confirmation, persist credentials and exit."""
    try:
        login = factory()
        console.print("正在获取 B 站登录二维码…")
        await asyncio.wait_for(login.generate_qrcode(), timeout=30)
        console.print("请用哔哩哔哩 App 扫码，并在手机上确认登录。")
        # Half-blocks represent two module rows per line without losing QR data.
        console.file.write(compact_terminal_qr(login.get_qrcode_terminal()) + "\n")
        console.file.flush()
        console.print("等待扫码…（二维码 3 分钟内有效，Ctrl+C 取消）")
    except Exception as exc:  # noqa: BLE001 -- SDK messages may expose credentials.
        console.print(_login_error(exc, "获取二维码"), markup=False)
        return 1

    deadline = time.monotonic() + 180
    previous = "scan"
    failures = 0
    while time.monotonic() < deadline:
        stage = "查询登录状态"
        try:
            if login.has_done():
                state = "done"
            else:
                event = await asyncio.wait_for(login.check_state(), timeout=20)
                state = event.value
            if state == "done":
                stage = "提取登录凭据"
                credential = login.get_credential()
                cookies = credential.get_cookies()
                values = {key: cookies.get(key, "") for key in COOKIE_FIELDS}
                values["refresh_token"] = credential.ac_time_value or ""
                try:
                    stage = "保存登录凭据"
                    save_credentials(config.bilibili.credentials_file, values)
                except InvalidLoginCredentials as exc:
                    console.print(
                        f"登录凭据校验失败：{exc}。旧凭据未修改。", markup=False
                    )
                    return 1
                except OSError:
                    console.print("无法保存登录凭据，请检查凭据目录的写入权限。")
                    return 1
                console.print(
                    "登录成功，凭据已保存。monitor 下一次请求会自动使用新凭据。"
                )
                return 0
            if state == "timeout":
                break
            if state not in {"scan", "confirm"}:
                raise ValueError("未知扫码状态")
            if state != previous:
                console.print(
                    "已扫码，请在手机上确认登录。"
                    if state == "confirm"
                    else "等待扫码…"
                )
                previous = state
            failures = 0
        except InvalidLoginCredentials as exc:
            console.print(f"登录凭据校验失败：{exc}。旧凭据未修改。", markup=False)
            return 1
        except Exception as exc:  # noqa: BLE001 -- Show only sanitized diagnostics.
            failures += 1
            console.print(_login_error(exc, stage), markup=False)
            if failures >= 3:
                console.print("连续查询失败，请重新运行登录命令。")
                return 1
            console.print("稍后自动重试…")
        await asyncio.sleep(2.5)
    console.print("二维码已过期，请重新运行登录命令。")
    return 1
