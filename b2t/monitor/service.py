"""Bilibili creator monitor service."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

from b2t.config import AppConfig, MonitorCreatorConfig, build_bilibili_cookie
from b2t.converter.md_remove_table import MarkdownRemoveTableConverter
from b2t.converter.md_to_png import MarkdownToPngConverter
from b2t.download.yutto_cli import extract_bvid
from b2t.history import HistoryDB, record_pipeline_run
from b2t.monitor.feishu import FeishuNotifier
from b2t.pipeline import run_pipeline
from b2t.storage import (
    StoredArtifact,
    StorageBackend,
    create_storage_backend,
    create_stt_storage_backend,
)

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
    """Persist the latest processed dynamic id for each creator."""

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
    """Monitor creators and trigger the existing b2t pipeline for new videos."""

    BILI_SPACE_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

    def __init__(
        self,
        config: AppConfig,
        *,
        notifier: FeishuNotifier | None = None,
        history_db: HistoryDB | None = None,
        storage_backend: StorageBackend | None = None,
        stt_storage_backend: StorageBackend | None = None,
        pipeline_runner: Callable[..., dict[str, StoredArtifact]] = run_pipeline,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.notifier = notifier or FeishuNotifier(config.feishu)
        self._owns_notifier = notifier is None
        self.history_db = history_db or HistoryDB(config.download.db_dir)
        self.storage_backend = storage_backend or create_storage_backend(config)
        self.stt_storage_backend = stt_storage_backend or create_stt_storage_backend(
            config
        )
        self.pipeline_runner = pipeline_runner
        self.state = JsonStateStore(config.monitor.state_file)
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        if self._owns_notifier:
            self.notifier.close()

    def reset_state(self) -> None:
        self.state.clear()

    def run(
        self,
        *,
        once: bool = False,
        bootstrap_unsummarized_count: int = 0,
    ) -> None:
        creators = self.config.monitor.creators
        if not creators:
            raise ValueError(
                "monitor.creators 为空，请先在配置文件中配置要监控的 UP 主"
            )

        if self.config.monitor.startup_notification:
            creator_names = ", ".join(
                creator.name or str(creator.uid) for creator in creators[:5]
            )
            if len(creators) > 5:
                creator_names += f" 等 {len(creators)} 个"
            self.notifier.send_system_notification(
                "INFO",
                "B站监控已启动",
                (
                    f"**模式**: {'单次检查' if once else '持续监控'}\n\n"
                    f"**UP 主**: {creator_names}\n\n"
                    f"**回填未总结视频数**: {bootstrap_unsummarized_count}"
                ),
            )

        if once:
            for creator in creators:
                self.process_creator(
                    creator,
                    bootstrap_unsummarized_count=bootstrap_unsummarized_count,
                )
            return

        next_run_at = {creator.uid: 0.0 for creator in creators}
        while True:
            now = time.time()
            used_bootstrap = False
            for creator in creators:
                if now < next_run_at[creator.uid]:
                    continue
                try:
                    self.process_creator(
                        creator,
                        bootstrap_unsummarized_count=bootstrap_unsummarized_count,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("监控 %s 失败", creator.name or creator.uid)
                    self.notifier.send_system_notification(
                        "ERROR",
                        "B站监控异常",
                        (
                            f"**UP 主**: {creator.name or creator.uid}\n\n"
                            f"**错误**: {exc}"
                        ),
                    )
                next_run_at[creator.uid] = now + creator.check_interval
                used_bootstrap = True
            if used_bootstrap:
                bootstrap_unsummarized_count = 0
            time.sleep(5)

    def process_creator(
        self,
        creator: MonitorCreatorConfig,
        *,
        bootstrap_unsummarized_count: int = 0,
    ) -> None:
        data = self.fetch_user_space_dynamics(creator.uid, limit_recent=20)
        raw_data = data.get("data")
        if raw_data is None:
            raw_data = {}
        if not isinstance(raw_data, dict):
            raise RuntimeError(
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
        if not items:
            logger.info("%s 暂无可处理动态", creator.name or creator.uid)
            return

        last_seen = self.state.get_last_seen(creator.uid)
        if bootstrap_unsummarized_count > 0:
            candidates = self._collect_unsummarized_video_items(
                items,
                bootstrap_unsummarized_count,
            )
        elif last_seen is None:
            candidates = self._collect_initial_video_items(items)
        else:
            candidates = self._collect_new_video_items(items, last_seen)
            if candidates is None:
                logger.warning(
                    "%s 的 last_seen 已失效，回退到首次扫描策略",
                    creator.name or creator.uid,
                )
                candidates = self._collect_recoverable_video_items(items)

        if not candidates:
            return

        for item in candidates:
            event = self.extract_video_event(item, creator)
            if event is None:
                continue
            self._handle_video_event(event)
            self.state.set_last_seen(creator.uid, event.dynamic_id)
            self.state.save()

    def fetch_user_space_dynamics(
        self,
        uid: int,
        *,
        limit_recent: int = 20,
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

        response = self._client.get(self.BILI_SPACE_API, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
        raw_data = payload.get("data")
        if raw_data is None:
            payload["data"] = {}
            return payload
        if not isinstance(raw_data, dict):
            raise RuntimeError(
                f"B站动态接口返回非法 data 结构: {type(raw_data).__name__}"
            )
        items = raw_data.get("items", [])
        if len(items) > limit_recent:
            raw_data["items"] = items[:limit_recent]
        return payload

    def _collect_initial_video_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        collected = self._collect_recent_video_items(items)
        limited = collected[: self.config.monitor.first_run_max_push]
        limited.sort(key=self.get_publish_timestamp)
        return limited

    def _collect_recent_video_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        threshold = int(time.time()) - self.config.monitor.lookback_hours * 3600
        collected: list[dict[str, Any]] = []
        for item in items:
            if self.get_publish_timestamp(item) < threshold:
                continue
            if self.extract_video_event(item, None) is None:
                continue
            collected.append(item)
        return collected

    def _collect_recoverable_video_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for item in self._collect_recent_video_items(items):
            event = self.extract_video_event(item, None)
            if event is None:
                continue
            if self._has_summary_for_bvid(event.bvid):
                continue
            collected.append(item)
        collected.sort(key=self.get_publish_timestamp)
        return collected

    def _collect_new_video_items(
        self,
        items: list[dict[str, Any]],
        last_seen: str,
    ) -> list[dict[str, Any]] | None:
        last_seen_index: int | None = None
        for index, item in enumerate(items):
            if self.get_dynamic_id(item) == last_seen:
                last_seen_index = index
                break
        if last_seen_index is None:
            return None

        threshold = int(time.time()) - self.config.monitor.lookback_hours * 3600
        collected: list[dict[str, Any]] = []
        for item in items[:last_seen_index]:
            publish_timestamp = self.get_publish_timestamp(item)
            if publish_timestamp < threshold:
                continue
            if self.extract_video_event(item, None) is None:
                continue
            collected.append(item)
        collected.sort(key=self.get_publish_timestamp)
        return collected

    def _collect_unsummarized_video_items(
        self,
        items: list[dict[str, Any]],
        count: int,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for item in items:
            event = self.extract_video_event(item, None)
            if event is None:
                continue
            if self._has_summary_for_bvid(event.bvid):
                continue
            collected.append(item)
            if len(collected) >= count:
                break
        collected.sort(key=self.get_publish_timestamp)
        return collected

    def _handle_video_event(self, event: DynamicVideoEvent) -> None:
        logger.info("发现新视频: %s (%s)", event.title, event.bvid)
        try:
            results = self.pipeline_runner(
                event.video_url,
                self.config,
                summary_preset=self.config.monitor.summary_preset,
                summary_profile=self.config.monitor.summary_profile,
                output_dir=self.config.monitor.output_dir or None,
                storage_backend=self.storage_backend,
                stt_storage_backend=self.stt_storage_backend,
            )
            self._record_history(event.bvid, results)
            image_paths = self._build_notification_pngs(event, results)
            try:
                ok = self.notifier.send_image_card(
                    f"{event.creator.name or event.creator.uid} 发布新视频",
                    image_paths,
                )
            finally:
                for image_path in image_paths:
                    image_path.unlink(missing_ok=True)
            if not ok:
                raise RuntimeError("飞书图片卡片发送失败")
        except Exception as exc:  # noqa: BLE001
            logger.exception("处理视频 %s 失败", event.bvid)
            self.notifier.send_system_notification(
                "ERROR",
                "视频监控处理失败",
                (
                    f"**UP 主**: {event.creator.name or event.creator.uid}\n\n"
                    f"**视频**: {event.title}\n\n"
                    f"**链接**: {event.video_url}\n\n"
                    f"**错误**: {exc}"
                ),
            )
            raise

    def _build_notification_markdown(
        self,
        event: DynamicVideoEvent,
        results: Mapping[str, StoredArtifact | Any],
    ) -> str:
        metadata = results.get("_metadata")
        author = getattr(metadata, "author", "") or event.creator.name
        pubdate = getattr(metadata, "pubdate", "") or event.publish_time

        summary_artifact = results.get("summary")
        summary_text = ""
        if isinstance(summary_artifact, StoredArtifact):
            summary_text = self._read_artifact_text(summary_artifact)

        max_chars = self.config.feishu.summary_max_chars
        if len(summary_text) > max_chars:
            summary_text = summary_text[:max_chars].rstrip() + "\n\n...[已截断]"

        parts = [
            f"**UP 主**: {author or event.creator.uid}",
            f"**标题**: {event.title}",
            f"**BV号**: {event.bvid}",
            f"**发布时间**: {pubdate or '未知'}",
            f"[打开视频]({event.video_url}) | [打开动态]({event.dynamic_url})",
        ]
        if summary_text:
            parts.append(f"**AI 总结**\n\n{summary_text}")
        return "\n\n".join(parts)

    def _build_notification_pngs(
        self,
        event: DynamicVideoEvent,
        results: Mapping[str, StoredArtifact | Any],
    ) -> list[Path]:
        summary_artifact = results.get("summary")
        if not isinstance(summary_artifact, StoredArtifact):
            raise RuntimeError("缺少 summary 产物，无法生成飞书图片")

        summary_table_artifact = results.get("summary_table_md")

        with tempfile.TemporaryDirectory(prefix="b2t-monitor-images-") as temp_dir:
            temp_root = Path(temp_dir)
            summary_md_path = temp_root / f"{event.bvid}_summary.md"
            summary_md_path.write_text(
                self._read_artifact_text(summary_artifact),
                encoding="utf-8",
            )

            png_converter = MarkdownToPngConverter()
            no_table_md_path = temp_root / f"{event.bvid}_summary_no_table.md"
            MarkdownRemoveTableConverter().convert(summary_md_path, no_table_md_path)

            no_table_png_path = temp_root / f"{event.bvid}_summary_no_table.png"
            png_converter.convert(no_table_md_path, no_table_png_path, is_table=False)

            generated_pngs = [no_table_png_path]

            if isinstance(summary_table_artifact, StoredArtifact):
                summary_table_md_path = temp_root / f"{event.bvid}_summary_table.md"
                summary_table_md_path.write_text(
                    self._read_artifact_text(summary_table_artifact),
                    encoding="utf-8",
                )
                summary_table_png_path = temp_root / f"{event.bvid}_summary_table.png"
                png_converter.convert(
                    summary_table_md_path,
                    summary_table_png_path,
                    is_table=True,
                    as_of_date=event.publish_time,
                )
                generated_pngs.append(summary_table_png_path)

            copied_pngs: list[Path] = []
            for png_path in generated_pngs:
                fd, persistent_name = tempfile.mkstemp(
                    prefix=f"{png_path.stem}-",
                    suffix=".png",
                )
                os.close(fd)
                persistent_path = Path(persistent_name)
                persistent_path.write_bytes(png_path.read_bytes())
                copied_pngs.append(persistent_path)
            return copied_pngs

    def _read_artifact_text(self, artifact: StoredArtifact) -> str:
        with self.storage_backend.open_stream(artifact.storage_key) as stream:
            return stream.read().decode("utf-8")

    def _record_history(
        self,
        bvid: str,
        results: Mapping[str, StoredArtifact | Any],
    ) -> None:
        metadata = results.get("_metadata")
        author = getattr(metadata, "author", "")
        pubdate = getattr(metadata, "pubdate", "")
        record_pipeline_run(
            db=self.history_db,
            bvid=bvid,
            results=results,
            author=author,
            pubdate=pubdate,
            summary_preset=self.config.monitor.summary_preset,
            summary_profile=self.config.monitor.summary_profile,
        )

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
        modules = item.get("modules", {})
        author = modules.get("module_author", {})
        pub_ts = author.get("pub_ts")
        if isinstance(pub_ts, int):
            return pub_ts
        if isinstance(pub_ts, float):
            return int(pub_ts)
        timestamp = item.get("timestamp")
        if isinstance(timestamp, int):
            return timestamp
        if isinstance(timestamp, float):
            return int(timestamp)
        return 0

    @staticmethod
    def get_publish_time(item: Mapping[str, Any]) -> str:
        modules = item.get("modules", {})
        author = modules.get("module_author", {})
        pub_ts = author.get("pub_ts")
        if isinstance(pub_ts, (int, float)):
            return datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M:%S")
        pub_time = author.get("pub_time")
        if isinstance(pub_time, str):
            return pub_time.strip()
        return ""

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
