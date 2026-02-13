"""Markdown 转 TXT（通过 pandoc）"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


class MarkdownToTextConverter:
    """Markdown 转 TXT 转换器。"""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """使用 pandoc 将 Markdown 转换为纯文本 TXT。"""
        if output_path is None:
            output_path = input_path.with_suffix(".txt")

        if shutil.which("pandoc") is None:
            raise RuntimeError("未找到 pandoc，请先安装 pandoc 后再试")

        try:
            subprocess.run(
                [
                    "pandoc",
                    str(input_path),
                    "-f",
                    "markdown",
                    "-t",
                    "plain",
                    "-o",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc 转换失败: {detail}") from exc

        logger.info("TXT 文件已生成: %s", output_path)
        return output_path


def convert_md_to_txt(
    md_path: Path | str,
    output_path: Path | str | None = None,
) -> Path:
    """
    使用 pandoc 将 Markdown 转换为纯文本 TXT。

    这是一个遗留的便捷函数，内部使用 MarkdownToTextConverter。
    """
    converter = MarkdownToTextConverter()
    return converter.convert(
        Path(md_path),
        Path(output_path) if output_path else None,
    )
