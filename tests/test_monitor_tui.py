import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

from rich.console import Console
from textual.widgets import Button, Input, Static

from b2t.config import BackendConfig
from b2t.monitor.display import CreatorStatus, MonitorSnapshot, VideoStatus
from b2t.monitor.tui import MonitorApp


class FakeMonitor:
    def __init__(self):
        self.config = SimpleNamespace(backend=BackendConfig())
        self.stop = threading.Event()
        self.closed = threading.Event()
        self.on_update = None

    def snapshot(self):
        return MonitorSnapshot(
            (
                CreatorStatus(
                    123,
                    "测试 UP",
                    300,
                    status="等待下次检查",
                    checked_at=time.time(),
                    next_check=time.time() + 300,
                    videos=(
                        VideoStatus(
                            "BV1AB411c7mD",
                            "最近一期 [不是标记]",
                            "2026-09-27 10:30:00",
                            "已总结",
                        ),
                    ),
                ),
            )
        )

    def run(self, **kwargs):
        self.on_update(self.snapshot())
        self.stop.wait(10)

    def request_stop(self):
        self.stop.set()

    def close(self):
        self.closed.set()


def render(widget):
    console = Console(width=120, color_system=None)
    with console.capture() as capture:
        console.print(widget.content)
    return capture.get()


def test_dashboard_updates_and_stops():
    async def scenario():
        service = FakeMonitor()
        app = MonitorApp(service)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.refresh_display()
            assert "最近一期 [不是标记]" in render(app.query_one("#videos", Static))
            assert "BV1AB411c7mD" in render(app.query_one("#videos", Static))
            assert not list(app.query(Input))
            assert not list(app.query(Button))
            assert app.focused is None
            old = service.snapshot()
            app.enqueue(replace(old, checks=2, activity="检查完成，等待下一轮"))
            app.enqueue("本轮没有新视频")
            app.refresh_display()
            assert "检查完成 2" in render(app.query_one("#overview", Static))
            assert "检查完成，等待下一轮" in render(app.query_one("#activity", Static))
            assert "本轮没有新视频" in render(app.query_one("#logs", Static))
            await pilot.press("ctrl+c")
        assert service.stop.is_set()
        assert service.closed.wait(1)

    asyncio.run(scenario())


def test_narrow_dashboard_and_manual_creator_selection():
    async def scenario():
        service = FakeMonitor()
        app = MonitorApp(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            first = service.snapshot().creators[0]
            first = replace(
                first, videos=(replace(first.videos[0], published="2天前"),)
            )
            second = replace(first, uid=456, name="第二个 UP")
            app.enqueue(MonitorSnapshot((first, second)))
            app.started = time.time() - 16
            app.refresh_display()
            assert "测试 UP" in render(app.query_one("#creator", Static))
            await pilot.press("right")
            assert "第二个 UP" in render(app.query_one("#creator", Static))
            assert "最近一期" in render(app.query_one("#videos", Static))
            assert "BV 号" not in render(app.query_one("#videos", Static))
            assert "2天前" in render(app.query_one("#videos", Static))
            assert app.query_one("#hint").region.bottom <= 24

    asyncio.run(scenario())


def test_video_selection_and_three_generation_choices():
    from b2t.monitor.backend_client import JobProgress
    from b2t.monitor.tui import GenerationMenu

    class FakeBackend:
        def __init__(self):
            self.calls = []
            self.closed = False

        async def submit(self, bvid, kind):
            self.calls.append((bvid, kind))
            return f"job-{len(self.calls)}"

        async def progress(self, job_id, kind):
            return JobProgress("总结和报告完成", done=True)

        async def close(self):
            self.closed = True

    async def scenario():
        service = FakeMonitor()
        backend = FakeBackend()
        app = MonitorApp(service, backend_client=backend)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            creator = service.snapshot().creators[0]
            second = replace(creator.videos[0], bvid="BV1CD411c7mE", title="旧视频")
            creator = replace(creator, videos=(*creator.videos, second))
            app.enqueue(MonitorSnapshot((creator,)))
            app.refresh_display()
            assert not backend.calls
            await pilot.press("down", "enter")
            assert isinstance(app.screen, GenerationMenu)
            # A refresh while the menu is open must not change the target.
            newer = replace(second, bvid="BV1EF411c7mF", title="新一期")
            app.enqueue(
                MonitorSnapshot((replace(creator, videos=(newer, *creator.videos)),))
            )
            app.refresh_display()
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert backend.calls == [(second.bvid, "both")]
            assert app.selected_bvid == second.bvid
            await pilot.press("enter")
            assert not isinstance(app.screen, GenerationMenu)
            assert len(backend.calls) == 1
            await app.poll_jobs()
            assert not app.jobs
            assert "总结和报告完成" in render(app.query_one("#videos", Static))
            for offset, kind in [(0, "summary"), (1, "report")]:
                await pilot.press("enter")
                for _ in range(offset):
                    await pilot.press("down")
                await pilot.press("enter")
                await pilot.pause()
                assert backend.calls[-1] == (second.bvid, kind)
                await app.poll_jobs()
            await pilot.press("enter", "escape")
            assert len(backend.calls) == 3
            await pilot.press("ctrl+c")
        assert backend.closed

    asyncio.run(scenario())


def test_submission_errors_keep_monitor_usable_and_unknown_result_guarded():
    from b2t.monitor.backend_client import BackendError, SubmissionUnknown
    from b2t.monitor.tui import GenerationMenu

    class OfflineBackend:
        async def submit(self, bvid, kind):
            if kind == "summary":
                raise BackendError("请先运行 uv run b2t backend")
            raise SubmissionUnknown("提交结果未知，请检查后台任务")

        async def close(self):
            pass

    async def scenario():
        app = MonitorApp(FakeMonitor(), backend_client=OfflineBackend())
        async with app.run_test() as pilot:
            await pilot.pause()
            bvid = app.selected_bvid
            await pilot.press("enter", "enter")
            await pilot.pause()
            assert app.job_labels[bvid] == "提交失败"
            assert bvid not in app.submitting
            assert "uv run b2t backend" in render(app.query_one("#logs", Static))
            await pilot.press("enter", "down", "enter")
            await pilot.pause()
            assert app.job_labels[bvid] == "提交结果未知"
            assert bvid in app.submitting
            await pilot.press("enter")
            assert not isinstance(app.screen, GenerationMenu)
            assert not app.failed
            await pilot.press("ctrl+c")

    asyncio.run(scenario())
