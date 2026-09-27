import time
from dataclasses import replace
from pathlib import Path

import httpx

from b2t.bilibili_credentials import save_credentials
from b2t.config import (
    AppConfig,
    BilibiliConfig,
    ConverterConfig,
    DownloadConfig,
    FancyHtmlConfig,
    MonitorConfig,
    MonitorCreatorConfig,
    RagConfig,
    StorageConfig,
    STTConfig,
    SummarizeConfig,
    SummarizeModelProfile,
    SummaryPreset,
    SummaryPresetsConfig,
)
from b2t.monitor.service import BilibiliMonitorService


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


def test_monitor_uses_structured_bilibili_cookie_fields(tmp_path: Path) -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers["cookie"] = request.headers.get("cookie", "")
        return httpx.Response(200, json={"code": 0, "data": {"items": []}})

    service = BilibiliMonitorService(
        _build_config(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    payload = service.fetch_user_space_dynamics(123456)
    service.close()

    assert payload["code"] == 0
    assert "SESSDATA=sess" in captured_headers["cookie"]
    assert "DedeUserID=10001" in captured_headers["cookie"]


def test_running_monitor_reads_credentials_saved_by_login_process(
    tmp_path: Path,
) -> None:
    config = _build_config(tmp_path)
    credential_path = str(tmp_path / "login.json")
    config = replace(
        config,
        bilibili=BilibiliConfig(credentials_file=credential_path, SESSDATA="manual"),
    )
    received = []

    def handler(request):
        received.append(request.headers.get("Cookie"))
        return httpx.Response(200, json={"code": 0, "data": {"items": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = BilibiliMonitorService(config, client=client)
        try:
            service.fetch_user_space_dynamics(123456)
            save_credentials(
                credential_path,
                {"SESSDATA": "scanned", "bili_jct": "csrf", "DedeUserID": "123"},
            )
            service.fetch_user_space_dynamics(123456)
        finally:
            service.close()
    assert received[0] == "SESSDATA=manual"
    assert "SESSDATA=scanned" in received[1]


def test_recent_videos_visible_regardless_of_age(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    snapshots = []
    service = BilibiliMonitorService(config, on_update=snapshots.append)
    old = int(time.time()) - 10 * 86400
    items = [
        {
            "id_str": str(100 + index),
            "modules": {
                "module_author": {"pub_ts": old + index * 100},
                "module_dynamic": {
                    "major": {
                        "type": "MAJOR_TYPE_ARCHIVE",
                        "archive": {
                            "bvid": f"BV1AB411c7m{index}",
                            "title": f"第 {index} 期",
                        },
                    }
                },
            },
        }
        for index in range(7)
    ]
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": 0,
        "data": {"items": items},
    }
    try:
        service.process_creator(config.monitor.creators[0])
    finally:
        service.close()
    latest = snapshots[-1].creators[0]
    assert [video.title for video in latest.videos] == [
        f"第 {i} 期" for i in (6, 5, 4, 3, 2)
    ]
    assert all(video.status == "未总结" for video in latest.videos)
    assert latest.checked_at is not None
    assert latest.next_check > latest.checked_at
    assert service.checks == 1


def test_check_failure_visible_and_state_not_advanced(tmp_path: Path) -> None:
    import pytest

    service = BilibiliMonitorService(_build_config(tmp_path))
    service.state.set_last_seen(123456, "old")
    service.fetch_user_space_dynamics = lambda *_args, **_kwargs: {
        "code": -101,
        "message": "登录失效",
    }
    try:
        with pytest.raises(RuntimeError):
            service.process_creator(service.config.monitor.creators[0])
        current = service.snapshot().creators[0]
        assert service.failed == 1
        assert service.checks == 0
        assert current.status == "失败，等待重试"
        assert "登录失效" in current.error
        assert current.next_check is not None
        assert service.state.get_last_seen(123456) == "old"
    finally:
        service.close()


def test_idle_monitor_stop_does_not_wait_for_interval(tmp_path: Path) -> None:
    import threading

    service = BilibiliMonitorService(_build_config(tmp_path))
    checked = threading.Event()

    def fetch(*args, **kwargs):
        checked.set()
        return {"code": 0, "data": {"items": []}}

    service.fetch_user_space_dynamics = fetch
    worker = threading.Thread(target=service.run, daemon=True)
    try:
        worker.start()
        assert checked.wait(2)
        service.request_stop()
        worker.join(timeout=2)
        assert not worker.is_alive()
    finally:
        service.request_stop()
        worker.join(timeout=2)
        service.close()


def test_pagination_collects_five_unique_videos_from_sparse_pages(
    tmp_path: Path,
) -> None:
    requests = []
    now = int(time.time())

    def video(index):
        return {
            "id_str": str(100 + index),
            "modules": {
                "module_author": {"pub_ts": str(now - index * 86400)},
                "module_dynamic": {
                    "major": {
                        "type": "MAJOR_TYPE_ARCHIVE",
                        "archive": {
                            "bvid": f"BV1AB411c7m{index}",
                            "title": f"第 {index} 期",
                        },
                    }
                },
            },
        }

    def handler(request):
        offset = request.url.params["offset"]
        page = int(offset) if offset else 0
        requests.append(page)
        items = [video(page), {"id_str": f"text-{page}", "modules": {}}]
        if page:
            items.insert(0, video(page - 1))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": items,
                    "has_more": True,
                    "offset": str(page + 1),
                },
            },
        )

    config = _build_config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = BilibiliMonitorService(config, client=client)
        try:
            payload = service.fetch_user_space_dynamics(123456)
            events = [
                service.extract_video_event(item, None)
                for item in payload["data"]["items"]
            ]
            events = [event for event in events if event]
            assert len(events) == 5
            assert requests == [0, 1, 2, 3, 4]
            assert len({event.bvid for event in events}) == 5
            assert events[0].publish_timestamp == now
            assert len(events[0].publish_time) == 19
        finally:
            service.close()


def test_pagination_stops_when_cursor_repeats(tmp_path: Path) -> None:
    calls = []

    def handler(request):
        calls.append(request.url.params["offset"])
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"id_str": "same", "modules": {}}],
                    "has_more": True,
                    "offset": "repeat",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = BilibiliMonitorService(_build_config(tmp_path), client=client)
        try:
            payload = service.fetch_user_space_dynamics(123456)
            assert calls == ["", "repeat"]
            assert len(payload["data"]["items"]) == 1
        finally:
            service.close()


def test_string_timestamp_is_normalized_for_display(tmp_path: Path) -> None:
    service = BilibiliMonitorService(_build_config(tmp_path))
    try:
        item = {
            "id_str": "new",
            "modules": {
                "module_author": {
                    "pub_ts": str(int(time.time()) - 60),
                    "pub_time": "1分钟前",
                },
                "module_dynamic": {
                    "major": {
                        "type": "MAJOR_TYPE_ARCHIVE",
                        "archive": {
                            "bvid": "BV1AB411c7mD",
                            "title": "新一期",
                        },
                    }
                },
            },
        }
        assert service.extract_video_event(item, None).publish_timestamp > 0
        assert service.get_publish_time(item) != "1分钟前"
    finally:
        service.close()


def test_monitor_only_displays_existing_and_new_videos(tmp_path, monkeypatch):
    from unittest.mock import Mock

    import b2t.pipeline
    import b2t.storage

    pipeline = Mock(side_effect=AssertionError("monitor must not run pipeline"))
    storage = Mock(side_effect=AssertionError("monitor must not initialize storage"))
    monkeypatch.setattr(b2t.pipeline, "run_pipeline", pipeline)
    monkeypatch.setattr(b2t.storage, "create_storage_backend", storage)
    monkeypatch.setattr(b2t.storage, "create_stt_storage_backend", storage)
    history = Mock(spec=["has_summary_for_bvid"])
    history.has_summary_for_bvid.side_effect = lambda bvid: bvid == "BV1AB411c7m0"
    config = _build_config(tmp_path)
    service = BilibiliMonitorService(config, history_db=history)
    items = []
    service.fetch_user_space_dynamics = lambda *_: {"code": 0, "data": {"items": items}}

    def video(index):
        return {
            "id_str": str(100 + index),
            "modules": {
                "module_author": {"pub_ts": str(int(time.time()) - 60 + index)},
                "module_dynamic": {
                    "major": {
                        "type": "MAJOR_TYPE_ARCHIVE",
                        "archive": {
                            "bvid": f"BV1AB411c7m{index}",
                            "title": f"视频{index}",
                        },
                    }
                },
            },
        }

    try:
        items.extend([video(1), video(0)])
        service.run(once=True)
        assert [v.status for v in service.snapshot().creators[0].videos] == [
            "未总结",
            "已总结",
        ]
        items.insert(0, video(2))
        service.run(once=True)
        service.run(once=True)
        assert service.checks == 3
        assert service.state.get_last_seen(123456) == "102"
        assert service.snapshot().creators[0].videos[0].status == "未总结"
        assert service.snapshot().creators[0].next_check is None
        assert not Path(config.download.output_dir).exists()
        pipeline.assert_not_called()
        storage.assert_not_called()
    finally:
        service.close()
