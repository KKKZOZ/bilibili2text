import time
import json
from pathlib import Path

import httpx

from b2t.config import (
    AppConfig,
    BilibiliConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    FeishuConfig,
    MonitorConfig,
    MonitorCreatorConfig,
    RagConfig,
    StorageConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPreset,
    SummaryPresetsConfig,
    STTConfig,
)
from b2t.monitor.feishu import FeishuNotifier
from b2t.monitor.service import BilibiliMonitorService
from b2t.storage import StoredArtifact
from b2t.storage.local import LocalStorageBackend


class DummyNotifier:
    def __init__(self) -> None:
        self.cards: list[tuple[str, str]] = []
        self.image_cards: list[tuple[str, list[Path | str]]] = []
        self.system_messages: list[tuple[str, str, str]] = []

    def send_card(self, title: str, markdown_content: str) -> bool:
        self.cards.append((title, markdown_content))
        return True

    def send_system_notification(self, level: str, title: str, content: str) -> bool:
        self.system_messages.append((level, title, content))
        return True

    def send_image_card(self, title: str, image_paths: list[Path | str]) -> bool:
        self.image_cards.append((title, image_paths))
        return True

    def close(self) -> None:
        return None


def _build_config(tmp_path: Path) -> AppConfig:
    summary_profile = SummarizeModelProfile(
        provider="bailian",
        model="qwen3-max",
        api_key="",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    return AppConfig(
        download=DownloadConfig(
            output_dir=str(tmp_path / "transcriptions"),
            db_dir=str(tmp_path / "db"),
        ),
        storage=StorageConfig(backend="local"),
        stt=STTConfig(),
        summarize=SummarizeConfig(
            profile="main",
            profiles={"main": summary_profile},
            preset="basic",
        ),
        fancy_html=FancyHtmlConfig(profile="main"),
        summary_presets=SummaryPresetsConfig(
            default="basic",
            presets={
                "basic": SummaryPreset(
                    prompt_template="{content}",
                    label="Basic",
                )
            },
            source_path=tmp_path / "summary_presets.toml",
        ),
        converter=ConverterConfig(),
        rag=RagConfig(),
        feishu=FeishuConfig(mode="disabled", summary_max_chars=120),
        monitor=MonitorConfig(
            enabled=True,
            state_file=str(tmp_path / "state.json"),
            creators=(
                MonitorCreatorConfig(
                    uid=123456,
                    name="测试UP",
                    check_interval=300,
                ),
            ),
        ),
        bilibili=BilibiliConfig(
            SESSDATA="sess",
            bili_jct="csrf",
            buvid3="buvid",
            DedeUserID="10001",
            DedeUserID__ckMd5="md5",
        ),
    )


def test_monitor_processes_new_video_and_updates_state(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    notifier = DummyNotifier()
    storage_backend = LocalStorageBackend(tmp_path / "transcriptions")
    processed_urls: list[str] = []

    def pipeline_runner(url: str, *_args, **_kwargs) -> dict[str, StoredArtifact]:
        processed_urls.append(url)
        work_dir = tmp_path / "transcriptions" / "BV1AB411c7mD_test"
        work_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = work_dir / "BV1AB411c7mD_test.md"
        summary_path = work_dir / "BV1AB411c7mD_test_summary.md"
        markdown_path.write_text("# transcript", encoding="utf-8")
        summary_path.write_text(
            "这是自动总结内容\n\n- 要点 1\n- 要点 2",
            encoding="utf-8",
        )
        return {
            "markdown": storage_backend.store_file(
                markdown_path,
                object_key="unused/markdown.md",
            ),
            "summary": storage_backend.store_file(
                summary_path,
                object_key="unused/summary.md",
            ),
        }

    service = BilibiliMonitorService(
        config,
        notifier=notifier,
        storage_backend=storage_backend,
        stt_storage_backend=storage_backend,
        pipeline_runner=pipeline_runner,
    )

    recent_timestamp = int(time.time()) - 60
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {
            "items": [
                {
                    "id_str": "999",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1AB411c7mD",
                                    "title": "新视频标题",
                                },
                            }
                        },
                    },
                }
            ]
        },
    }
    fake_png = tmp_path / "summary_no_table.png"
    fake_png.write_bytes(b"fake-png")
    service._build_notification_pngs = lambda *_args, **_kwargs: [fake_png]

    service.process_creator(config.monitor.creators[0])
    service.close()

    assert processed_urls == ["https://www.bilibili.com/video/BV1AB411c7mD"]
    assert notifier.image_cards
    assert notifier.image_cards[0][0] == "测试UP 发布新视频"
    assert service.state.get_last_seen(123456) == "999"


def test_monitor_can_bootstrap_latest_unsummarized_videos(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    notifier = DummyNotifier()
    storage_backend = LocalStorageBackend(tmp_path / "transcriptions")
    processed_bvids: list[str] = []

    def pipeline_runner(url: str, *_args, **_kwargs) -> dict[str, StoredArtifact]:
        processed_bvids.append(url.rsplit("/", 1)[-1])
        bvid = processed_bvids[-1]
        work_dir = tmp_path / "transcriptions" / f"{bvid}_test"
        work_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = work_dir / f"{bvid}_test.md"
        summary_path = work_dir / f"{bvid}_test_summary.md"
        markdown_path.write_text("# transcript", encoding="utf-8")
        summary_path.write_text("bootstrap summary", encoding="utf-8")
        return {
            "markdown": storage_backend.store_file(
                markdown_path,
                object_key=f"unused/{bvid}/markdown.md",
            ),
            "summary": storage_backend.store_file(
                summary_path,
                object_key=f"unused/{bvid}/summary.md",
            ),
        }

    service = BilibiliMonitorService(
        config,
        notifier=notifier,
        storage_backend=storage_backend,
        stt_storage_backend=storage_backend,
        pipeline_runner=pipeline_runner,
    )

    recent_timestamp = int(time.time()) - 60
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {
            "items": [
                {
                    "id_str": "1000",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 20},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1AB411c7mD",
                                    "title": "已总结视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "999",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 10},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1CD411c7mE",
                                    "title": "待测试视频A",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "998",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1EF411c7mF",
                                    "title": "待测试视频B",
                                },
                            }
                        },
                    },
                },
            ]
        },
    }
    service._has_summary_for_bvid = lambda bvid: bvid == "BV1AB411c7mD"
    fake_png = tmp_path / "bootstrap_summary.png"
    fake_png.write_bytes(b"fake-png")
    service._build_notification_pngs = lambda *_args, **_kwargs: [fake_png]

    service.process_creator(
        config.monitor.creators[0],
        bootstrap_unsummarized_count=2,
    )
    service.close()

    assert processed_bvids == ["BV1EF411c7mF", "BV1CD411c7mE"]


def test_feishu_webhook_notifier_sends_interactive_card() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    notifier = FeishuNotifier(
        FeishuConfig(
            mode="webhook",
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/example",
            title_prefix="B2T",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    ok = notifier.send_card("测试标题", "**测试内容**")
    notifier.close()

    assert ok is True
    assert len(requests) == 1
    payload = json.loads(requests[0].content.decode("utf-8"))
    assert payload["msg_type"] == "interactive"
    assert payload["card"]["header"]["title"]["content"] == "B2T | 测试标题"


def test_feishu_disabled_image_card_is_noop_success() -> None:
    notifier = FeishuNotifier(FeishuConfig(mode="disabled"))

    ok = notifier.send_image_card("测试标题", [Path("/tmp/nonexistent.png")])
    notifier.close()

    assert ok is True


def test_monitor_uses_structured_bilibili_cookie_fields(tmp_path: Path) -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers["cookie"] = request.headers.get("cookie", "")
        return httpx.Response(200, json={"code": 0, "data": {"items": []}})

    service = BilibiliMonitorService(
        _build_config(tmp_path),
        notifier=DummyNotifier(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    payload = service.fetch_user_space_dynamics(123456)
    service.close()

    assert payload["code"] == 0
    assert "SESSDATA=sess" in captured_headers["cookie"]
    assert "DedeUserID=10001" in captured_headers["cookie"]


def test_monitor_updates_state_after_each_successful_video(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    notifier = DummyNotifier()
    storage_backend = LocalStorageBackend(tmp_path / "transcriptions")
    processed_bvids: list[str] = []

    def pipeline_runner(url: str, *_args, **_kwargs) -> dict[str, StoredArtifact]:
        bvid = url.rsplit("/", 1)[-1]
        processed_bvids.append(bvid)
        if bvid == "BV1AB411c7mD":
            raise RuntimeError("boom")

        work_dir = tmp_path / "transcriptions" / f"{bvid}_test"
        work_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = work_dir / f"{bvid}_test.md"
        summary_path = work_dir / f"{bvid}_test_summary.md"
        markdown_path.write_text("# transcript", encoding="utf-8")
        summary_path.write_text("ok", encoding="utf-8")
        return {
            "markdown": storage_backend.store_file(
                markdown_path,
                object_key=f"unused/{bvid}/markdown.md",
            ),
            "summary": storage_backend.store_file(
                summary_path,
                object_key=f"unused/{bvid}/summary.md",
            ),
        }

    service = BilibiliMonitorService(
        config,
        notifier=notifier,
        storage_backend=storage_backend,
        stt_storage_backend=storage_backend,
        pipeline_runner=pipeline_runner,
    )

    recent_timestamp = int(time.time()) - 60
    service.state.set_last_seen(123456, "997")
    service.state.save()
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {
            "items": [
                {
                    "id_str": "999",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 20},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1AB411c7mD",
                                    "title": "失败视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "998",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 10},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1CD411c7mE",
                                    "title": "成功视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "997",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1EF411c7mF",
                                    "title": "旧视频",
                                },
                            }
                        },
                    },
                },
            ]
        },
    }
    fake_png = tmp_path / "partial_success.png"
    fake_png.write_bytes(b"fake-png")
    service._build_notification_pngs = lambda *_args, **_kwargs: [fake_png]

    try:
        service.process_creator(config.monitor.creators[0])
    except RuntimeError as exc:
        assert str(exc) == "boom"
    finally:
        service.close()

    assert processed_bvids == ["BV1CD411c7mE", "BV1AB411c7mD"]
    assert service.state.get_last_seen(123456) == "998"


def test_monitor_recovers_when_last_seen_is_missing(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    notifier = DummyNotifier()
    storage_backend = LocalStorageBackend(tmp_path / "transcriptions")
    processed_bvids: list[str] = []

    def pipeline_runner(url: str, *_args, **_kwargs) -> dict[str, StoredArtifact]:
        processed_bvids.append(url.rsplit("/", 1)[-1])
        bvid = processed_bvids[-1]
        work_dir = tmp_path / "transcriptions" / f"{bvid}_test"
        work_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = work_dir / f"{bvid}_test.md"
        summary_path = work_dir / f"{bvid}_test_summary.md"
        markdown_path.write_text("# transcript", encoding="utf-8")
        summary_path.write_text("ok", encoding="utf-8")
        return {
            "markdown": storage_backend.store_file(
                markdown_path,
                object_key=f"unused/{bvid}/markdown.md",
            ),
            "summary": storage_backend.store_file(
                summary_path,
                object_key=f"unused/{bvid}/summary.md",
            ),
        }

    service = BilibiliMonitorService(
        config,
        notifier=notifier,
        storage_backend=storage_backend,
        stt_storage_backend=storage_backend,
        pipeline_runner=pipeline_runner,
    )

    recent_timestamp = int(time.time()) - 60
    service.state.set_last_seen(123456, "stale-id")
    service.state.save()
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {
            "items": [
                {
                    "id_str": "1001",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 30},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1GH411c7mG",
                                    "title": "最新视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "1000",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 20},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1CD411c7mE",
                                    "title": "次新视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "999",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 10},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1AB411c7mD",
                                    "title": "更早视频",
                                },
                            }
                        },
                    },
                },
            ]
        },
    }
    fake_png = tmp_path / "recover_missing_last_seen.png"
    fake_png.write_bytes(b"fake-png")
    service._build_notification_pngs = lambda *_args, **_kwargs: [fake_png]

    service.process_creator(config.monitor.creators[0])
    service.close()

    assert processed_bvids == ["BV1AB411c7mD", "BV1CD411c7mE", "BV1GH411c7mG"]
    assert service.state.get_last_seen(123456) == "1001"


def test_monitor_does_not_advance_last_seen_for_non_video_dynamics(
    tmp_path: Path,
) -> None:
    config = _build_config(tmp_path)
    notifier = DummyNotifier()
    storage_backend = LocalStorageBackend(tmp_path / "transcriptions")
    processed_bvids: list[str] = []

    def pipeline_runner(url: str, *_args, **_kwargs) -> dict[str, StoredArtifact]:
        processed_bvids.append(url.rsplit("/", 1)[-1])
        bvid = processed_bvids[-1]
        work_dir = tmp_path / "transcriptions" / f"{bvid}_test"
        work_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = work_dir / f"{bvid}_test.md"
        summary_path = work_dir / f"{bvid}_test_summary.md"
        markdown_path.write_text("# transcript", encoding="utf-8")
        summary_path.write_text("ok", encoding="utf-8")
        return {
            "markdown": storage_backend.store_file(
                markdown_path,
                object_key=f"unused/{bvid}/markdown.md",
            ),
            "summary": storage_backend.store_file(
                summary_path,
                object_key=f"unused/{bvid}/summary.md",
            ),
        }

    service = BilibiliMonitorService(
        config,
        notifier=notifier,
        storage_backend=storage_backend,
        stt_storage_backend=storage_backend,
        pipeline_runner=pipeline_runner,
    )

    recent_timestamp = int(time.time()) - 60
    service.state.set_last_seen(123456, "999")
    service.state.save()
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {
            "items": [
                {
                    "id_str": "1001",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 20},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_OPUS",
                            }
                        },
                    },
                },
                {
                    "id_str": "1000",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp + 10},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1CD411c7mE",
                                    "title": "新视频",
                                },
                            }
                        },
                    },
                },
                {
                    "id_str": "999",
                    "modules": {
                        "module_author": {"pub_ts": recent_timestamp},
                        "module_dynamic": {
                            "major": {
                                "type": "MAJOR_TYPE_ARCHIVE",
                                "archive": {
                                    "bvid": "BV1AB411c7mD",
                                    "title": "旧视频",
                                },
                            }
                        },
                    },
                },
            ]
        },
    }
    fake_png = tmp_path / "non_video_dynamic.png"
    fake_png.write_bytes(b"fake-png")
    service._build_notification_pngs = lambda *_args, **_kwargs: [fake_png]

    service.process_creator(config.monitor.creators[0])
    service.close()

    assert processed_bvids == ["BV1CD411c7mE"]
    assert service.state.get_last_seen(123456) == "1000"
