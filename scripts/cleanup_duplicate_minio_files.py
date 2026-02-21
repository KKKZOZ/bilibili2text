#!/usr/bin/env python3
"""清理 MinIO 中路径错误的重复文件（b2t/b2t/ 路径）"""

import argparse
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from b2t.config import load_config
from b2t.storage.minio_client import MinIOStorageBackend

logger = logging.getLogger(__name__)


def main():
    """清理 MinIO 中的重复文件"""

    parser = argparse.ArgumentParser(
        description="清理 MinIO 中路径错误的重复文件（b2t/b2t/ 路径）",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式：只列出要删除的文件，不实际删除",
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

    # 查找重复的文件
    logger.info("查找路径错误的重复文件...")
    try:
        # 查找 b2t/b2t/ 路径下的所有文件
        duplicate_prefix = f"{config.storage.minio.base_prefix}/{config.storage.minio.base_prefix}/"

        objects = minio_backend._client.list_objects(
            bucket_name=config.storage.minio.bucket,
            prefix=duplicate_prefix,
            recursive=True,
        )

        duplicate_files = []
        for obj in objects:
            object_name = getattr(obj, "object_name", "")
            if object_name:
                duplicate_files.append(object_name)

        logger.info(f"找到 {len(duplicate_files)} 个重复文件")

        if not duplicate_files:
            logger.info("没有找到重复文件")
            return

        # 显示要删除的文件
        logger.info("=" * 60)
        logger.info("将要删除的文件:")
        for i, object_name in enumerate(duplicate_files, 1):
            logger.info(f"  [{i}/{len(duplicate_files)}] {object_name}")

        if args.dry_run:
            logger.info("=" * 60)
            logger.info("DRY-RUN 模式：不会实际删除文件")
            logger.info(f"如需删除，请运行: python {sys.argv[0]}")
            return

        # 确认删除
        logger.info("=" * 60)
        response = input(f"确认删除这 {len(duplicate_files)} 个文件？(yes/no): ")
        if response.lower() not in ["yes", "y"]:
            logger.info("取消删除")
            return

        # 删除文件
        logger.info("开始删除...")
        deleted_count = 0
        error_count = 0

        for i, object_name in enumerate(duplicate_files, 1):
            try:
                logger.info(f"  [{i}/{len(duplicate_files)}] 删除: {object_name}")
                minio_backend._delete_object(object_name)
                deleted_count += 1
            except Exception as e:
                logger.error(f"  ✗ 删除失败: {e}")
                error_count += 1

        # 输出统计
        logger.info("=" * 60)
        logger.info("清理完成!")
        logger.info(f"  总文件数: {len(duplicate_files)}")
        logger.info(f"  已删除: {deleted_count}")
        logger.info(f"  失败: {error_count}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"列出对象失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
