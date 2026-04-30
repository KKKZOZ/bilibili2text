#!/usr/bin/env python3
"""Command-line tool for formatting Markdown files"""

import argparse
import sys
from pathlib import Path

# Add the project root directory to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from b2t.converter.markdown_formatter import (
    format_markdown_with_markdownlint,
    batch_format_markdown,
)


def main():
    parser = argparse.ArgumentParser(
        description="使用 markdownlint-cli2 格式化 Markdown 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 格式化单个文件
  python scripts/format_markdown.py file.md

  # 格式化多个文件
  python scripts/format_markdown.py file1.md file2.md file3.md

  # 批量格式化目录中的所有 .md 文件
  python scripts/format_markdown.py --directory ./transcriptions

  # 批量格式化目录中匹配模式的文件
  python scripts/format_markdown.py --directory ./transcriptions --pattern "*_summary.md"
        """,
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="要格式化的 Markdown 文件路径",
    )

    parser.add_argument(
        "-d",
        "--directory",
        help="批量格式化目录中的所有 Markdown 文件",
    )

    parser.add_argument(
        "-p",
        "--pattern",
        default="*.md",
        help="文件匹配模式（默认: *.md）",
    )

    args = parser.parse_args()

    if not args.files and not args.directory:
        parser.error("必须指定文件或目录")

    # Format specified files
    if args.files:
        for file_path in args.files:
            path = Path(file_path)
            if not path.exists():
                print(f"错误: 文件不存在: {file_path}", file=sys.stderr)
                continue

            print(f"格式化: {file_path}")
            format_markdown_with_markdownlint(path)

    # Batch format directory
    if args.directory:
        directory = Path(args.directory)
        if not directory.exists():
            print(f"错误: 目录不存在: {args.directory}", file=sys.stderr)
            sys.exit(1)

        if not directory.is_dir():
            print(f"错误: 不是目录: {args.directory}", file=sys.stderr)
            sys.exit(1)

        print(f"批量格式化目录: {args.directory}")
        print(f"文件模式: {args.pattern}")
        count = batch_format_markdown(directory, args.pattern)
        print(f"共格式化 {count} 个文件")


if __name__ == "__main__":
    main()
