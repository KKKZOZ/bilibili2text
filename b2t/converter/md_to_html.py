"""Markdown 转 HTML（通过 Pandoc）"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


class MarkdownToHtmlConverter:
    """Markdown 转 HTML 转换器。"""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        使用 pandoc 将 Markdown 转换为 HTML。

        Args:
            input_path: Markdown 文件路径
            output_path: 输出 HTML 路径（可选）
            **options: 额外选项
                - standalone: 是否生成独立 HTML（包含 <html>, <head> 等）

        Returns:
            输出 HTML 文件路径
        """
        if output_path is None:
            output_path = input_path.with_suffix(".html")

        if shutil.which("pandoc") is None:
            raise RuntimeError("未找到 pandoc，请先安装 pandoc 后再试")

        standalone = options.get("standalone", True)

        cmd = [
            "pandoc",
            str(input_path),
            "-f",
            "markdown",
            "-t",
            "html",
            "-o",
            str(output_path),
        ]

        if standalone:
            cmd.append("--standalone")

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc HTML 转换失败: {detail}") from exc

        logger.info("HTML 文件已生成: %s", output_path)
        return output_path
