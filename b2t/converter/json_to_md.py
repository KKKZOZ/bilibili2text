"""JSON transcription result to Markdown"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def ms_to_mmss(milliseconds: int) -> str:
    """Convert milliseconds to MM:SS format"""
    total_seconds = milliseconds // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _extract_timed_sentences(data: dict) -> list[tuple[int, str]]:
    """Extract (millisecond timestamp, text) list from different STT provider JSON formats."""
    timed_sentences: list[tuple[int, str]] = []

    # Qwen format: transcripts[].sentences[]
    transcripts = data.get("transcripts", [])
    if isinstance(transcripts, list) and transcripts:
        for transcript in transcripts:
            if not isinstance(transcript, dict):
                continue
            sentences = transcript.get("sentences", [])
            if not isinstance(sentences, list):
                continue

            for sentence in sentences:
                if not isinstance(sentence, dict):
                    continue
                begin_time = int(sentence.get("begin_time", 0))
                text = str(sentence.get("text", "")).strip()
                if text:
                    timed_sentences.append((begin_time, text))
        return timed_sentences

    # Groq format: segments[]
    segments = data.get("segments", [])
    if isinstance(segments, list) and segments:
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start_seconds = float(segment.get("start", 0))
            text = str(segment.get("text", "")).strip()
            if text:
                timed_sentences.append((int(start_seconds * 1000), text))
        return timed_sentences

    # Volc format: result.utterances[]
    result = data.get("result")
    if isinstance(result, dict):
        utterances = result.get("utterances", [])
        if isinstance(utterances, list) and utterances:
            for utterance in utterances:
                if not isinstance(utterance, dict):
                    continue
                start_time = int(utterance.get("start_time", 0))
                text = str(utterance.get("text", "")).strip()
                if text:
                    timed_sentences.append((start_time, text))
            return timed_sentences

    # Fallback: full text
    text = str(data.get("text", "")).strip()
    if not text and isinstance(result, dict):
        text = str(result.get("text", "")).strip()
    if text:
        timed_sentences.append((0, text))

    return timed_sentences


def _join_paragraph_texts(parts: list[str]) -> str:
    """Join paragraph text, avoiding different provider outputs being concatenated without spaces."""
    if not parts:
        return ""

    merged = parts[0]
    for part in parts[1:]:
        if not part:
            continue

        if not merged:
            merged = part
            continue

        if merged[-1].isspace() or part[0].isspace():
            merged += part
            continue

        if merged[-1] in "，。！？,.!?;；:：、)]】}”\"'":
            merged += part
            continue

        merged += " " + part

    return merged


def convert_json_to_md(
    json_path: Path | str,
    output_path: Path | str | None = None,
    min_length: int = 60,
) -> Path:
    """Convert JSON transcription result to Markdown format

    Segmentation strategy:
    - By default, split by sentence
    - If sentence length is <= min_length, merge it with the next sentence

    Args:
        json_path: JSON file path
        output_path: Output path, auto-generated when None
        min_length: Minimum sentence length, short sentence merge threshold

    Returns:
        Generated Markdown file path
    """
    json_path = Path(json_path)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if output_path is None:
        output_path = (
            json_path.parent / f"{json_path.stem.replace('_transcription', '')}.md"
        )
    else:
        output_path = Path(output_path)

    file_name = json_path.stem.replace("_transcription", "")

    lines = []

    # Title
    lines.append(f"{file_name}_原文\n")

    # Date and time
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"{current_time}")

    # Process transcription content (compatible with Qwen and Groq)
    timed_sentences = _extract_timed_sentences(data)

    i = 0
    while i < len(timed_sentences):
        start_time, text = timed_sentences[i]
        if not text:
            i += 1
            continue

        paragraph_texts = [text]

        while len(text) <= min_length and i + 1 < len(timed_sentences):
            i += 1
            _, next_text = timed_sentences[i]
            if next_text:
                paragraph_texts.append(next_text)
                text = next_text

        time_str = ms_to_mmss(start_time)
        lines.append(f"Speaker {time_str}")
        lines.append(_join_paragraph_texts(paragraph_texts))
        lines.append("")

        i += 1

    output_path.write_text("\n".join(lines), encoding="utf-8")

    logger.info("Markdown file generated: %s", output_path)
    return output_path
