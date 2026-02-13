"""Markdown 转 PDF（通过 Pandoc）"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


class MarkdownToPdfConverter:
    """Markdown 转 PDF 转换器。"""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        使用 pandoc 将 Markdown 转换为 PDF。

        Args:
            input_path: Markdown 文件路径
            output_path: 输出 PDF 路径（可选）
            **options: 额外选项
                - pdf_engine: PDF 引擎（xelatex, pdflatex 等）

        Returns:
            输出 PDF 文件路径
        """
        if output_path is None:
            output_path = input_path.with_suffix(".pdf")

        if shutil.which("pandoc") is None:
            raise RuntimeError("未找到 pandoc，请先安装 pandoc 后再试")

        pdf_engine = options.get("pdf_engine", "xelatex")

        cmd = [
            "pandoc",
            str(input_path),
            "-f",
            "markdown",
            "-o",
            str(output_path),
            "--pdf-engine",
            pdf_engine,
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"pandoc PDF 转换失败: {detail}") from exc

        logger.info("PDF 文件已生成: %s", output_path)
        return output_path
