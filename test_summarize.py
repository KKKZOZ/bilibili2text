import argparse
import time
from pathlib import Path

from openai import OpenAI

from b2t.config import load_config, resolve_summarize_model_profile


def _is_openrouter_endpoint(endpoint: str) -> bool:
    return "openrouter.ai" in endpoint.lower()


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
        "-m",
        "--model",
        default=None,
        help="覆盖模型名（默认使用 summarize profile 对应 model）",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    selected_profile = (
        args.summary_profile.strip()
        if args.summary_profile
        else config.summarize.profile
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

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"未找到输入文件: {input_path}")
    output_path = input_path.with_name(f"{input_path.stem}_answer.md")

    prompt_text = input_path.read_text(encoding="utf-8").strip()
    if not prompt_text:
        raise ValueError(f"输入文件为空: {input_path}")

    print(f"使用配置 profile: {selected_profile}")
    print(f"使用模型: {selected_model}")
    print(f"接口地址: {model_profile.endpoint}")
    if _is_openrouter_endpoint(model_profile.endpoint) and model_profile.providers:
        print(f"OpenRouter providers: {', '.join(model_profile.providers)}")

    messages = [{"role": "user", "content": prompt_text}]
    extra_body = {"enable_thinking": config.summarize.enable_thinking}
    extra_body_groq = {"reasoning_effort": "high"}
    if _is_openrouter_endpoint(model_profile.endpoint) and model_profile.providers:
        extra_body["provider"] = {"order": list(model_profile.providers)}

    completion = client.chat.completions.create(
        model=selected_model,
        messages=messages,
        extra_body=extra_body,
        stream=True,
        stream_options={"include_usage": True},
    )

    reasoning_content = ""
    answer_content = ""
    is_answering = False
    usage = None
    start_time = time.perf_counter()
    print("\n" + "=" * 20 + "思考过程" + "=" * 20 + "\n")

    for chunk in completion:
        if not chunk.choices:
            usage = chunk.usage
            print("\n" + "=" * 20 + "Token 消耗" + "=" * 20 + "\n")
            print(chunk.usage)
            continue

        delta = chunk.choices[0].delta

        if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
            if not is_answering:
                print(delta.reasoning_content, end="", flush=True)
            reasoning_content += delta.reasoning_content

        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                is_answering = True
            print(delta.content, end="", flush=True)
            answer_content += delta.content

    elapsed = max(time.perf_counter() - start_time, 1e-9)
    output_chars = len(reasoning_content) + len(answer_content)
    chars_per_sec = output_chars / elapsed

    print("\n\n" + "=" * 20 + "输出统计" + "=" * 20)
    print(f"输入文件: {input_path}")
    print(f"总耗时: {elapsed:.2f} 秒")
    print(f"输出字符数(思考+回复): {output_chars}")
    print(f"大概输出速度: {chars_per_sec:.2f} 字符/秒")

    token_speed = None
    if usage and getattr(usage, "completion_tokens", None):
        token_speed = usage.completion_tokens / elapsed
        print(f"大概输出速度: {token_speed:.2f} token/秒")

    stats_lines = [
        f"- 输入文件: {input_path}",
        f"- 配置 profile: {selected_profile}",
        f"- 模型: {selected_model}",
        f"- endpoint: {model_profile.endpoint}",
        f"- OpenRouter providers: {', '.join(model_profile.providers) if model_profile.providers else '(default)'}",
        f"- 总耗时: {elapsed:.2f} 秒",
        f"- 输出字符数(思考+回复): {output_chars}",
        f"- 大概输出速度: {chars_per_sec:.2f} 字符/秒",
    ]
    if token_speed is not None:
        stats_lines.append(f"- 大概输出速度: {token_speed:.2f} token/秒")

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
