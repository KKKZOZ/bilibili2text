"""Markdown to TXT conversion (via pandoc)"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


class MarkdownToTextConverter:
    """Markdown to TXT converter."""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """Convert Markdown to plain text TXT using pandoc."""
        if output_path is None:
            output_path = input_path.with_suffix(".txt")

        if shutil.which("pandoc") is None:
            raise RuntimeError("pandoc not found, please install pandoc first")

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
            raise RuntimeError(f"pandoc conversion failed: {detail}") from exc

        logger.info("TXT file generated: %s", output_path)
        return output_path


def convert_md_to_txt(
    md_path: Path | str,
    output_path: Path | str | None = None,
) -> Path:
    """
    Convert Markdown to plain text TXT using pandoc.

    This is a legacy convenience function that uses MarkdownToTextConverter internally.
    """
    converter = MarkdownToTextConverter()
    return converter.convert(
        Path(md_path),
        Path(output_path) if output_path else None,
    )
