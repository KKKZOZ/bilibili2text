"""Bilibili creator monitor service."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

import httpx

from b2t.cancellation import CancellationToken, PipelineCancelled
from b2t.config import AppConfig, MonitorCreatorConfig, build_bilibili_cookie
from b2t.download.yutto_cli import extract_bvid
from b2t.history import HistoryDB
from b2t.monitor.display import CreatorStatus, MonitorSnapshot, VideoStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DynamicVideoEvent:
    creator: MonitorCreatorConfig
    dynamic_id: str
    bvid: str
    title: str
    publish_timestamp: int
    publish_time: str

    @property
    def dynamic_url(self) -> str:
        return f"https://t.bilibili.com/{self.dynamic_id}"

    @property
    def video_url(self) -> str:
        return f"https://www.bilibili.com/video/{self.bvid}"


class JsonStateStore:
    """Persist the latest observed video dynamic id for each creator."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.state = {}
            return

        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("监控状态文件损坏或不可读，已重置为空: %s", self.path)
            self.state = {}

    def save(self) -> None:
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def clear(self) -> None:
        self.state = {}
        self.save()

    def get_last_seen(self, uid: int) -> str | None:
        return self.state.get(str(uid), {}).get("last_seen")

    def set_last_seen(self, uid: int, dynamic_id: str) -> None:
        self.state.setdefault(str(uid), {})["last_seen"] = dynamic_id


class BilibiliMonitorService:
    """Monitor creators and display videos without running transcription or summaries."""

    BILI_SPACE_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

    def __init__(
        self,
        config: AppConfig,
        *,
        on_update: Callable[[MonitorSnapshot], None] | None = None,
        history_db: HistoryDB | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.on_update = on_update
        self._stop = Event()
        self._cancellation = CancellationToken()
        self._statuses = {
            creator.uid: CreatorStatus(
                creator.uid, creator.name or str(creator.uid), creator.check_interval
            )
            for creator in config.monitor.creators
        }
        self.checks = 0
        self.failed = 0
        self.activity = "正在启动监控"
        self.history_db = history_db or HistoryDB(config.download.db_dir)
        self.state = JsonStateStore(config.monitor.state_file)
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def reset_state(self) -> None:
        self.state.clear()

    def snapshot(self) -> MonitorSnapshot:
        return MonitorSnapshot(
            tuple(self._statuses.values()), self.checks, self.failed, self.activity
        )

    def _publish(self) -> None:
        if self.on_update:
            self.on_update(self.snapshot())

    def _update_creator(self, uid: int, **changes) -> None:
        self._statuses[uid] = replace(self._statuses[uid], **changes)
        self._publish()

    def request_stop(self) -> None:
        self._stop.set()
        self._cancellation.cancel()

    def run(self, *, once: bool = False) -> None:
        creators = self.config.monitor.creators
        if not creators:
            raise ValueError("monitor.creators 为空，请先配置要监控的 UP 主")
        self.activity = "单次检查" if once else "持续监控中"
        self._publish()
        logger.info("监控已启动，共 %d 个 UP 主", len(creators))
        while not self._stop.is_set():
            for creator in creators:
                if self._stop.is_set():
                    break
                due = self._statuses[creator.uid].next_check
                if due is not None and time.time() < due:
                    continue
                try:
                    self.process_creator(creator)
                except PipelineCancelled:
                    return
                except Exception:
                    logger.exception("监控 %s 失败", creator.name or creator.uid)
                    if once:
                        raise
            if once:
                for creator in creators:
                    self._update_creator(creator.uid, next_check=None)
                return
            self._stop.wait(1)

    def process_creator(self, creator: MonitorCreatorConfig) -> None:
        self._cancellation.raise_if_cancelled()
        self._update_creator(creator.uid, status="正在检查", error="", next_check=None)
        try:
            self._process_creator(creator)
        except PipelineCancelled:
            self._update_creator(creator.uid, status="已停止")
            raise
        except Exception as exc:
            self.failed += 1
            self.activity = f"{creator.name or creator.uid} 检查失败"
            self._update_creator(creator.uid, status="失败，等待重试", error=str(exc))
            raise
        else:
            self.checks += 1
            self.activity = "检查完成，等待下一轮"
            self._update_creator(creator.uid, status="等待下次检查")
        finally:
            now = time.time()
            self._update_creator(
                creator.uid, checked_at=now, next_check=now + creator.check_interval
            )

    def _process_creator(self, creator: MonitorCreatorConfig) -> None:
        data = self.fetch_user_space_dynamics(creator.uid)
        raw_data = data.get("data")
        if raw_data is None:
            raw_data = {}
        if not isinstance(raw_data, dict):
            raise RuntimeError(  # noqa: TRY004 -- Malformed upstream response, not caller input.
                f"获取 {creator.name or creator.uid} 动态失败: 接口返回非法 data 结构"
            )
        items = raw_data.get("items", [])
        logger.info(
            "%s B站接口返回 %d 条动态",
            creator.name or creator.uid,
            len(items),
        )
        if data.get("code") not in (0, None):
            message = data.get("message", "未知错误")
            raise RuntimeError(
                f"获取 {creator.name or creator.uid} 动态失败: {message}"
            )
        videos = {}
        for item in items:
            event = self.extract_video_event(item, creator)
            if event is not None:
                videos[event.bvid] = event
        latest = sorted(
            videos.values(), key=lambda event: event.publish_timestamp, reverse=True
        )[:5]
        self._update_creator(
            creator.uid,
            videos=tuple(
                VideoStatus(
                    event.bvid,
                    event.title,
                    event.publish_time,
                    "已总结" if self._has_summary_for_bvid(event.bvid) else "未总结",
                )
                for event in latest
            ),
        )
        for event in latest:
            logger.info(
                "最近视频 | %s | %s | %s | %s",
                creator.name or creator.uid,
                event.publish_time,
                event.bvid,
                event.title,
            )
        if latest:
            self.state.set_last_seen(creator.uid, latest[0].dynamic_id)
            self.state.save()

    def fetch_user_space_dynamics(
        self,
        uid: int,
    ) -> dict[str, Any]:
        params = {
            "offset": "",
            "host_mid": str(uid),
            "timezone_offset": "-480",
            "platform": "web",
            "features": "itemOpusStyle,listOnlyfans,opusBigCover",
            "web_location": "333.1387",
        }
        headers = {
            "User-Agent": self.config.monitor.user_agent,
            "Referer": f"https://space.bilibili.com/{uid}/dynamic",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Origin": "https://space.bilibili.com",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        cookie = build_bilibili_cookie(self.config)
        if cookie:
            headers["Cookie"] = cookie

        collected = []
        seen_ids = set()
        video_ids = set()
        seen_offsets = {""}
        first_payload = None
        # A dynamic page includes text, forwards and pinned posts. Fetch enough
        # pages for five distinct non-pinned videos instead of five dynamics.
        for page_number in range(10):
            self._cancellation.raise_if_cancelled()
            response = self._client.get(
                self.BILI_SPACE_API, params=params, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, None):
                raise RuntimeError(f"B站动态接口返回错误代码: {payload.get('code')}")
            raw_data = payload.get("data") or {}
            if not isinstance(raw_data, dict):
                raise RuntimeError("B站动态接口返回非法 data 结构")  # noqa: TRY004
            if first_payload is None:
                first_payload = payload
            page_items = raw_data.get("items") or []
            if not isinstance(page_items, list):
                raise RuntimeError("B站动态接口返回非法 items 结构")  # noqa: TRY004
            for item in page_items:
                dynamic_id = self.get_dynamic_id(item)
                if dynamic_id is not None and dynamic_id in seen_ids:
                    continue
                if dynamic_id is not None:
                    seen_ids.add(dynamic_id)
                collected.append(item)
                event = self.extract_video_event(item, None)
                tag = (item.get("modules") or {}).get("module_tag") or {}
                if event is not None and tag.get("text") != "置顶":
                    video_ids.add(event.bvid)
            if len(video_ids) >= 5 or not raw_data.get("has_more") or not page_items:
                break
            offset = raw_data.get("offset")
            if not isinstance(offset, str) or not offset or offset in seen_offsets:
                logger.warning("动态分页游标未推进，停止本轮补取")
                break
            seen_offsets.add(offset)
            params["offset"] = offset
            if self._stop.wait(0.2):
                self._cancellation.raise_if_cancelled()
        if len(video_ids) < 5:
            logger.info("已检查 %d 页动态，当前可用视频不足 5 期", page_number + 1)
        logger.info("本轮获取 %d 页、%d 条动态", page_number + 1, len(collected))
        first_payload["data"] = {
            **(first_payload.get("data") or {}),
            "items": collected,
        }
        return first_payload

    def _has_summary_for_bvid(self, bvid: str) -> bool:
        return self.history_db.has_summary_for_bvid(bvid)

    @staticmethod
    def get_dynamic_id(item: Mapping[str, Any]) -> str | None:
        dynamic_id = item.get("id_str") or item.get("id")
        if dynamic_id is None:
            return None
        return str(dynamic_id)

    @staticmethod
    def get_publish_timestamp(item: Mapping[str, Any]) -> int:
        modules = item.get("modules") or {}
        author = modules.get("module_author") or {}
        for value in (author.get("pub_ts"), item.get("timestamp")):
            if isinstance(value, bool):
                continue
            try:
                timestamp = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 < timestamp < 253402300800:
                return timestamp
        return 0

    @staticmethod
    def get_publish_time(item: Mapping[str, Any]) -> str:
        timestamp = BilibiliMonitorService.get_publish_timestamp(item)
        if timestamp:
            return (
                datetime.fromtimestamp(timestamp, tz=UTC)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        author = (item.get("modules") or {}).get("module_author") or {}
        pub_time = author.get("pub_time")
        return pub_time.strip() if isinstance(pub_time, str) else ""

    def extract_video_event(
        self,
        item: Mapping[str, Any],
        creator: MonitorCreatorConfig | None,
    ) -> DynamicVideoEvent | None:
        modules = item.get("modules", {})
        if not isinstance(modules, Mapping):
            return None
        dynamic = modules.get("module_dynamic")
        if not isinstance(dynamic, Mapping):
            return None
        major = dynamic.get("major")
        if not isinstance(major, Mapping):
            return None
        if major.get("type") not in {"MAJOR_TYPE_ARCHIVE", "archive"}:
            return None
        archive = major.get("archive")
        if not isinstance(archive, Mapping):
            return None
        bvid = archive.get("bvid")
        if not isinstance(bvid, str) or not extract_bvid(bvid):
            return None

        dynamic_id = self.get_dynamic_id(item)
        if dynamic_id is None:
            return None

        title = archive.get("title")
        if not isinstance(title, str) or not title.strip():
            title = bvid

        effective_creator = creator or MonitorCreatorConfig(
            uid=0,
            name="",
            check_interval=self.config.monitor.default_check_interval,
        )

        return DynamicVideoEvent(
            creator=effective_creator,
            dynamic_id=dynamic_id,
            bvid=bvid.strip(),
            title=title.strip(),
            publish_timestamp=self.get_publish_timestamp(item),
            publish_time=self.get_publish_time(item),
        )
