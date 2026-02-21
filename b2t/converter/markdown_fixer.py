"""Markdown 文件修复工具，自动处理常见的格式问题"""

from pathlib import Path


class MarkdownFixer:
    """修复常见的 Markdown 格式问题"""

    @staticmethod
    def fix_table_spacing(content: str) -> str:
        """
        确保表格前后有空行。

        Args:
            content: Markdown 文本内容

        Returns:
            修复后的 Markdown 文本
        """
        lines = content.splitlines()
        fixed_lines = []

        for i, line in enumerate(lines):
            # 检查当前行是否是表格的开始
            if line.strip().startswith('|') and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # 检查下一行是否是表格分隔符（包含 |--- 或 |:--）
                if next_line.startswith('|') and ('---' in next_line or ':--' in next_line):
                    # 这是表格的开始，检查上一行是否为空
                    if i > 0 and fixed_lines and fixed_lines[-1].strip() != '':
                        # 在表格前添加空行
                        fixed_lines.append('')

            fixed_lines.append(line)

        # 保持原始的尾部换行符
        result = '\n'.join(fixed_lines)
        if content.endswith('\n') and not result.endswith('\n'):
            result += '\n'

        return result

    @staticmethod
    def fix_file(input_path: Path, output_path: Path | None = None) -> Path:
        """
        修复 Markdown 文件。

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径（如果为 None，则覆盖原文件）

        Returns:
            输出文件路径
        """
        if output_path is None:
            output_path = input_path

        content = input_path.read_text(encoding='utf-8')
        fixed_content = MarkdownFixer.fix_table_spacing(content)
        output_path.write_text(fixed_content, encoding='utf-8')

        return output_path
