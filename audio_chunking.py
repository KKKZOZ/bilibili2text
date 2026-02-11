from groq import Groq, RateLimitError
from pydub import AudioSegment
import json
from pathlib import Path
from datetime import datetime
import time
import subprocess
import os
import tempfile
import re
from datetime import datetime as dt

# Optional PDF generation support
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

api_key = "your_groq_api_key_here"  # Replace with your actual Groq API key or set via environment variable


def preprocess_audio(input_path: Path) -> Path:
    """
    Preprocess audio file to 16kHz mono FLAC using ffmpeg.
    FLAC provides lossless compression for faster upload times.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Get original file size
    original_size = input_path.stat().st_size
    original_size_mb = original_size / (1024 * 1024)

    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as temp_file:
        output_path = Path(temp_file.name)

    print("Converting audio to 16kHz mono FLAC...")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                input_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "flac",
                "-y",
                output_path,
            ],
            check=True,
        )

        # Get processed file size
        processed_size = output_path.stat().st_size
        processed_size_mb = processed_size / (1024 * 1024)

        # Print file sizes
        print(
            f"Original file size: {original_size_mb:.2f} MB ({original_size:,} bytes)"
        )
        print(
            f"Processed file size: {processed_size_mb:.2f} MB ({processed_size:,} bytes)"
        )

        # Check if processed file is larger than original
        assert processed_size <= original_size, (
            f"Processed file ({processed_size_mb:.2f} MB) is larger than original "
            f"({original_size_mb:.2f} MB). This should not happen with FLAC compression."
        )

        return output_path
    # We'll raise an error if our FFmpeg conversion fails
    except subprocess.CalledProcessError as e:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg conversion failed: {e.stderr}")


def transcribe_single_chunk(
    client: Groq, chunk: AudioSegment, chunk_num: int, total_chunks: int
) -> tuple[dict, float, float]:
    """
    Transcribe a single audio chunk with Groq API.

    Args:
        client: Groq client instance
        chunk: Audio segment to transcribe
        chunk_num: Current chunk number
        total_chunks: Total number of chunks

    Returns:
        Tuple of (transcription result, API time, export time)

    Raises:
        Exception: If chunk transcription fails after retries
    """
    total_api_time = 0
    total_export_time = 0

    while True:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            # Export as m4a with lower bitrate for smaller file size
            # Use macOS hardware acceleration (AudioToolbox AAC encoder)
            export_start = time.time()
            chunk.export(
                temp_path,
                format="ipod",
                bitrate="64k",
                codec="aac_at",  # Use Apple's hardware-accelerated AAC encoder
            )
            export_time = time.time() - export_start
            total_export_time += export_time

            # Get chunk file size
            chunk_size = Path(temp_path).stat().st_size
            chunk_size_mb = chunk_size / (1024 * 1024)
            print(
                f"Chunk {chunk_num}/{total_chunks} size: {chunk_size_mb:.2f} MB ({chunk_size:,} bytes), "
                f"export time: {export_time:.2f}s"
            )

            start_time = time.time()
            try:
                with open(temp_path, "rb") as f:
                    result = client.audio.transcriptions.create(
                        file=("chunk.m4a", f.read()),
                        model="whisper-large-v3-turbo",
                        language="zh",  # We highly recommend specifying the language of your audio if you know it
                        response_format="verbose_json",
                    )
                api_time = time.time() - start_time
                total_api_time += api_time

                print(f"Chunk {chunk_num}/{total_chunks} API time: {api_time:.2f}s")
                return result, total_api_time, total_export_time

            except RateLimitError as e:
                print(
                    f"\nRate limit hit for chunk {chunk_num} - retrying in 60 seconds..."
                )
                time.sleep(60)  # default wait time
                continue

            except Exception as e:
                print(f"Error transcribing chunk {chunk_num}: {str(e)}")
                raise

        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)


def find_longest_common_sequence(
    sequences: list[str], match_by_words: bool = True
) -> str:
    """
    Find the optimal alignment between sequences with longest common sequence and sliding window matching.

    Args:
        sequences: List of text sequences to align and merge
        match_by_words: Whether to match by words (True) or characters (False)

    Returns:
        str: Merged sequence with optimal alignment

    Raises:
        RuntimeError: If there's a mismatch in sequence lengths during comparison
    """
    if not sequences:
        return ""

    # Convert input based on matching strategy
    if match_by_words:
        sequences = [
            [word for word in re.split(r"(\s+\w+)", seq) if word] for seq in sequences
        ]
    else:
        sequences = [list(seq) for seq in sequences]

    left_sequence = sequences[0]
    left_length = len(left_sequence)
    total_sequence = []

    for right_sequence in sequences[1:]:
        max_matching = 0.0
        right_length = len(right_sequence)
        max_indices = (left_length, left_length, 0, 0)

        # Try different alignments
        for i in range(1, left_length + right_length + 1):
            # Add epsilon to favor longer matches
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

            # Normalize matches by position and add epsilon
            matching = matches / float(i) + eps

            # Require at least 2 matches
            if matches > 1 and matching > max_matching:
                max_matching = matching
                max_indices = (left_start, left_stop, right_start, right_stop)

        # Use the best alignment found
        left_start, left_stop, right_start, right_stop = max_indices

        # Take left half from left sequence and right half from right sequence
        left_mid = (left_stop + left_start) // 2
        right_mid = (right_stop + right_start) // 2

        total_sequence.extend(left_sequence[:left_mid])
        left_sequence = right_sequence[right_mid:]
        left_length = len(left_sequence)

    # Add remaining sequence
    total_sequence.extend(left_sequence)

    # Join back into text
    if match_by_words:
        return "".join(total_sequence)
    return "".join(total_sequence)


def merge_transcripts(results: list[tuple[dict, int]]) -> dict:
    """
    Merge transcription chunks and handle overlaps.

    Works with responses from Groq API regardless of whether segments, words,
    or both were requested via timestamp_granularities.

    Args:
        results: List of (result, start_time) tuples

    Returns:
        dict: Merged transcription
    """
    print("\nMerging results...")

    # First, check if we have segments in our results
    has_segments = False
    for chunk, _ in results:
        data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
        if (
            "segments" in data
            and data["segments"] is not None
            and len(data["segments"]) > 0
        ):
            has_segments = True
            break

    # Process word-level timestamps regardless of segment presence
    has_words = False
    words = []

    for chunk, chunk_start_ms in results:
        # Convert Pydantic model to dict
        data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk

        # Process word timestamps if available
        if (
            isinstance(data, dict)
            and "words" in data
            and data["words"] is not None
            and len(data["words"]) > 0
        ):
            has_words = True
            # Adjust word timestamps based on chunk start time
            chunk_words = data["words"]
            for word in chunk_words:
                # Convert chunk_start_ms from milliseconds to seconds for word timestamp adjustment
                word["start"] = word["start"] + (chunk_start_ms / 1000)
                word["end"] = word["end"] + (chunk_start_ms / 1000)
            words.extend(chunk_words)
        elif hasattr(chunk, "words") and getattr(chunk, "words") is not None:
            has_words = True
            # Handle Pydantic model for words
            chunk_words = getattr(chunk, "words")
            processed_words = []
            for word in chunk_words:
                if hasattr(word, "model_dump"):
                    word_dict = word.model_dump()
                else:
                    # Create a dict from the word object
                    word_dict = {
                        "word": getattr(word, "word", ""),
                        "start": getattr(word, "start", 0) + (chunk_start_ms / 1000),
                        "end": getattr(word, "end", 0) + (chunk_start_ms / 1000),
                    }
                processed_words.append(word_dict)
            words.extend(processed_words)

    # If we don't have segments, just merge the full texts
    if not has_segments:
        print("No segments found in transcription results. Merging full texts only.")

        texts = []

        for chunk, _ in results:
            # Convert Pydantic model to dict
            data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk

            # Get text - handle both dictionary and object access
            if isinstance(data, dict):
                text = data.get("text", "")
            else:
                # For Pydantic models or other objects
                text = getattr(chunk, "text", "")

            texts.append(text)

        merged_text = " ".join(texts)
        result = {"text": merged_text}

        # Include word-level timestamps if available
        if has_words:
            result["words"] = words

        # Return an empty segments list since segments weren't requested
        result["segments"] = []
        return result

    # If we do have segments, proceed with the segment merging logic
    print("Merging segments across chunks...")
    final_segments = []
    processed_chunks = []

    for i, (chunk, chunk_start_ms) in enumerate(results):
        data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk

        # Handle both dictionary and object access for segments
        if isinstance(data, dict):
            segments = data.get("segments", [])
        else:
            segments = getattr(chunk, "segments", [])
            # Convert segments to list of dicts if needed
            if hasattr(segments, "model_dump"):
                segments = segments.model_dump()
            elif not isinstance(segments, list):
                segments = []

        # If not last chunk, find next chunk start time
        if i < len(results) - 1:
            next_start = results[i + 1][1]  # This is in milliseconds

            # Split segments into current and overlap based on next chunk's start time
            current_segments = []
            overlap_segments = []

            for segment in segments:
                # Handle both dict and object access for segment
                if isinstance(segment, dict):
                    segment_end = segment["end"]
                else:
                    segment_end = getattr(segment, "end", 0)

                # Convert segment end time to ms and compare with next chunk start time
                if segment_end * 1000 > next_start:
                    # Make sure segment is a dict
                    if not isinstance(segment, dict) and hasattr(segment, "model_dump"):
                        segment = segment.model_dump()
                    elif not isinstance(segment, dict):
                        # Create a dict from the segment object
                        segment = {
                            "text": getattr(segment, "text", ""),
                            "start": getattr(segment, "start", 0),
                            "end": segment_end,
                        }
                    overlap_segments.append(segment)
                else:
                    # Make sure segment is a dict
                    if not isinstance(segment, dict) and hasattr(segment, "model_dump"):
                        segment = segment.model_dump()
                    elif not isinstance(segment, dict):
                        # Create a dict from the segment object
                        segment = {
                            "text": getattr(segment, "text", ""),
                            "start": getattr(segment, "start", 0),
                            "end": segment_end,
                        }
                    current_segments.append(segment)

            # Merge overlap segments if any exist
            if overlap_segments:
                merged_overlap = overlap_segments[0].copy()
                merged_overlap.update(
                    {
                        "text": " ".join(
                            s.get("text", "")
                            if isinstance(s, dict)
                            else getattr(s, "text", "")
                            for s in overlap_segments
                        ),
                        "end": overlap_segments[-1].get("end", 0)
                        if isinstance(overlap_segments[-1], dict)
                        else getattr(overlap_segments[-1], "end", 0),
                    }
                )
                current_segments.append(merged_overlap)

            processed_chunks.append(current_segments)
        else:
            # For last chunk, ensure all segments are dicts
            dict_segments = []
            for segment in segments:
                if not isinstance(segment, dict) and hasattr(segment, "model_dump"):
                    dict_segments.append(segment.model_dump())
                elif not isinstance(segment, dict):
                    dict_segments.append(
                        {
                            "text": getattr(segment, "text", ""),
                            "start": getattr(segment, "start", 0),
                            "end": getattr(segment, "end", 0),
                        }
                    )
                else:
                    dict_segments.append(segment)
            processed_chunks.append(dict_segments)

    # Merge boundaries between chunks
    for i in range(len(processed_chunks) - 1):
        # Skip if either chunk has no segments
        if not processed_chunks[i] or not processed_chunks[i + 1]:
            continue

        # Add all segments except last from current chunk
        if len(processed_chunks[i]) > 1:
            final_segments.extend(processed_chunks[i][:-1])

        # Merge boundary segments
        last_segment = processed_chunks[i][-1]
        first_segment = processed_chunks[i + 1][0]

        merged_text = find_longest_common_sequence(
            [
                last_segment.get("text", "")
                if isinstance(last_segment, dict)
                else getattr(last_segment, "text", ""),
                first_segment.get("text", "")
                if isinstance(first_segment, dict)
                else getattr(first_segment, "text", ""),
            ]
        )

        merged_segment = (
            last_segment.copy()
            if isinstance(last_segment, dict)
            else {
                "text": getattr(last_segment, "text", ""),
                "start": getattr(last_segment, "start", 0),
                "end": getattr(last_segment, "end", 0),
            }
        )

        merged_segment.update(
            {
                "text": merged_text,
                "end": first_segment.get("end", 0)
                if isinstance(first_segment, dict)
                else getattr(first_segment, "end", 0),
            }
        )
        final_segments.append(merged_segment)

    # Add all segments from last chunk
    if processed_chunks and processed_chunks[-1]:
        final_segments.extend(processed_chunks[-1])

    # Create final transcription
    final_text = " ".join(
        segment.get("text", "")
        if isinstance(segment, dict)
        else getattr(segment, "text", "")
        for segment in final_segments
    )

    # Create result with both segments and words (if available)
    result = {"text": final_text, "segments": final_segments}

    # Include word-level timestamps if available
    if has_words:
        result["words"] = words

    return result


def format_timestamp(seconds: float) -> str:
    """
    Format seconds to MM:SS format.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def merge_short_segments(segments: list, min_length: int = 100) -> list:
    """
    Merge short segments into longer paragraphs.

    Args:
        segments: List of segments from transcription
        min_length: Minimum character length for merged segments

    Returns:
        List of merged segments
    """
    if not segments:
        return []

    merged = []
    current_segment = None

    for segment in segments:
        # Extract data from segment (handle both dict and object)
        start_time = (
            segment.get("start", 0)
            if isinstance(segment, dict)
            else getattr(segment, "start", 0)
        )
        text = (
            segment.get("text", "").strip()
            if isinstance(segment, dict)
            else getattr(segment, "text", "").strip()
        )

        if not text:
            continue

        if current_segment is None:
            # Start a new merged segment
            current_segment = {"start": start_time, "text": text}
        else:
            # Add to current segment with a space separator
            # Only add space if the previous text doesn't already end with whitespace
            if current_segment["text"] and not current_segment["text"][-1].isspace():
                current_segment["text"] += " " + text
            else:
                current_segment["text"] += text

            # Check if we should end this segment
            # End if: 1) reached min length AND ends with sentence punctuation
            #         2) OR accumulated text is very long (>300 chars)
            text_length = len(current_segment["text"])
            ends_with_punctuation = current_segment["text"][-1] in "。！？.!?"

            if (
                text_length >= min_length and ends_with_punctuation
            ) or text_length >= 300:
                merged.append(current_segment)
                current_segment = None

    # Add remaining segment
    if current_segment is not None:
        merged.append(current_segment)

    return merged


def generate_formatted_transcript(result: dict, audio_path: Path) -> str:
    """
    Generate a formatted transcript with timestamps similar to the PDF format.

    Args:
        result: Transcription result dictionary
        audio_path: Original audio file path

    Returns:
        Formatted transcript string
    """
    lines = []

    # Add title
    title = f"{audio_path.stem}_原文"
    lines.append(title)
    lines.append("")

    # Add timestamp
    now = dt.now().strftime("%Y年%m月%d日 %H:%M")
    lines.append(now)

    # Check if we have segments with timestamps
    if "segments" in result and result["segments"]:
        # Merge short segments into longer paragraphs
        merged_segments = merge_short_segments(result["segments"], min_length=100)

        for segment in merged_segments:
            # Format: 发言人 MM:SS
            timestamp = format_timestamp(segment["start"])
            lines.append(f"发言人 {timestamp}")
            lines.append(segment["text"])
            lines.append("")  # Empty line between segments
    else:
        # Fallback: if no segments, just add the full text with a single timestamp
        lines.append("发言人 00:00")
        lines.append(result.get("text", ""))
        lines.append("")

    return "\n".join(lines)


def generate_pdf(result: dict, audio_path: Path, output_path: str) -> bool:
    """
    Generate a PDF file from transcription results.

    Args:
        result: Transcription result dictionary
        audio_path: Original audio file path
        output_path: Path to save the PDF

    Returns:
        True if PDF was generated successfully, False otherwise
    """
    if not PDF_AVAILABLE:
        return False

    try:
        # Create PDF document
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        # Try to register Chinese font (fallback to default if not available)
        try:
            # Try common Chinese font paths on macOS
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Songti.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont("Chinese", font_path))
                    break
        except:
            pass

        # Create styles
        styles = getSampleStyleSheet()

        # Title style
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=12,
            fontName="Chinese" if PDF_AVAILABLE else "Helvetica-Bold",
        )

        # Timestamp style
        timestamp_style = ParagraphStyle(
            "Timestamp",
            parent=styles["Normal"],
            fontSize=10,
            alignment=TA_CENTER,
            spaceAfter=20,
            textColor="grey",
            fontName="Chinese" if PDF_AVAILABLE else "Helvetica",
        )

        # Speaker style (发言人 timestamp)
        speaker_style = ParagraphStyle(
            "Speaker",
            parent=styles["Normal"],
            fontSize=10,
            spaceAfter=6,
            fontName="Chinese" if PDF_AVAILABLE else "Helvetica-Bold",
        )

        # Content style
        content_style = ParagraphStyle(
            "Content",
            parent=styles["Normal"],
            fontSize=10,
            spaceAfter=12,
            fontName="Chinese" if PDF_AVAILABLE else "Helvetica",
        )

        # Build document content
        story = []

        # Add title
        title = f"{audio_path.stem}_原文"
        story.append(Paragraph(title, title_style))

        # Add timestamp
        now = dt.now().strftime("%Y年%m月%d日 %H:%M")
        story.append(Paragraph(now, timestamp_style))

        # Add segments (merge short segments first)
        if "segments" in result and result["segments"]:
            merged_segments = merge_short_segments(result["segments"], min_length=100)

            for segment in merged_segments:
                # Add speaker with timestamp
                timestamp = format_timestamp(segment["start"])
                story.append(Paragraph(f"发言人 {timestamp}", speaker_style))

                # Add content
                story.append(Paragraph(segment["text"], content_style))
        else:
            # Fallback
            story.append(Paragraph("发言人 00:00", speaker_style))
            story.append(Paragraph(result.get("text", ""), content_style))

        # Build PDF
        doc.build(story)
        return True

    except Exception as e:
        print(f"Warning: Failed to generate PDF: {str(e)}")
        return False


def save_results(result: dict, audio_path: Path) -> Path:
    """
    Save transcription results to files.

    Args:
        result: Transcription result dictionary
        audio_path: Original audio file path

    Returns:
        base_path: Base path where files were saved

    Raises:
        IOError: If saving results fails
    """
    try:
        # Create output directory structure: transcriptions/{audio_name}/
        base_name = Path(audio_path).stem
        output_dir = Path("transcriptions") / base_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save raw text (full transcript without timestamps)
        raw_txt_path = output_dir / f"{base_name}-raw.txt"
        with open(raw_txt_path, "w", encoding="utf-8") as f:
            f.write(result["text"])

        # Save formatted transcript (with timestamps, PDF-like format)
        formatted_txt = generate_formatted_transcript(result, audio_path)
        formatted_txt_path = output_dir / f"{base_name}.md"
        with open(formatted_txt_path, "w", encoding="utf-8") as f:
            f.write(formatted_txt)

        # Save full JSON (all data including segments and words)
        full_json_path = output_dir / f"{base_name}_full.json"
        with open(full_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"\nResults saved to: {output_dir}/")
        print(f"- {raw_txt_path.name} (raw transcript)")
        print(f"- {formatted_txt_path.name} (formatted with timestamps)")
        print(f"- {full_json_path.name} (complete JSON data)")

        # Generate PDF if reportlab is available
        pdf_path = output_dir / f"{base_name}.pdf"
        if generate_pdf(result, audio_path, str(pdf_path)):
            print(f"- {pdf_path.name} (PDF format)")
        else:
            if not PDF_AVAILABLE:
                print("\nNote: PDF generation skipped (reportlab not installed)")
                print("Install with: pip install reportlab")

        return output_dir

    except IOError as e:
        print(f"Error saving results: {str(e)}")
        raise


def transcribe_audio_in_chunks(
    audio_path: Path,
    chunk_length: int = 600,
    overlap: int = 10,
    preprocess: bool = False,
) -> dict:
    """
    Transcribe audio in chunks with overlap with Whisper via Groq API.

    Args:
        audio_path: Path to audio file
        chunk_length: Length of each chunk in seconds
        overlap: Overlap between chunks in seconds
        preprocess: Whether to preprocess audio to 16kHz mono FLAC (default: False)

    Returns:
        dict: Containing transcription results

    Raises:
        ValueError: If Groq API key is not set
        RuntimeError: If audio file fails to load
    """
    # api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set")

    print(f"\nStarting transcription of: {audio_path}")
    # Make sure your Groq API key is configured. If you don't have one, you can get one at https://console.groq.com/keys!
    client = Groq(api_key=api_key, max_retries=0)

    processed_path = None
    try:
        # Conditionally preprocess audio based on flag
        if preprocess:
            print("Preprocessing enabled: converting to 16kHz mono FLAC...")
            processed_path = preprocess_audio(audio_path)
            audio_file_path = processed_path
            audio_format = "flac"
        else:
            print("Using original audio file without preprocessing...")
            audio_file_path = audio_path
            # Try to detect format from file extension
            audio_format = audio_path.suffix.lstrip(".")

        try:
            audio = AudioSegment.from_file(audio_file_path, format=audio_format)
        except Exception as e:
            raise RuntimeError(f"Failed to load audio: {str(e)}")

        duration = len(audio)
        print(f"Audio duration: {duration / 1000:.2f}s")

        # Calculate # of chunks
        chunk_ms = chunk_length * 1000
        overlap_ms = overlap * 1000
        total_chunks = (duration // (chunk_ms - overlap_ms)) + 1
        print(f"Processing {total_chunks} chunks...")

        results = []
        total_transcription_time = 0
        total_export_time = 0

        # Loop through each chunk, extract current chunk from audio, transcribe
        for i in range(total_chunks):
            start = i * (chunk_ms - overlap_ms)
            end = min(start + chunk_ms, duration)

            print(f"\nProcessing chunk {i + 1}/{total_chunks}")
            print(f"Time range: {start / 1000:.1f}s - {end / 1000:.1f}s")

            chunk = audio[start:end]
            result, chunk_api_time, chunk_export_time = transcribe_single_chunk(
                client, chunk, i + 1, total_chunks
            )
            total_transcription_time += chunk_api_time
            total_export_time += chunk_export_time
            results.append((result, start))

        final_result = merge_transcripts(results)
        save_results(final_result, audio_path)

        print(f"\n--- Timing Summary ---")
        print(f"Total export time: {total_export_time:.2f}s")
        print(f"Total Groq API time: {total_transcription_time:.2f}s")
        print(
            f"Total processing time: {total_export_time + total_transcription_time:.2f}s"
        )

        return final_result

    # Clean up temp files regardless of successful creation (only if preprocessing was used)
    finally:
        if preprocess and processed_path:
            Path(processed_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Transcribe audio files using Groq's Whisper API with chunking support"
    )
    parser.add_argument(
        "audio_file", type=str, help="Path to the audio file to transcribe"
    )
    parser.add_argument(
        "--preprocess",
        "-p",
        action="store_true",
        help="Preprocess audio to 16kHz mono FLAC before transcription (default: False)",
    )
    parser.add_argument(
        "--chunk-length",
        type=int,
        default=1800,
        help="Length of each chunk in seconds (default: 1800)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=10,
        help="Overlap between chunks in seconds (default: 10)",
    )

    args = parser.parse_args()
    audio_path = Path(args.audio_file)

    if not audio_path.exists():
        print(f"Error: File not found: {audio_path}")
        parser.print_help()
        exit(1)

    transcribe_audio_in_chunks(
        audio_path,
        chunk_length=args.chunk_length,
        overlap=args.overlap,
        preprocess=args.preprocess,
    )
