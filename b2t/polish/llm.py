"""LLM 总结/润色"""

import logging
from pathlib import Path

from openai import OpenAI

from b2t.config import PolishConfig, SummaryPresetsConfig, resolve_summary_preset_name

logger = logging.getLogger(__name__)


def summarize(
    md_path: Path | str,
    config: PolishConfig,
    summary_presets: SummaryPresetsConfig,
    preset: str | None = None,
) -> Path:
    """使用 LLM 对 Markdown 文件进行总结

    Args:
        md_path: Markdown 文件路径
        config: 润色配置
        summary_presets: 总结 preset 配置
        preset: 可选，覆盖默认 preset 名称

    Returns:
        生成的总结文件路径

    Raises:
        Exception: API 调用失败时抛出
    """
    md_path = Path(md_path)
    content = md_path.read_text(encoding="utf-8")

    preset_name = resolve_summary_preset_name(
        polish=config,
        summary_presets=summary_presets,
        override=preset,
    )
    template = summary_presets.presets[preset_name].prompt_template
    prompt = template.format(content=content)

    logger.info("正在使用 %s 模型进行总结（preset: %s）...", config.model, preset_name)

    client = OpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )

    response = client.chat.completions.create(
        model=config.model,
        messages=[{"role": "user", "content": prompt}],
    )

    summary = response.choices[0].message.content

    summary_path = md_path.parent / f"{md_path.stem}_summary.md"
    summary_path.write_text(summary, encoding="utf-8")

    logger.info("总结已保存到: %s", summary_path)
    return summary_path
