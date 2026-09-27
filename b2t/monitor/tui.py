"""Interactive Textual dashboard for the independently running monitor."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import ClassVar

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from b2t.cancellation import PipelineCancelled
from b2t.monitor.backend_client import (
    BackendError,
    GenerationKind,
    MonitorBackendClient,
    SubmissionUnknown,
)
from b2t.monitor.display import MonitorSnapshot
from b2t.monitor.service import BilibiliMonitorService


class GenerationMenu(ModalScreen):
    AUTO_FOCUS = "#generation-kind"
    BINDINGS: ClassVar = [Binding("escape", "cancel", "取消")]
    CSS = """
    GenerationMenu { align: center middle; }
    GenerationMenu > Vertical { width: 64; height: auto; border: round #14b8a6;
        background: #101820; padding: 1 2; }
    GenerationMenu OptionList { height: 5; }
    """

    def __init__(self, title: str):
        super().__init__()
        self.video_title = title

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical():
            yield Static(Text(self.video_title))
            yield Static("使用 backend 默认模型和模板 · Esc 取消")
            yield OptionList(
                "生成总结", "生成阅读报告", "总结和阅读报告都生成", id="generation-kind"
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(("summary", "report", "both")[event.option_index])

    def action_cancel(self) -> None:
        self.dismiss(None)


class MonitorApp(App):
    """Monitor locally; submit explicitly selected jobs over the backend API."""

    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = None
    BINDINGS: ClassVar = [
        Binding("ctrl+c", "quit", show=False, priority=True),
        Binding("up", "move_video(-1)", show=False),
        Binding("down", "move_video(1)", show=False),
        Binding("left", "move_creator(-1)", show=False),
        Binding("right", "move_creator(1)", show=False),
        Binding("enter", "generate", show=False),
    ]
    CSS = """
    Screen { background: #101820; color: #e2e8f0; padding: 1 2; }
    #heading { height: 1; color: #5eead4; text-style: bold; }
    #overview { height: 1; color: #94a3b8; }
    #activity { height: 2; border-left: thick #14b8a6; padding-left: 1; }
    #creator { height: 3; margin-top: 1; }
    #videos { height: 1fr; min-height: 7; overflow: hidden; }
    #logs { height: 5; border-top: solid #334155; color: #94a3b8; }
    #hint { height: 1; color: #64748b; }
    """

    def __init__(self, service: BilibiliMonitorService, *, backend_client=None):
        super().__init__()
        self.service = service
        self.backend = backend_client or MonitorBackendClient(service.config.backend)
        self.creator_index = 0
        self.selected_bvid: str | None = None
        self.jobs: dict[str, tuple[str, GenerationKind]] = {}
        self.job_labels: dict[str, str] = {}
        self.submitting: set[str] = set()
        self.current = service.snapshot()
        self.messages: queue.Queue = queue.Queue(maxsize=256)
        self.recent_logs: deque[str] = deque(maxlen=5)
        self.started = time.time()
        self.thread: threading.Thread | None = None
        self.failed = False
        self.stopping = False

    def compose(self) -> ComposeResult:
        yield Static("B2T  /  UP 主监控", id="heading")
        yield Static(id="overview")
        yield Static(id="activity")
        yield Static(id="creator")
        yield Static(id="videos")
        yield Static(id="logs")
        yield Static(
            "↑↓ 选视频 · ←→ 切换 UP · Enter 生成 · Ctrl+C 退出（后台任务继续）",
            id="hint",
        )

    def enqueue(self, value) -> None:
        try:
            self.messages.put_nowait(value)
        except queue.Full:
            # Keep the newest progress without letting logs consume unbounded RAM.
            try:
                self.messages.get_nowait()
                self.messages.put_nowait(value)
            except (queue.Empty, queue.Full):
                pass

    def on_mount(self) -> None:
        self.service.on_update = self.enqueue
        self.set_interval(0.25, self.refresh_display)
        self.set_interval(2, self.start_polling)
        self.refresh_display()
        self.thread = threading.Thread(
            target=self._monitor, name="b2t-monitor", daemon=True
        )
        self.thread.start()

    def _monitor(self) -> None:
        try:
            self.service.run()
        except PipelineCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 -- Display worker failures in the dashboard.
            self.failed = True
            self.enqueue(f"监控已停止：{exc}")
        finally:
            self.service.close()

    async def action_quit(self) -> None:
        self.stopping = True
        self.refresh_display()
        await asyncio.to_thread(self.service.request_stop)
        self.exit()

    async def on_unmount(self) -> None:
        await asyncio.to_thread(self.service.request_stop)
        self.workers.cancel_all()
        await self.workers.wait_for_complete()
        await self.backend.close()

    def selected_creator(self):
        creators = self.current.creators
        return creators[self.creator_index % len(creators)] if creators else None

    def action_move_creator(self, delta: int) -> None:
        if isinstance(self.screen, GenerationMenu):
            return
        if self.current.creators:
            self.creator_index = (self.creator_index + delta) % len(
                self.current.creators
            )
            self.selected_bvid = None
            self.refresh_display()

    def action_move_video(self, delta: int) -> None:
        if isinstance(self.screen, GenerationMenu):
            return
        creator = self.selected_creator()
        if creator and creator.videos:
            ids = [v.bvid for v in creator.videos]
            index = ids.index(self.selected_bvid) if self.selected_bvid in ids else 0
            self.selected_bvid = ids[(index + delta) % len(ids)]
            self.refresh_display()

    def action_generate(self) -> None:
        if isinstance(self.screen, GenerationMenu):
            return
        creator = self.selected_creator()
        video = (
            next((v for v in creator.videos if v.bvid == self.selected_bvid), None)
            if creator
            else None
        )
        if video is None:
            return
        if video.bvid in self.jobs or video.bvid in self.submitting:
            self.enqueue("该视频已有任务或提交结果待确认，请勿重复提交")
            return

        def chosen(kind: GenerationKind | None):
            if kind:
                self.submitting.add(video.bvid)
                self.job_labels[video.bvid] = "正在提交…"
                self.run_worker(self.submit_video(video.bvid, kind))

        self.push_screen(GenerationMenu(video.title), chosen)

    async def submit_video(self, bvid: str, kind: GenerationKind) -> None:
        try:
            job_id = await self.backend.submit(bvid, kind)
        except SubmissionUnknown as exc:
            self.job_labels[bvid] = "提交结果未知"
            self.enqueue(str(exc))
            # Keep the guard: a timeout must not cause duplicate paid tasks.
        except BackendError as exc:
            self.submitting.discard(bvid)
            self.job_labels[bvid] = "提交失败"
            self.enqueue(str(exc))
        else:
            self.submitting.discard(bvid)
            self.jobs[bvid] = (job_id, kind)
            self.job_labels[bvid] = "已提交，等待 backend"
            label = {"summary": "总结", "report": "阅读报告", "both": "总结和阅读报告"}[
                kind
            ]
            self.enqueue(f"{label}任务已提交 · {bvid} · {job_id}")
        self.refresh_display()

    def start_polling(self) -> None:
        if self.jobs and not any(
            w.group == "job-poll" and not w.is_finished for w in self.workers
        ):
            self.run_worker(self.poll_jobs(), group="job-poll")

    async def poll_jobs(self) -> None:
        for bvid, (job_id, kind) in list(self.jobs.items()):
            try:
                progress = await self.backend.progress(job_id, kind)
            except BackendError as exc:
                if self.job_labels.get(bvid) != "状态查询失败，重试中":
                    self.enqueue(f"{bvid} · {exc}")
                self.job_labels[bvid] = "状态查询失败，重试中"
            else:
                self.job_labels[bvid] = progress.label
                if progress.done:
                    self.jobs.pop(bvid, None)
                    self.enqueue(f"{bvid} · {progress.label} {progress.error}")
        self.refresh_display()

    def refresh_display(self) -> None:
        for _ in range(256):
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, MonitorSnapshot):
                self.current = message
            else:
                self.recent_logs.append(str(message).replace("\n", " "))
        snapshot = self.current
        elapsed = int(time.time() - self.started)
        self.screen_stack[0].query_one("#overview", Static).update(
            f"{len(snapshot.creators)} 个 UP 主  ·  检查完成 {snapshot.checks}  ·  检查失败 {snapshot.failed}"
            f"  ·  已运行 {elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}"
        )
        activity = (
            "正在停止监控…"
            if self.stopping
            else "监控已停止，请检查日志"
            if self.failed
            else snapshot.activity
        )
        if self.jobs and not self.stopping:
            activity = (
                f"backend 处理中：{len(self.jobs)} 个任务 · "
                + self.job_labels.get(self.selected_bvid, snapshot.activity)
            )
        self.screen_stack[0].query_one("#activity", Static).update(Text(activity))
        if snapshot.creators:
            index = self.creator_index % len(snapshot.creators)
            creator = snapshot.creators[index]
            if self.selected_bvid not in {v.bvid for v in creator.videos}:
                self.selected_bvid = creator.videos[0].bvid if creator.videos else None
            checked = (
                datetime.fromtimestamp(creator.checked_at, tz=UTC)
                .astimezone()
                .strftime("%H:%M:%S")
                if creator.checked_at
                else "尚未检查"
            )
            remaining = (
                f"{max(0, int(creator.next_check - time.time()))} 秒"
                if creator.next_check
                else "—"
            )
            text = Text(
                f"{creator.name}  ·  UID {creator.uid}  ·  {index + 1}/{len(snapshot.creators)}",
                style="bold",
            )
            text.append(
                f"\n{creator.status}  ·  上次 {checked}  ·  下次 {remaining}  ·  周期 {creator.interval} 秒",
                style="#94a3b8",
            )
            if creator.error:
                text.append(f"\n{creator.error}", style="#fda4af")
            self.screen_stack[0].query_one("#creator", Static).update(text)
            table = Table(expand=True, box=None, padding=(0, 1), show_edge=False)
            table.add_column("", width=1)
            table.add_column("发布时间", width=11)
            table.add_column("最近视频", ratio=1, overflow="ellipsis", no_wrap=True)
            if self.size.width >= 100:
                table.add_column("BV 号", width=12)
            table.add_column("状态", width=16, no_wrap=True, overflow="ellipsis")
            for video in creator.videos:
                selected = video.bvid == self.selected_bvid
                status = self.job_labels.get(video.bvid, video.status)
                row = [
                    "›" if selected else "",
                    video.published[5:16]
                    if len(video.published) >= 16 and video.published[4:5] == "-"
                    else video.published or "未知",
                    Text(video.title),
                ]
                if self.size.width >= 100:
                    row.append(video.bvid)
                color = (
                    "#5eead4"
                    if status
                    in {"已总结", "总结完成", "阅读报告完成", "总结和报告完成"}
                    else "#fda4af"
                    if "失败" in status
                    else "#cbd5e1"
                )
                row.append(Text(status, style=color))
                table.add_row(*row, style="on #243846" if selected else None)
            self.screen_stack[0].query_one("#videos", Static).update(
                table if creator.videos else Text("尚无视频数据，等待检查…")
            )
        self.screen_stack[0].query_one("#logs", Static).update(
            Text("\n".join(self.recent_logs))
        )


class DashboardLogHandler(logging.Handler):
    def __init__(self, app: MonitorApp):
        super().__init__()
        self.app = app
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s · %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        self.app.enqueue(self.format(record))


def run_monitor_tui(service: BilibiliMonitorService) -> int:
    app = MonitorApp(service)
    root = logging.getLogger()
    handlers = root.handlers[:]
    handler = DashboardLogHandler(app)
    root.handlers = [handler]
    try:
        app.run(mouse=False)
        return 1 if app.failed else 0
    finally:
        service.request_stop()
        if app.thread is None:
            service.close()
        else:
            app.thread.join(timeout=1)
        root.handlers = handlers
        handler.close()
