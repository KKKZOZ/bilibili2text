"""Markdown file fixer that automatically handles common formatting issues"""

from pathlib import Path


class MarkdownFixer:
    """Fix common Markdown formatting issues"""

    @staticmethod
    def fix_table_spacing(content: str) -> str:
        """
        Ensure there are blank lines before and after tables.

        Args:
            content: Markdown text content

        Returns:
            Fixed Markdown text
        """
        lines = content.splitlines()
        fixed_lines = []

        for i, line in enumerate(lines):
            # Check if current line is the start of a table
            if line.strip().startswith("|") and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Check if next line is a table separator (contains |--- or |:--)
                if next_line.startswith("|") and (
                    "---" in next_line or ":--" in next_line
                ):
                    # This is a table start, check if previous line is not empty
                    if i > 0 and fixed_lines and fixed_lines[-1].strip() != "":
                        # Add a blank line before the table
                        fixed_lines.append("")

            fixed_lines.append(line)

        # Preserve original trailing newline
        result = "\n".join(fixed_lines)
        if content.endswith("\n") and not result.endswith("\n"):
            result += "\n"

        return result

    @staticmethod
    def fix_file(input_path: Path, output_path: Path | None = None) -> Path:
        """
        Fix a Markdown file.

        Args:
            input_path: Input file path
            output_path: Output file path (if None, overwrites the original file)

        Returns:
            Output file path
        """
        if output_path is None:
            output_path = input_path

        content = input_path.read_text(encoding="utf-8")
        fixed_content = MarkdownFixer.fix_table_spacing(content)
        output_path.write_text(fixed_content, encoding="utf-8")

        return output_path
