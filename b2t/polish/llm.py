"""LLM 总结/润色"""

import logging
from pathlib import Path

from openai import OpenAI

from b2t.config import PolishConfig

logger = logging.getLogger(__name__)


def summarize(
    md_path: Path | str,
    config: PolishConfig,
    prompt_template: str | None = None,
) -> Path:
    """使用 LLM 对 Markdown 文件进行总结

    Args:
        md_path: Markdown 文件路径
        config: 润色配置
        prompt_template: 自定义提示词模板，须包含 {content} 占位符。
                         为 None 时使用配置中的默认模板。

    Returns:
        生成的总结文件路径

    Raises:
        Exception: API 调用失败时抛出
    """
    md_path = Path(md_path)
    content = md_path.read_text(encoding="utf-8")

    template = prompt_template or config.prompt_template
    prompt = template.format(content=content)

    logger.info("正在使用 %s 模型进行总结...", config.model)

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
