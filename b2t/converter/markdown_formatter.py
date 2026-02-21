"""Markdown 格式化工具"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


def format_markdown_with_markdownlint(md_path: Path | str) -> None:
    """使用 markdownlint-cli2 格式化 Markdown 文件

    该函数会自动修复常见的 Markdown 格式问题，包括：
    - 表格前缺少空行
    - 表格列对齐问题
    - 行尾空格
    - 等等

    Args:
        md_path: Markdown 文件路径

    Note:
        - 如果 markdownlint-cli2 未安装，会静默跳过
        - 即使 markdownlint 报错也会继续执行（使用 || true）
        - 某些配置项的报错会被忽略（例如行长度限制）
    """
    md_path = Path(md_path)

    if not md_path.exists():
        logger.warning("Markdown 文件不存在，跳过格式化: %s", md_path)
        return

    if not shutil.which("markdownlint-cli2"):
        logger.debug("markdownlint-cli2 未安装，跳过 Markdown 格式化")
        return

    try:
        # 使用 || true 来忽略错误，因为某些配置项的报错我们不关心
        # 例如：MD013 (行长度限制)、MD060 (表格列对齐) 等
        subprocess.run(
            f'markdownlint-cli2 --fix "{md_path}" || true',
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            cwd=md_path.parent,
        )
        logger.debug("已使用 markdownlint-cli2 格式化: %s", md_path)
    except Exception as e:
        logger.debug("markdownlint-cli2 运行失败，已忽略: %s", e)


def batch_format_markdown(directory: Path | str, pattern: str = "*.md") -> int:
    """批量格式化目录中的 Markdown 文件

    Args:
        directory: 目录路径
        pattern: 文件匹配模式（默认: "*.md"）

    Returns:
        格式化的文件数量
    """
    directory = Path(directory)
    count = 0

    for md_file in directory.glob(pattern):
        if md_file.is_file():
            format_markdown_with_markdownlint(md_file)
            count += 1

    logger.info("已格式化 %d 个 Markdown 文件", count)
    return count
