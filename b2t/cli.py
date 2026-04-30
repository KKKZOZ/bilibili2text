"""CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.table import Table

from b2t.config import load_config
from b2t.download.yutto_cli import extract_bvid
from b2t.history import HistoryDB, record_pipeline_run
from b2t.monitor import BilibiliMonitorService
from b2t.pipeline import run_pipeline
from b2t.storage import StoredArtifact


@dataclass(frozen=True)
class CLIArgs:
    url: str
    config: str | None = None
    output: str | None = None
    no_summary: bool = False
    summary_preset: str | None = None
    summary_profile: str | None = None
    verbose: bool = False


@dataclass(frozen=True)
class MonitorCLIArgs:
    config: str | None = None
    once: bool = False
    reset_state: bool = False
    bootstrap_unsummarized_count: int = 0
    verbose: bool = False


@dataclass(frozen=True)
class PromptStep:
    key: str
    question: str
    parse: Callable[[str], object]
    hint: str = ""
    default_hint: str = ""


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _coerce_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_optional_text(value)
    raise ValueError("交互输入解析失败，参数类型非法")


def _parse_bool_input(raw: str, *, default: bool) -> bool:
    value = raw.strip().lower()
    if not value:
        return default

    truthy = {"y", "yes", "1", "true"}
    falsy = {"n", "no", "0", "false"}
    if value in truthy:
        return True
    if value in falsy:
        return False
    raise ValueError("请输入 y/yes/1/true 或 n/no/0/false")


def _parse_required_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Bilibili 视频 URL 不能为空")
    return value


def _parse_optional_text(raw: str) -> str | None:
    return _normalize_optional_text(raw)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _build_script_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="b2t",
        description="Bilibili 视频转文字：下载音频 → 转录 → Markdown → 总结",
    )
    parser.add_argument("url", help="Bilibili 视频 URL")
    parser.add_argument(
        "-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）"
    )
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument(
        "--no-summary", action="store_true", help="跳过 LLM 总结步骤"
    )
    parser.add_argument(
        "--summary-preset",
        default=None,
        help="指定总结 preset 名称（默认使用配置中的 preset）",
    )
    parser.add_argument(
        "--summary-profile",
        default=None,
        help="指定总结模型 profile 名称（默认使用配置中的 summarize.profile）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细日志"
    )
    return parser


def _build_monitor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="b2t monitor",
        description="监控 Bilibili UP 主动态，发现新视频后自动总结并推送到飞书",
    )
    parser.add_argument(
        "-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）"
    )
    parser.add_argument("--once", action="store_true", help="仅执行一次检查")
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="清空监控状态文件，再开始监控",
    )
    parser.add_argument(
        "--bootstrap-unsummarized",
        type=int,
        default=0,
        help="测试用：回填最近前 N 个尚未总结过的视频",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细日志"
    )
    return parser


def _validate_script_args(
    parser: argparse.ArgumentParser, parsed: argparse.Namespace
) -> CLIArgs:
    url = parsed.url.strip()
    if not url:
        parser.error("url 不能为空")

    config = _normalize_optional_text(parsed.config)
    if parsed.config is not None and config is None:
        parser.error("--config 不能为空字符串")

    output = _normalize_optional_text(parsed.output)
    if parsed.output is not None and output is None:
        parser.error("--output 不能为空字符串")

    summary_preset = _normalize_optional_text(parsed.summary_preset)
    if parsed.summary_preset is not None and summary_preset is None:
        parser.error("--summary-preset 不能为空字符串")

    summary_profile = _normalize_optional_text(parsed.summary_profile)
    if parsed.summary_profile is not None and summary_profile is None:
        parser.error("--summary-profile 不能为空字符串")

    return CLIArgs(
        url=url,
        config=config,
        output=output,
        no_summary=bool(parsed.no_summary),
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        verbose=bool(parsed.verbose),
    )


def _validate_monitor_args(parsed: argparse.Namespace) -> MonitorCLIArgs:
    config = _normalize_optional_text(parsed.config)
    if parsed.config is not None and config is None:
        raise ValueError("--config 不能为空字符串")
    if not isinstance(parsed.bootstrap_unsummarized, int):
        raise ValueError("--bootstrap-unsummarized 必须是整数")
    if parsed.bootstrap_unsummarized < 0:
        raise ValueError("--bootstrap-unsummarized 不能小于 0")

    return MonitorCLIArgs(
        config=config,
        once=bool(parsed.once),
        reset_state=bool(parsed.reset_state),
        bootstrap_unsummarized_count=int(parsed.bootstrap_unsummarized),
        verbose=bool(parsed.verbose),
    )


def _run_interactive_mode(console: Console) -> CLIArgs | None:
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Container
        from textual.widgets import Footer, Header, Input, Static
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"缺少依赖 {exc.name}，请安装 `textual` 后再使用交互模式"
        ) from exc

    steps: tuple[PromptStep, ...] = (
        PromptStep(
            key="url",
            question="请输入 Bilibili 视频 URL",
            parse=_parse_required_url,
            hint="示例: https://www.bilibili.com/video/BVxxxxxxxxx",
        ),
        PromptStep(
            key="config",
            question="配置文件路径（可选，回车使用默认配置）",
            parse=_parse_optional_text,
        ),
        PromptStep(
            key="output",
            question="输出目录（可选，回车使用配置中的 output_dir）",
            parse=_parse_optional_text,
        ),
        PromptStep(
            key="no_summary",
            question="是否跳过总结步骤？(y/N)",
            parse=lambda raw: _parse_bool_input(raw, default=False),
            default_hint="N",
        ),
        PromptStep(
            key="summary_preset",
            question="总结 preset（可选，回车使用配置默认值）",
            parse=_parse_optional_text,
        ),
        PromptStep(
            key="summary_profile",
            question="总结 profile（可选，回车使用配置默认值）",
            parse=_parse_optional_text,
        ),
        PromptStep(
            key="verbose",
            question="启用详细日志？(y/N)",
            parse=lambda raw: _parse_bool_input(raw, default=False),
            default_hint="N",
        ),
    )

    class InteractiveApp(App[CLIArgs | None]):
        CSS = """
        Screen {
            align: center middle;
            background: #eef3fb;
            color: #0f172a;
        }
        Header {
            background: #0d9488;
            color: #f8fafc;
            text-style: bold;
        }
        Footer {
            background: #0f766e;
            color: #ecfeff;
        }
        #panel {
            width: 90%;
            max-width: 110;
            border: round #94a3b8;
            background: #f8fafc;
            padding: 1 2;
        }
        #badge {
            width: auto;
            border: round #99f6e4;
            background: #ecfeff;
            color: #0f766e;
            text-style: bold;
            padding: 0 1;
            margin-bottom: 1;
        }
        #title {
            color: #0f172a;
            text-style: bold;
        }
        #step {
            color: #64748b;
            margin-bottom: 1;
        }
        #question {
            color: #334155;
            text-style: bold;
            margin-bottom: 1;
        }
        #hint {
            color: #64748b;
            margin-top: 1;
        }
        #error {
            color: #dc2626;
            text-style: bold;
            margin-top: 1;
        }
        Input {
            margin-top: 1;
            border: round #cbd5e1;
            background: #ffffff;
            color: #0f172a;
        }
        Input:focus {
            border: round #22d3ee;
        }
        """
        BINDINGS = [Binding("ctrl+c", "cancel", "取消")]

        def __init__(self) -> None:
            super().__init__()
            self._answers: dict[str, object] = {}
            self._step_index = 0

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Container(id="panel"):
                yield Static("B2T CLI", id="badge")
                yield Static("B2T 交互模式", id="title")
                yield Static("", id="step")
                yield Static("", id="question")
                yield Input(placeholder="请输入并回车", id="answer")
                yield Static("", id="hint")
                yield Static("", id="error")
            yield Footer()

        def on_mount(self) -> None:
            self._show_current_step()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if self._step_index >= len(steps):
                return

            step = steps[self._step_index]
            raw_value = event.value.strip()
            try:
                value = step.parse(raw_value)
            except ValueError as exc:
                self.query_one("#error", Static).update(str(exc))
                self.query_one("#answer", Input).value = ""
                return

            self._answers[step.key] = value
            self._step_index += 1
            self._skip_optional_summary_steps_if_needed()
            self._show_current_step()

        def action_cancel(self) -> None:
            self.exit(None)

        def _skip_optional_summary_steps_if_needed(self) -> None:
            while self._step_index < len(steps):
                current = steps[self._step_index]
                if current.key not in {"summary_preset", "summary_profile"}:
                    return
                if bool(self._answers.get("no_summary")):
                    self._step_index += 1
                    continue
                return

        def _show_current_step(self) -> None:
            if self._step_index >= len(steps):
                self.exit(
                    CLIArgs(
                        url=str(self._answers["url"]),
                        config=_coerce_optional_text(self._answers.get("config")),
                        output=_coerce_optional_text(self._answers.get("output")),
                        no_summary=bool(self._answers.get("no_summary")),
                        summary_preset=_coerce_optional_text(
                            self._answers.get("summary_preset")
                        ),
                        summary_profile=_coerce_optional_text(
                            self._answers.get("summary_profile")
                        ),
                        verbose=bool(self._answers.get("verbose")),
                    )
                )
                return

            step = steps[self._step_index]
            self.query_one("#step", Static).update(
                f"步骤 {self._step_index + 1} / {len(steps)}"
            )
            self.query_one("#question", Static).update(step.question)

            hint_parts: list[str] = []
            if step.hint:
                hint_parts.append(step.hint)
            if step.default_hint:
                hint_parts.append(f"默认值: {step.default_hint}")
            self.query_one("#hint", Static).update("；".join(hint_parts))

            self.query_one("#error", Static).update("")
            answer = self.query_one("#answer", Input)
            answer.value = ""
            answer.focus()

    result = InteractiveApp().run()
    return result


def _print_results(
    console: Console, results: dict[str, StoredArtifact]
) -> None:
    table = Table(
        title="输出文件",
        title_style="bold #0f766e",
        header_style="bold #334155",
        border_style="#94a3b8",
    )
    table.add_column("阶段", style="#0f766e", no_wrap=True)
    table.add_column("存储", style="#0284c7")
    table.add_column("对象 Key", style="#334155")
    table.add_column("文件名", style="#16a34a")

    for stage, artifact in results.items():
        table.add_row(
            stage,
            artifact.backend,
            artifact.storage_key,
            artifact.filename,
        )

    console.print("")
    console.print(table)


def _run_pipeline_with_args(args: CLIArgs, console: Console) -> int:
    _configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]配置错误:[/] {exc}")
        return 1

    try:
        results = run_pipeline(
            args.url,
            config,
            skip_summary=args.no_summary,
            summary_preset=args.summary_preset,
            summary_profile=args.summary_profile,
            output_dir=args.output,
        )
    except KeyboardInterrupt:
        console.print("[bold #334155]已取消[/bold #334155]")
        return 130
    except Exception as exc:
        logging.error("执行失败: %s", exc)
        console.print(f"[bold red]执行失败:[/] {exc}")
        return 1

    console.print("[bold #16a34a]完成[/bold #16a34a]")
    _print_results(console, results)

    bvid = extract_bvid(args.url)
    if bvid is None:
        return 0

    db_dir = config.download.db_dir
    try:
        # Extract metadata from results
        metadata = results.get("_metadata")
        author = metadata.author if metadata else ""
        pubdate = metadata.pubdate if metadata else ""

        record_pipeline_run(
            db=HistoryDB(db_dir),
            bvid=bvid,
            results=results,
            author=author,
            pubdate=pubdate,
            summary_preset=args.summary_preset,
            summary_profile=args.summary_profile,
        )
    except Exception as exc:  # noqa: BLE001
        logging.warning("记录历史转录失败: %s", exc)

    return 0


def _run_monitor_with_args(args: MonitorCLIArgs, console: Console) -> int:
    _configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]配置错误:[/] {exc}")
        return 1

    if not config.monitor.enabled:
        console.print(
            "[bold red]配置错误:[/] [monitor].enabled = true 后才能启动监控"
        )
        return 1

    service = BilibiliMonitorService(config)
    try:
        if args.reset_state:
            service.reset_state()
            console.print("[bold #0f766e]监控状态已重置[/bold #0f766e]")
        service.run(
            once=args.once,
            bootstrap_unsummarized_count=args.bootstrap_unsummarized_count,
        )
    except KeyboardInterrupt:
        console.print("[bold #334155]已停止监控[/bold #334155]")
        return 130
    except Exception as exc:
        logging.error("监控执行失败: %s", exc)
        console.print(f"[bold red]监控执行失败:[/] {exc}")
        return 1
    finally:
        service.close()

    console.print("[bold #16a34a]监控检查完成[/bold #16a34a]")
    return 0


def main() -> None:
    console = Console()
    argv = sys.argv[1:]

    if argv and argv[0] == "monitor":
        parser = _build_monitor_parser()
        parsed = parser.parse_args(argv[1:])
        try:
            args = _validate_monitor_args(parsed)
        except ValueError as exc:
            console.print(f"[bold red]参数错误:[/] {exc}")
            sys.exit(2)
        exit_code = _run_monitor_with_args(args, console)
        if exit_code != 0:
            sys.exit(exit_code)
        return

    if argv:
        parser = _build_script_parser()
        parsed = parser.parse_args(argv)
        args = _validate_script_args(parser, parsed)
    else:
        try:
            args = _run_interactive_mode(console)
        except RuntimeError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            sys.exit(1)
        if args is None:
            console.print("[bold #334155]已取消[/bold #334155]")
            sys.exit(130)

    exit_code = _run_pipeline_with_args(args, console)
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
