import argparse
import sys
import time
from pathlib import Path

# 允许在 scripts 目录直接运行时也能导入项目内的 b2t 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import questionary
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from b2t.config import (
    load_config,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)


def _is_openrouter_endpoint(endpoint: str) -> bool:
    return "openrouter.ai" in endpoint.lower()


def _resolve_openrouter_max_tokens(model: str) -> int | None:
    normalized = model.strip().lower()
    if "qwen3-max-thinking" in normalized:
        return 32768
    if "qwen3-max" in normalized:
        return 32768
    return None


def _get_field(data: object, field: str) -> object | None:
    if isinstance(data, dict):
        return data.get(field)
    return getattr(data, field, None)


def _as_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _pick_token_count(usage: object | None, keys: tuple[str, ...]) -> int | None:
    if usage is None:
        return None
    for key in keys:
        token_count = _as_int(_get_field(usage, key))
        if token_count is not None:
            return token_count
    return None


def _extract_reasoning_text(delta: object) -> str:
    direct_reasoning = _get_field(delta, "reasoning_content")
    if isinstance(direct_reasoning, str) and direct_reasoning:
        return direct_reasoning

    alias_reasoning = _get_field(delta, "reasoning")
    if isinstance(alias_reasoning, str) and alias_reasoning:
        return alias_reasoning

    reasoning_details = _get_field(delta, "reasoning_details")
    parts: list[str] = []
    if isinstance(reasoning_details, list):
        for item in reasoning_details:
            text = _get_field(item, "text")
            if isinstance(text, str) and text:
                if not parts or parts[-1] != text:
                    parts.append(text)
                continue

            summary = _get_field(item, "summary")
            if isinstance(summary, str) and summary:
                if not parts or parts[-1] != summary:
                    parts.append(summary)
                continue
            if isinstance(summary, list):
                for summary_item in summary:
                    if isinstance(summary_item, str) and summary_item:
                        if not parts or parts[-1] != summary_item:
                            parts.append(summary_item)

    return "".join(parts)


def _find_txt_files() -> list[Path]:
    """查找当前目录及子目录中的 .txt 文件"""
    cwd = Path.cwd()
    txt_files = list(cwd.glob("**/*.txt"))
    txt_files = [f for f in txt_files if f.is_file() and ".venv" not in str(f)]
    txt_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return txt_files[:50]


def _run_interactive_config(config_path: str | None) -> dict[str, str] | None:
    """使用 questionary 运行交互式配置"""
    console = Console()
    console.print("\n[bold cyan]⚙️  交互式配置[/bold cyan]\n")

    # 加载配置
    config = load_config(config_path)

    # 交互式选择
    try:
        # 1. 首先选择输入来源
        input_source = questionary.select(
            "选择输入来源:",
            choices=[
                questionary.Choice(title="📄 从文件读取", value="file"),
                questionary.Choice(title="⌨️  从终端输入", value="terminal"),
            ],
            use_shortcuts=True,
            use_arrow_keys=True,
        ).ask()

        if input_source is None:
            console.print("[yellow]已取消[/yellow]")
            return None

        # 2. 根据来源获取内容
        content_source = None
        if input_source == "file":
            # 查找文件
            txt_files = _find_txt_files()
            if not txt_files:
                console.print("[red]未找到任何 .txt 文件，请检查当前目录[/red]")
                sys.exit(1)

            file_choices = [
                questionary.Choice(
                    title=f"📄 {f.name} ({f.parent})",
                    value=str(f),
                )
                for f in txt_files
            ]

            content_source = questionary.select(
                "选择输入文件:",
                choices=file_choices,
                use_shortcuts=True,
                use_arrow_keys=True,
            ).ask()

            if content_source is None:
                console.print("[yellow]已取消[/yellow]")
                return None

        else:  # terminal
            console.print("\n[cyan]请输入要总结的内容（输入完成后按 Ctrl+D 或输入单独一行的 EOF）:[/cyan]\n")
            lines = []
            try:
                while True:
                    line = input()
                    if line.strip() == "EOF":
                        break
                    lines.append(line)
            except EOFError:
                pass

            content_source = "\n".join(lines).strip()
            if not content_source:
                console.print("[red]未输入任何内容[/red]")
                return None

            console.print(f"\n[green]已输入 {len(content_source)} 个字符[/green]\n")

        # 3. 选择 profile
        profile_choices = [
            questionary.Choice(title=f"⚙️  {name}", value=name)
            for name in config.summarize.profiles.keys()
        ]

        profile = questionary.select(
            "选择 summarize profile:",
            choices=profile_choices,
            default=config.summarize.profile,
            use_shortcuts=True,
            use_arrow_keys=True,
        ).ask()

        if profile is None:
            console.print("[yellow]已取消[/yellow]")
            return None

        # 4. 选择 preset
        preset_choices = [
            questionary.Choice(
                title=f"📝 {preset.label}",
                value=preset_name,
            )
            for preset_name, preset in config.summary_presets.presets.items()
        ]

        preset = questionary.select(
            "选择 summary preset:",
            choices=preset_choices,
            default=config.summarize.preset,
            use_shortcuts=True,
            use_arrow_keys=True,
        ).ask()

        if preset is None:
            console.print("[yellow]已取消[/yellow]")
            return None

        console.print("\n[green]✓ 配置完成[/green]\n")
        return {
            "input_source": input_source,
            "content_source": content_source,
            "profile": profile,
            "preset": preset,
        }

    except KeyboardInterrupt:
        console.print("\n[yellow]已取消[/yellow]")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 summarize 配置下的流式输出")
    parser.add_argument(
        "-i",
        "--input",
        default="test_thinking_input.txt",
        help="默认读取的输入文本文件路径（默认: test_thinking_input.txt）",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="配置文件路径（默认读取项目根目录 config.toml）",
    )
    parser.add_argument(
        "--summary-profile",
        default=None,
        help="覆盖 summarize.profile，例如 dashscope/openrouter",
    )
    parser.add_argument(
        "--summary-preset",
        default=None,
        help="覆盖 summarize.preset，例如 timeline_merge/key_points",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help="覆盖模型名（默认使用 summarize profile 对应 model）",
    )
    args = parser.parse_args()

    input_file_path: str | None = None
    input_content: str | None = None  # 终端输入的内容
    input_source_type: str = "file"  # "file" 或 "terminal"
    selected_profile_override: str | None = None
    selected_preset_override: str | None = None

    has_any_arg = any(
        [
            args.input != "test_thinking_input.txt",
            args.summary_profile,
            args.summary_preset,
            args.model,
        ]
    )

    if not has_any_arg:
        user_config = _run_interactive_config(args.config)
        if user_config is None:
            sys.exit(0)
        input_source_type = user_config["input_source"]
        if input_source_type == "file":
            input_file_path = user_config["content_source"]
        else:  # terminal
            input_content = user_config["content_source"]
        selected_profile_override = user_config["profile"]
        selected_preset_override = user_config["preset"]
    else:
        input_file_path = args.input
        selected_profile_override = (
            args.summary_profile.strip() if args.summary_profile else None
        )
        selected_preset_override = (
            args.summary_preset.strip() if args.summary_preset else None
        )

    if args.summary_preset is not None and not selected_preset_override:
        raise ValueError("--summary-preset 不能为空字符串")

    config = load_config(args.config)
    selected_profile = selected_profile_override or config.summarize.profile

    selected_preset = resolve_summary_preset_name(
        summarize=config.summarize,
        summary_presets=config.summary_presets,
        override=selected_preset_override,
    )
    model_profile = resolve_summarize_model_profile(
        config.summarize,
        override=selected_profile,
    )
    selected_model = args.model.strip() if args.model else model_profile.model

    if not model_profile.api_key:
        raise ValueError(
            f"summarize.profiles.{selected_profile}.api_key 为空，请先在配置文件中设置"
        )

    client = OpenAI(
        api_key=model_profile.api_key,
        base_url=model_profile.endpoint,
    )

    # 根据输入来源获取内容
    if input_source_type == "file":
        input_path = Path(input_file_path)
        if not input_path.exists():
            raise FileNotFoundError(f"未找到输入文件: {input_path}")
        output_path = input_path.with_name(f"{input_path.stem}_answer.md")
        raw_content = input_path.read_text(encoding="utf-8").strip()
        if not raw_content:
            raise ValueError(f"输入文件为空: {input_path}")
        input_display_name = str(input_path)
    else:  # terminal
        raw_content = input_content.strip()
        if not raw_content:
            raise ValueError("终端输入内容为空")
        output_path = Path("terminal_input_answer.md")
        input_display_name = f"终端输入 ({len(raw_content)} 字符)"

    prompt_template = config.summary_presets.presets[selected_preset].prompt_template
    prompt_text = prompt_template.format(content=raw_content)

    # 使用 rich 显示配置信息
    console = Console()
    config_table = Table(title="⚙️  配置信息", show_header=False, border_style="cyan")
    config_table.add_column("项目", style="yellow", width=18)
    config_table.add_column("值", style="white")

    config_table.add_row("输入来源", "📄 文件" if input_source_type == "file" else "⌨️  终端")
    config_table.add_row("Profile", selected_profile)
    config_table.add_row("Preset", f"{selected_preset} ({config.summary_presets.presets[selected_preset].label})")
    config_table.add_row("模型", selected_model)
    config_table.add_row("接口地址", model_profile.endpoint)
    if _is_openrouter_endpoint(model_profile.endpoint) and model_profile.providers:
        config_table.add_row("Providers", ', '.join(model_profile.providers))

    console.print(config_table)

    messages = [{"role": "user", "content": prompt_text}]
    is_openrouter = _is_openrouter_endpoint(model_profile.endpoint)
    extra_body: dict[str, object] = {}
    if is_openrouter:
        if config.summarize.enable_thinking:
            extra_body["reasoning"] = {"enabled": True}
            # Legacy fallback accepted by OpenRouter.
            extra_body["include_reasoning"] = True
        else:
            extra_body["reasoning"] = {"effort": "none", "exclude": True}
            extra_body["include_reasoning"] = False
    else:
        extra_body["enable_thinking"] = config.summarize.enable_thinking

    if is_openrouter and model_profile.providers:
        extra_body["provider"] = {"order": list(model_profile.providers)}

    request_kwargs: dict[str, object] = {
        "model": selected_model,
        "messages": messages,
        "extra_body": extra_body,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if is_openrouter:
        max_tokens = _resolve_openrouter_max_tokens(selected_model)
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens

    completion = client.chat.completions.create(**request_kwargs)

    reasoning_content = ""
    answer_content = ""
    is_answering = False
    usage = None
    start_time = time.perf_counter()

    console = Console()
    console.print("\n")
    console.print(Panel("💭 思考过程", style="magenta", expand=False))
    print()

    for chunk in completion:
        chunk_usage = _get_field(chunk, "usage")
        if chunk_usage is not None:
            usage = chunk_usage

        choices = _get_field(chunk, "choices")
        if not isinstance(choices, list) or not choices:
            continue

        delta = _get_field(choices[0], "delta")
        if delta is None:
            continue

        reasoning_piece = _extract_reasoning_text(delta)
        if reasoning_piece:
            if not is_answering:
                print(reasoning_piece, end="", flush=True)
            reasoning_content += reasoning_piece

        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                print("\n")
                console.print(Panel("✨ 完整回复", style="green", expand=False))
                print()
                is_answering = True
            print(delta.content, end="", flush=True)
            answer_content += delta.content

    elapsed = max(time.perf_counter() - start_time, 1e-9)
    output_chars = len(reasoning_content) + len(answer_content)

    # 使用 rich 显示统计信息
    console = Console()
    print("\n")

    # 创建统计表格
    stats_table = Table(title="📊 输出统计", show_header=False, border_style="blue")
    stats_table.add_column("项目", style="cyan", width=20)
    stats_table.add_column("值", style="green")

    stats_table.add_row(
        "📁 输入来源" if input_source_type == "terminal" else "📁 输入文件",
        input_display_name
    )
    stats_table.add_row("⚙️  配置 Profile", selected_profile)
    stats_table.add_row("📝 总结 Preset", f"{selected_preset} ({config.summary_presets.presets[selected_preset].label})")
    stats_table.add_row("🤖 模型", selected_model)
    stats_table.add_row("⏱️  总耗时", f"{elapsed:.2f} 秒")
    stats_table.add_row("📄 输出字符数", f"{output_chars:,}")

    token_speed = None
    completion_tokens = None

    # 尝试获取 token 信息
    if usage:
        completion_tokens = _pick_token_count(
            usage,
            (
                "completion_tokens",
                "output_tokens",
                "generated_tokens",
                "completionTokens",
                "outputTokens",
                "generatedTokens",
            ),
        )

    if completion_tokens and completion_tokens > 0:
        token_speed = completion_tokens / elapsed
        stats_table.add_row("🚀 输出速度", f"{token_speed:.2f} token/秒")
        stats_table.add_row("🎯 总 Token 数", f"{completion_tokens:,}")

        # 尝试获取输入 token 数
        prompt_tokens = _pick_token_count(
            usage,
            (
                "prompt_tokens",
                "input_tokens",
                "promptTokens",
                "inputTokens",
            ),
        )
        if prompt_tokens:
            stats_table.add_row("📥 输入 Token 数", f"{prompt_tokens:,}")

        # 尝试获取总 token 数
        total_tokens = _pick_token_count(
            usage,
            (
                "total_tokens",
                "totalTokens",
            ),
        )
        if total_tokens:
            stats_table.add_row("💰 总消耗 Token", f"{total_tokens:,}")
        elif prompt_tokens:
            # 如果没有 total_tokens，自己计算
            total = completion_tokens + prompt_tokens
            stats_table.add_row("💰 总消耗 Token", f"{total:,}")
    else:
        # 如果没有 token 信息，显示提示
        stats_table.add_row("ℹ️  Token 统计", "API 未返回 token 信息")
        if usage:
            # 输出 usage 对象的内容用于调试
            usage_dump = None
            if hasattr(usage, "model_dump"):
                usage_dump = usage.model_dump()  # type: ignore[assignment]
            elif isinstance(usage, dict):
                usage_dump = usage

            print(f"\n[调试] usage 对象: {usage}", file=sys.stderr)
            print(f"[调试] usage 类型: {type(usage)}", file=sys.stderr)
            if usage_dump is not None:
                print(f"[调试] usage 内容: {usage_dump}", file=sys.stderr)
            else:
                print(f"[调试] usage 属性: {dir(usage)}", file=sys.stderr)

    console.print(stats_table)

    stats_lines = [
        f"- 输入来源: {'文件' if input_source_type == 'file' else '终端输入'}",
        f"- 输入信息: {input_display_name}",
        f"- 配置 profile: {selected_profile}",
        f"- 总结 preset: {selected_preset}",
        f"- 模型: {selected_model}",
        f"- endpoint: {model_profile.endpoint}",
        f"- OpenRouter providers: {', '.join(model_profile.providers) if model_profile.providers else '(default)'}",
        f"- 总耗时: {elapsed:.2f} 秒",
        f"- 输出字符数(思考+回复): {output_chars}",
    ]
    if token_speed is not None and completion_tokens:
        stats_lines.append(f"- 输出速度: {token_speed:.2f} token/秒")
        stats_lines.append(f"- 总 Token 数: {completion_tokens}")

    markdown_output = "\n".join(
        [
            "# 思考过程",
            "",
            reasoning_content if reasoning_content else "_无思考内容_",
            "",
            "# 完整回复",
            "",
            answer_content if answer_content else "_无回复内容_",
            "",
            "# 输出统计",
            "",
            *stats_lines,
            "",
        ]
    )
    output_path.write_text(markdown_output, encoding="utf-8")
    print(f"结果已写入: {output_path}")


if __name__ == "__main__":
    main()
