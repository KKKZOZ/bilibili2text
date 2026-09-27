"""Shared, private credential storage for independent login and monitor processes."""

import json
import os
import tempfile
from pathlib import Path

COOKIE_FIELDS = ("SESSDATA", "bili_jct", "buvid3", "DedeUserID", "DedeUserID__ckMd5")
STORED_FIELDS = (*COOKIE_FIELDS, "refresh_token")


class InvalidLoginCredentials(ValueError):
    """Validation failure containing field names only, never credential values."""


def read_credentials(path: str) -> dict[str, str] | None:
    if not path:
        return None
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ValueError("无法读取 B 站登录凭据，请重新扫码登录") from None
    if not isinstance(raw, dict) or any(
        not isinstance(raw.get(key, ""), str) for key in STORED_FIELDS
    ):
        raise ValueError("B 站登录凭据格式错误，请重新扫码登录")
    return {key: raw.get(key, "") for key in STORED_FIELDS}


def save_credentials(path: str, values: dict[str, str]) -> None:
    """Atomically replace credentials; never partially overwrite a working login."""
    if not path:
        raise InvalidLoginCredentials("未配置 B 站凭据文件")
    missing = [
        key for key in ("SESSDATA", "bili_jct", "DedeUserID") if not values.get(key)
    ]
    if missing:
        raise InvalidLoginCredentials("登录结果缺少字段：" + ", ".join(missing))
    if any(not isinstance(values.get(key, ""), str) for key in STORED_FIELDS):
        raise InvalidLoginCredentials("登录凭据字段类型错误")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".bilibili-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({key: values.get(key, "") for key in STORED_FIELDS}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
