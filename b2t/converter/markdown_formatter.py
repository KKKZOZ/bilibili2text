"""Markdown formatting utility"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


def format_markdown_with_markdownlint(md_path: Path | str) -> None:
    """Format a Markdown file using markdownlint-cli2

    This function automatically fixes common Markdown formatting issues, including:
    - Missing blank lines before tables
    - Table column alignment issues
    - Trailing whitespace
    - And more

    Args:
        md_path: Markdown file path

    Note:
        - Skips silently if markdownlint-cli2 is not installed
        - Continues even if markdownlint reports errors (uses || true)
        - Certain configuration warnings are ignored (e.g. line length limits)
    """
    md_path = Path(md_path)

    if not md_path.exists():
        logger.warning("Markdown file does not exist, skipping formatting: %s", md_path)
        return

    if not shutil.which("markdownlint-cli2"):
        logger.debug("markdownlint-cli2 not installed, skipping Markdown formatting")
        return

    try:
        # Use || true to ignore errors, as some configuration warnings are not relevant
        # For example: MD013 (line length limits), MD060 (table column alignment), etc.
        subprocess.run(
            f'markdownlint-cli2 --fix "{md_path}" || true',
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            cwd=md_path.parent,
        )
        logger.debug("Formatted with markdownlint-cli2: %s", md_path)
    except Exception as e:
        logger.debug("markdownlint-cli2 run failed, ignored: %s", e)


def batch_format_markdown(directory: Path | str, pattern: str = "*.md") -> int:
    """Batch format Markdown files in a directory

    Args:
        directory: Directory path
        pattern: File matching pattern (default: "*.md")

    Returns:
        Number of formatted files
    """
    directory = Path(directory)
    count = 0

    for md_file in directory.glob(pattern):
        if md_file.is_file():
            format_markdown_with_markdownlint(md_file)
            count += 1

    logger.info("Formatted %d Markdown files", count)
    return count
