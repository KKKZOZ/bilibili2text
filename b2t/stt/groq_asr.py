"""Groq Whisper speech-to-text (chunking + merging)"""

import json
import logging
import re
import tempfile
import time
from pathlib import Path

from groq import Groq, RateLimitError
from pydub import AudioSegment

from b2t.config import STTConfig
from b2t.stt.base import ProgressCallback, STTProvider

logger = logging.getLogger(__name__)


def _export_chunk(chunk: AudioSegment, temp_path: str, bitrate: str) -> float:
    """Export a single audio chunk to m4a, preferring macOS hardware encoding."""
    export_start = time.time()
    try:
        chunk.export(
            temp_path,
            format="ipod",
            bitrate=bitrate,
            codec="aac_at",
        )
    except Exception:
        chunk.export(
            temp_path,
            format="ipod",
            bitrate=bitrate,
        )
    return time.time() - export_start


def _transcribe_single_chunk(
    client: Groq,
    chunk: AudioSegment,
    chunk_num: int,
    total_chunks: int,
    config: STTConfig,
) -> tuple[dict, float, float]:
    total_api_time = 0.0
    total_export_time = 0.0

    while True:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            export_time = _export_chunk(chunk, temp_path, config.groq_bitrate)
            total_export_time += export_time

            chunk_size = Path(temp_path).stat().st_size
            chunk_size_mb = chunk_size / (1024 * 1024)
            logger.info(
                "Chunk %s/%s size: %.2f MB (%s bytes), export time: %.2fs",
                chunk_num,
                total_chunks,
                chunk_size_mb,
                f"{chunk_size:,}",
                export_time,
            )

            start_time = time.time()
            try:
                with open(temp_path, "rb") as f:
                    result = client.audio.transcriptions.create(
                        file=("chunk.m4a", f.read()),
                        model=config.groq_model,
                        language=config.language,
                        response_format="verbose_json",
                    )

                api_time = time.time() - start_time
                total_api_time += api_time
                logger.info(
                    "Chunk %s/%s API time: %.2fs", chunk_num, total_chunks, api_time
                )

                data = result.model_dump() if hasattr(result, "model_dump") else result
                if not isinstance(data, dict):
                    data = {"text": str(getattr(result, "text", "")), "segments": []}
                return data, total_api_time, total_export_time

            except RateLimitError:
                logger.warning(
                    "Rate limit hit for chunk %s - retrying in 60 seconds...", chunk_num
                )
                time.sleep(60)
                continue

        finally:
            Path(temp_path).unlink(missing_ok=True)


def _find_longest_common_sequence(
    sequences: list[str], match_by_words: bool = True
) -> str:
    if not sequences:
        return ""

    if match_by_words:
        parsed = [
            [word for word in re.split(r"(\s+\w+)", seq) if word] for seq in sequences
        ]
    else:
        parsed = [list(seq) for seq in sequences]

    left_sequence = parsed[0]
    left_length = len(left_sequence)
    total_sequence: list[str] = []

    for right_sequence in parsed[1:]:
        max_matching = 0.0
        right_length = len(right_sequence)
        max_indices = (left_length, left_length, 0, 0)

        for i in range(1, left_length + right_length + 1):
            eps = float(i) / 10000.0

            left_start = max(0, left_length - i)
            left_stop = min(left_length, left_length + right_length - i)
            left = left_sequence[left_start:left_stop]

            right_start = max(0, i - left_length)
            right_stop = min(right_length, i)
            right = right_sequence[right_start:right_stop]

            if len(left) != len(right):
                raise RuntimeError(
                    "Mismatched subsequences detected during transcript merging."
                )

            matches = sum(a == b for a, b in zip(left, right))
            matching = matches / float(i) + eps

            if matches > 1 and matching > max_matching:
                max_matching = matching
                max_indices = (left_start, left_stop, right_start, right_stop)

        left_start, left_stop, right_start, right_stop = max_indices
        left_mid = (left_stop + left_start) // 2
        right_mid = (right_stop + right_start) // 2

        total_sequence.extend(left_sequence[:left_mid])
        left_sequence = right_sequence[right_mid:]
        left_length = len(left_sequence)

    total_sequence.extend(left_sequence)
    return "".join(total_sequence)


def _normalize_segment(segment: object) -> dict:
    if isinstance(segment, dict):
        return segment
    if hasattr(segment, "model_dump"):
        data = segment.model_dump()
        if isinstance(data, dict):
            return data
    return {
        "text": getattr(segment, "text", ""),
        "start": getattr(segment, "start", 0),
        "end": getattr(segment, "end", 0),
    }


def merge_transcripts(results: list[tuple[dict, int]]) -> dict:
    """Merge Groq chunked transcription results."""
    logger.info("Merging Groq chunk results...")

    has_segments = False
    has_words = False
    words: list[dict] = []

    for chunk, chunk_start_ms in results:
        segments = chunk.get("segments", []) if isinstance(chunk, dict) else []
        if segments:
            has_segments = True

        chunk_words = chunk.get("words", []) if isinstance(chunk, dict) else []
        if chunk_words:
            has_words = True
            for word in chunk_words:
                if isinstance(word, dict):
                    word["start"] = word.get("start", 0) + (chunk_start_ms / 1000)
                    word["end"] = word.get("end", 0) + (chunk_start_ms / 1000)
                    words.append(word)

    if not has_segments:
        texts = []
        for chunk, _ in results:
            if isinstance(chunk, dict):
                texts.append(chunk.get("text", ""))
        output = {"text": " ".join(texts), "segments": []}
        if has_words:
            output["words"] = words
        return output

    final_segments: list[dict] = []
    processed_chunks: list[list[dict]] = []

    for i, (chunk, _) in enumerate(results):
        segments = chunk.get("segments", []) if isinstance(chunk, dict) else []
        normalized_segments = [_normalize_segment(segment) for segment in segments]

        if i < len(results) - 1:
            next_start_ms = results[i + 1][1]
            current_segments: list[dict] = []
            overlap_segments: list[dict] = []

            for segment in normalized_segments:
                segment_end = float(segment.get("end", 0))
                if segment_end * 1000 > next_start_ms:
                    overlap_segments.append(segment)
                else:
                    current_segments.append(segment)

            if overlap_segments:
                merged_overlap = overlap_segments[0].copy()
                merged_overlap["text"] = " ".join(
                    str(seg.get("text", "")) for seg in overlap_segments
                )
                merged_overlap["end"] = overlap_segments[-1].get("end", 0)
                current_segments.append(merged_overlap)

            processed_chunks.append(current_segments)
        else:
            processed_chunks.append(normalized_segments)

    for i in range(len(processed_chunks) - 1):
        if not processed_chunks[i] or not processed_chunks[i + 1]:
            continue

        if len(processed_chunks[i]) > 1:
            final_segments.extend(processed_chunks[i][:-1])

        last_segment = processed_chunks[i][-1]
        first_segment = processed_chunks[i + 1][0]

        merged_text = _find_longest_common_sequence(
            [
                str(last_segment.get("text", "")),
                str(first_segment.get("text", "")),
            ]
        )

        merged_segment = last_segment.copy()
        merged_segment["text"] = merged_text
        merged_segment["end"] = first_segment.get("end", 0)
        final_segments.append(merged_segment)

    if processed_chunks and processed_chunks[-1]:
        final_segments.extend(processed_chunks[-1])

    final_text = " ".join(str(segment.get("text", "")) for segment in final_segments)
    output = {"text": final_text, "segments": final_segments}
    if has_words:
        output["words"] = words
    return output


def transcribe_local_audio(audio_path: Path, config: STTConfig) -> dict:
    """Transcribe local audio in chunks using Groq."""
    if not config.groq_api_key:
        raise ValueError("Missing stt.groq_api_key config")

    if config.groq_chunk_length <= 0:
        raise ValueError("stt.groq_chunk_length must be greater than 0")

    if config.groq_overlap < 0:
        raise ValueError("stt.groq_overlap must not be negative")

    step_seconds = config.groq_chunk_length - config.groq_overlap
    if step_seconds <= 0:
        raise ValueError("stt.groq_overlap must be less than stt.groq_chunk_length")

    logger.info("Starting Groq transcription for audio: %s", audio_path)
    client = Groq(
        api_key=config.groq_api_key, base_url=config.groq_base_url, max_retries=0
    )

    audio = AudioSegment.from_file(audio_path)
    duration = len(audio)
    logger.info("Audio duration: %.2fs", duration / 1000)

    chunk_ms = config.groq_chunk_length * 1000
    step_ms = step_seconds * 1000
    total_chunks = (duration // step_ms) + 1
    logger.info("Processing %s chunks...", total_chunks)

    results: list[tuple[dict, int]] = []
    total_api_time = 0.0
    total_export_time = 0.0

    for i in range(total_chunks):
        start = i * step_ms
        if start >= duration:
            break

        end = min(start + chunk_ms, duration)
        logger.info(
            "Processing chunk %s/%s, range %.1fs-%.1fs",
            i + 1,
            total_chunks,
            start / 1000,
            end / 1000,
        )

        chunk = audio[start:end]
        result, chunk_api_time, chunk_export_time = _transcribe_single_chunk(
            client,
            chunk,
            i + 1,
            total_chunks,
            config,
        )
        total_api_time += chunk_api_time
        total_export_time += chunk_export_time
        results.append((result, start))

    final_result = merge_transcripts(results)

    logger.info(
        "Groq transcription timing summary - export: %.2fs, api: %.2fs, total: %.2fs",
        total_export_time,
        total_api_time,
        total_export_time + total_api_time,
    )

    return final_result


class GroqSTTProvider(STTProvider):
    """Groq STT Provider (local chunked transcription)."""

    def __init__(self, stt_config: STTConfig) -> None:
        self._stt_config = stt_config

    def transcribe(
        self,
        audio_path: Path,
        work_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        def emit(stage: str, label: str, progress: int) -> None:
            if progress_callback is not None:
                progress_callback(stage, label, progress)

        emit("transcribing", "Speech transcription", 45)
        result = transcribe_local_audio(audio_path, self._stt_config)

        json_path = work_dir / f"{audio_path.stem}_transcription.json"
        emit("transcribing", "Speech transcription", 65)
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return json_path
