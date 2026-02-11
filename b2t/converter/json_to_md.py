"""JSON 转录结果转 Markdown"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def ms_to_mmss(milliseconds: int) -> str:
    """将毫秒转换为 MM:SS 格式"""
    total_seconds = milliseconds // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def convert_json_to_md(
    json_path: Path | str,
    output_path: Path | str | None = None,
    min_length: int = 60,
) -> Path:
    """将 JSON 转录结果转换为 Markdown 格式

    分段策略：
    - 默认按照 sentence 分段
    - 如果句子长度 <= min_length，则合并到下一个句子

    Args:
        json_path: JSON 文件路径
        output_path: 输出路径，为 None 时自动生成
        min_length: 最小句子长度，短句合并阈值

    Returns:
        生成的 Markdown 文件路径
    """
    json_path = Path(json_path)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if output_path is None:
        output_path = (
            json_path.parent
            / f"{json_path.stem.replace('_transcription', '')}.md"
        )
    else:
        output_path = Path(output_path)

    file_name = json_path.stem.replace("_transcription", "")

    lines = []

    # 标题
    lines.append(f"{file_name}_原文\n")

    # 日期时间
    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    lines.append(f"{current_time}")

    # 处理转录内容
    transcripts = data.get("transcripts", [])

    for transcript in transcripts:
        sentences = transcript.get("sentences", [])

        if not sentences:
            continue

        i = 0
        while i < len(sentences):
            sentence = sentences[i]
            begin_time = sentence.get("begin_time", 0)
            text = sentence.get("text", "").strip()

            if not text:
                i += 1
                continue

            paragraph_texts = [text]
            start_time = begin_time

            while len(text) <= min_length and i + 1 < len(sentences):
                i += 1
                next_sentence = sentences[i]
                next_text = next_sentence.get("text", "").strip()

                if next_text:
                    paragraph_texts.append(next_text)
                    text = next_text

            time_str = ms_to_mmss(start_time)
            lines.append(f"发言人 {time_str}")
            lines.append("".join(paragraph_texts))
            lines.append("")

            i += 1

    output_path.write_text("\n".join(lines), encoding="utf-8")

    logger.info("Markdown 文件已生成: %s", output_path)
    return output_path
