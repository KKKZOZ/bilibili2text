"""Markdown to HTML conversion (via Pandoc)"""

import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


class MarkdownToHtmlConverter:
    """Markdown to HTML converter."""

    def convert(
        self,
        input_path: Path,
        output_path: Path | None = None,
        **options,
    ) -> Path:
        """
        Convert Markdown to HTML using pandoc.

        Args:
            input_path: Markdown file path
            output_path: Output HTML path (optional)
            **options: Extra options
                - standalone: Whether to generate standalone HTML (includes <html>, <head>, etc.)

        Returns:
            Output HTML file path
        """
        if output_path is None:
            output_path = input_path.with_suffix(".html")

        if shutil.which("pandoc") is None:
            raise RuntimeError("pandoc not found, please install pandoc first")

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
            raise RuntimeError(f"pandoc HTML conversion failed: {detail}") from exc

        logger.info("HTML file generated: %s", output_path)
        return output_path
