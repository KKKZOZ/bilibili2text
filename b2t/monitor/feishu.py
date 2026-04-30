"""Feishu notification helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from b2t.config import FeishuConfig

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """Send notifications to Feishu via webhook or app credentials."""

    def __init__(
        self,
        config: FeishuConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._owns_client = client is None
        self._tenant_access_token: str | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def is_enabled(self) -> bool:
        return self.config.mode != "disabled"

    def send_card(self, title: str, markdown_content: str) -> bool:
        if not self.is_enabled():
            logger.info("[Mock飞书消息] %s\n%s", title, markdown_content)
            return False

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"{self.config.title_prefix} | {title}",
                },
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown_content,
                }
            ],
        }

        if self.config.mode == "webhook":
            return self._send_webhook_card(card)
        return self._send_app_card(card)

    def send_image_card(self, title: str, image_paths: list[Path | str]) -> bool:
        if not self.is_enabled():
            logger.info("[Mock飞书图片消息] %s\n%s", title, image_paths)
            return False

        image_keys: list[str] = []
        for image_path in image_paths:
            image_key = self.upload_image(image_path)
            if image_key is None:
                logger.error("飞书图片上传失败: %s", image_path)
                return False
            image_keys.append(image_key)

        elements = [
            {
                "tag": "img",
                "img_key": image_key,
                "alt": {
                    "tag": "plain_text",
                    "content": title,
                },
            }
            for image_key in image_keys
        ]

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"{self.config.title_prefix} | {title}",
                },
            },
            "elements": elements,
        }

        if self.config.mode == "webhook":
            return self._send_webhook_card(card)
        return self._send_app_card(card)

    def send_system_notification(self, level: str, title: str, content: str) -> bool:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        markdown_content = (
            f"**级别**: {level}\n\n**内容**\n{content}\n\n**时间**: {timestamp}"
        )
        return self.send_card(title, markdown_content)

    def _send_webhook_card(self, card: dict[str, object]) -> bool:
        response = self._client.post(
            self.config.webhook_url,
            json={"msg_type": "interactive", "card": card},
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("飞书 webhook 请求失败: %s", exc)
            return False

        if payload.get("code") not in (0, None):
            logger.error("飞书 webhook 返回错误: %s", payload)
            return False
        return True

    def upload_image(self, image_path: Path | str) -> str | None:
        token = self._get_tenant_access_token()
        if not token:
            logger.error("缺少可用的飞书 app_id/app_secret，无法上传图片")
            return None

        image_path = Path(image_path).expanduser().resolve()
        if not image_path.is_file():
            logger.error("飞书图片不存在: %s", image_path)
            return None

        with image_path.open("rb") as image_file:
            response = self._client.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": (image_path.name, image_file, "image/png")},
            )

        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("飞书图片上传请求失败: %s", exc)
            return None

        if payload.get("code") not in (0, None):
            logger.error("飞书图片上传返回错误: %s", payload)
            return None

        data = payload.get("data", {})
        image_key = data.get("image_key")
        if not isinstance(image_key, str) or not image_key:
            logger.error("飞书图片上传响应缺少 image_key: %s", payload)
            return None
        return image_key

    def _send_app_card(self, card: dict[str, object]) -> bool:
        token = self._get_tenant_access_token()
        if not token:
            return False

        response = self._client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": self.config.receive_id_type},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": self.config.receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("飞书应用消息发送失败: %s", exc)
            return False

        if payload.get("code") not in (0, None):
            logger.error("飞书应用接口返回错误: %s", payload)
            return False
        return True

    def _get_tenant_access_token(self) -> str | None:
        if self._tenant_access_token is not None:
            return self._tenant_access_token

        response = self._client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            },
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("获取飞书 tenant_access_token 失败: %s", exc)
            return None

        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            logger.error("飞书 tenant_access_token 响应异常: %s", payload)
            return None

        self._tenant_access_token = token
        return token
