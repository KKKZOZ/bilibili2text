#!/usr/bin/env python3
"""从 MinIO 下载所有 Markdown 文件，格式化后重新上传"""

import argparse
import logging
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from b2t.config import load_config
from b2t.converter.markdown_formatter import format_markdown_with_markdownlint
from b2t.storage.minio_client import MinIOStorageBackend

logger = logging.getLogger(__name__)


def main():
    """处理 MinIO 中的所有 Markdown 文件"""

    parser = argparse.ArgumentParser(
        description="从 MinIO 下载所有 Markdown 文件，格式化后重新上传",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 格式化所有 Markdown 文件
  python scripts/format_minio_markdown.py

  # 只格式化特定前缀的文件
  python scripts/format_minio_markdown.py --prefix "BV1cZsKzNEPW"

  # 只格式化 _summary.md 文件
  python scripts/format_minio_markdown.py --suffix "_summary.md"

  # 试运行（不上传）
  python scripts/format_minio_markdown.py --dry-run

  # 启用调试日志
  python scripts/format_minio_markdown.py --debug
        """,
    )

    parser.add_argument(
        "--prefix",
        help="只处理以此前缀开头的文件（例如：BV1cZsKzNEPW）",
    )

    parser.add_argument(
        "--suffix",
        default=".md",
        help="只处理以此后缀结尾的文件（默认：.md）",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式：只下载和格式化，不上传回 MinIO",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志",
    )

    args = parser.parse_args()

    # 配置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 加载配置
    logger.info("加载配置文件...")
    config = load_config()

    # 检查是否使用 MinIO
    if config.storage.backend != "minio":
        logger.error(f"当前 storage backend 是 {config.storage.backend}，不是 minio")
        sys.exit(1)

    # 初始化 MinIO 客户端
    logger.info("连接到 MinIO...")
    minio_backend = MinIOStorageBackend(config.storage.minio)
    logger.info(
        f"已连接到 MinIO: {config.storage.minio.endpoint}, "
        f"bucket: {config.storage.minio.bucket}, "
        f"base_prefix: {config.storage.minio.base_prefix}"
    )

    # 列出所有对象
    logger.info("列出 MinIO 中的所有对象...")
    try:
        # 使用 base_prefix 作为前缀
        prefix = config.storage.minio.base_prefix.strip("/")
        if prefix:
            prefix = f"{prefix}/"

        objects = minio_backend._client.list_objects(
            bucket_name=config.storage.minio.bucket,
            prefix=prefix,
            recursive=True,
        )

        # 筛选出所有匹配的 Markdown 文件
        md_files = []
        for obj in objects:
            object_name = getattr(obj, "object_name", "")

            # 检查后缀
            if not object_name.lower().endswith(args.suffix.lower()):
                continue

            # 检查前缀（如果指定）
            if args.prefix:
                # 获取相对路径（去掉 base_prefix）
                relative_path = minio_backend._strip_base_prefix(object_name)
                # 检查文件名是否包含指定前缀
                if args.prefix.lower() not in relative_path.lower():
                    continue

            md_files.append(object_name)

        logger.info(f"找到 {len(md_files)} 个 Markdown 文件")

        if not md_files:
            logger.info("没有找到 Markdown 文件，退出")
            return

        # 处理每个文件
        processed_count = 0
        error_count = 0

        with tempfile.TemporaryDirectory(prefix="b2t-format-") as tmpdir:
            tmpdir_path = Path(tmpdir)

            for i, object_name in enumerate(md_files, 1):
                logger.info(f"[{i}/{len(md_files)}] 处理: {object_name}")

                try:
                    # 下载文件
                    filename = Path(object_name).name
                    local_path = tmpdir_path / filename

                    logger.debug(f"  下载到: {local_path}")
                    with minio_backend.open_stream(object_name) as stream:
                        content = stream.read()
                        local_path.write_bytes(content)

                    # 记录原始内容
                    original_content = local_path.read_text(encoding="utf-8")
                    original_size = len(original_content)

                    # 格式化
                    logger.debug(f"  格式化中...")
                    format_markdown_with_markdownlint(local_path)

                    # 检查是否有变化
                    formatted_content = local_path.read_text(encoding="utf-8")
                    formatted_size = len(formatted_content)

                    if original_content == formatted_content:
                        logger.info(f"  ✓ 无需修改（{original_size} 字节）")
                        continue

                    # 上传回 MinIO（除非是 dry-run 模式）
                    if args.dry_run:
                        logger.info(
                            f"  ✓ 已修改但未上传（dry-run）（{original_size} -> {formatted_size} 字节）"
                        )
                    else:
                        logger.debug(f"  上传回 MinIO...")
                        # 使用相对路径（去掉 base_prefix），因为 store_file 会自动添加 base_prefix
                        relative_key = minio_backend._strip_base_prefix(object_name)
                        minio_backend.store_file(local_path, object_key=relative_key)
                        logger.info(
                            f"  ✓ 已更新（{original_size} -> {formatted_size} 字节）"
                        )

                    processed_count += 1

                except Exception as e:
                    logger.error(f"  ✗ 处理失败: {e}", exc_info=True)
                    error_count += 1
                    continue

                finally:
                    # 清理临时文件
                    if local_path.exists():
                        local_path.unlink()

        # 输出统计
        logger.info("=" * 60)
        if args.dry_run:
            logger.info("处理完成（DRY-RUN 模式，未上传到 MinIO）!")
        else:
            logger.info("处理完成!")
        logger.info(f"  总文件数: {len(md_files)}")
        logger.info(f"  已{'修改' if args.dry_run else '更新'}: {processed_count}")
        logger.info(f"  无需修改: {len(md_files) - processed_count - error_count}")
        logger.info(f"  失败: {error_count}")
        if args.prefix:
            logger.info(f"  过滤前缀: {args.prefix}")
        if args.suffix != ".md":
            logger.info(f"  过滤后缀: {args.suffix}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"列出对象失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
