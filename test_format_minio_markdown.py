#!/usr/bin/env python3
"""测试 MinIO Markdown 格式化脚本（模拟）"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# 模拟 MinIO 对象
class MockMinIOObject:
    def __init__(self, object_name: str):
        self.object_name = object_name


def test_format_minio_markdown():
    """测试 MinIO Markdown 格式化流程"""

    print("=" * 60)
    print("测试 MinIO Markdown 格式化脚本")
    print("=" * 60)

    # 创建测试数据
    test_files = {
        "b2t/BV123456-20260216-120000/BV123456.md": """# 测试视频

## 内容总结
这是一段文字：
| 列1 | 列2 |
|-----|-----|
| A   | B   |
""",
        "b2t/BV789012-20260216-130000/BV789012_summary.md": """# 总结

## 要点
文字内容：
| 要点 | 说明 |
|------|------|
| 1    | 说明1 |
""",
        "b2t/BV345678-20260216-140000/BV345678_summary_table.md": """| 股票 | 板块 |
|------|------|
| A    | B    |
""",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        print("\n1. 模拟下载 Markdown 文件")
        print("-" * 60)

        # 保存原始文件
        for object_name, content in test_files.items():
            filename = Path(object_name).name
            local_path = tmpdir_path / filename
            local_path.write_text(content, encoding="utf-8")
            print(f"  创建测试文件: {filename}")
            print(f"    表格前空行: {'是' if '\\n\\n|' in content else '否'}")

        print("\n2. 格式化 Markdown 文件")
        print("-" * 60)

        from b2t.converter.markdown_formatter import format_markdown_with_markdownlint

        processed = 0
        unchanged = 0

        for object_name, original_content in test_files.items():
            filename = Path(object_name).name
            local_path = tmpdir_path / filename

            print(f"\n  处理: {filename}")
            print(f"    原始大小: {len(original_content)} 字节")

            # 格式化
            format_markdown_with_markdownlint(local_path)

            # 检查变化
            formatted_content = local_path.read_text(encoding="utf-8")
            print(f"    格式化后: {len(formatted_content)} 字节")

            if original_content != formatted_content:
                print(f"    状态: ✓ 已修改")
                print(f"    表格前空行: {'是' if '\\n\\n|' in formatted_content else '否'}")
                processed += 1

                # 显示差异
                original_lines = original_content.splitlines()
                formatted_lines = formatted_content.splitlines()
                if len(formatted_lines) > len(original_lines):
                    print(f"    添加了 {len(formatted_lines) - len(original_lines)} 行")
            else:
                print(f"    状态: - 无变化")
                unchanged += 1

        print("\n" + "=" * 60)
        print("测试完成!")
        print("=" * 60)
        print(f"  总文件数: {len(test_files)}")
        print(f"  已修改: {processed}")
        print(f"  未修改: {unchanged}")
        print("=" * 60)

        # 验证格式化效果
        print("\n3. 验证格式化效果")
        print("-" * 60)

        from b2t.converter.md_to_pdf import MarkdownToPdfConverter

        converter = MarkdownToPdfConverter()

        for object_name in test_files.keys():
            filename = Path(object_name).name
            local_path = tmpdir_path / filename

            try:
                html = converter._run_pandoc(local_path)
                has_table = "<table>" in html
                print(f"  {filename}: {'✓ 表格正常' if has_table else '✗ 无表格'}")
            except Exception as e:
                print(f"  {filename}: ✗ 错误 ({e})")


if __name__ == "__main__":
    test_format_minio_markdown()
