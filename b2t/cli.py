"""CLI 入口"""

import argparse
import logging
import sys

from b2t.config import load_config
from b2t.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="b2t",
        description="Bilibili 视频转文字：下载音频 → 转录 → Markdown → 总结",
    )
    parser.add_argument("url", help="Bilibili 视频 URL")
    parser.add_argument(
        "-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）"
    )
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument(
        "--no-summary", action="store_true", help="跳过 LLM 总结步骤"
    )
    parser.add_argument(
        "--summary-preset",
        default=None,
        help="指定总结 preset 名称（默认使用配置中的 preset）",
    )
    parser.add_argument(
        "--summary-profile",
        default=None,
        help="指定总结模型 profile 名称（默认使用配置中的 summarize.profile）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细日志"
    )

    args = parser.parse_args()

    # 配置 logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 避免 yutto 下载阶段刷屏 HTTP 请求日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        logging.error("%s", e)
        sys.exit(1)

    try:
        results = run_pipeline(
            args.url,
            config,
            skip_summary=args.no_summary,
            summary_preset=args.summary_preset,
            summary_profile=args.summary_profile,
            output_dir=args.output,
        )

        print(f"\n完成！输出文件：")
        for key, path in results.items():
            print(f"  {key}: {path}")

    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except Exception as e:
        logging.error("执行失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
