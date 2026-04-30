"""Markdown paragraph chunker for RAG indexing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str  # Prefixed with "【title】\n" at the head
    run_id: str
    kind: str  # "summary" or "markdown"
    title: str
    bvid: str
    chunk_index: int
    doc_id: str  # "{run_id}__{kind}__{chunk_index}"


def chunk_markdown(
    content: str,
    *,
    run_id: str,
    kind: str,
    title: str,
    bvid: str,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> list[Chunk]:
    """Split markdown content into overlapping chunks.

    Strategy:
    1. Split on double-newline paragraphs
    2. Merge short paragraphs (< 50 chars) into previous
    3. Split paragraphs exceeding chunk_size on sentence boundaries
    4. Carry chunk_overlap chars from previous chunk as prefix
    5. Prefix each chunk with 【title】
    """
    paragraphs = _split_paragraphs(content, chunk_size=chunk_size)
    raw_chunks = _merge_into_chunks(
        paragraphs, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    chunks: list[Chunk] = []
    for i, text in enumerate(raw_chunks):
        prefixed = f"【{title}】\n{text}"
        chunks.append(
            Chunk(
                text=prefixed,
                run_id=run_id,
                kind=kind,
                title=title,
                bvid=bvid,
                chunk_index=i,
                doc_id=f"{run_id}__{kind}__{i}",
            )
        )
    return chunks


def _split_paragraphs(content: str, *, chunk_size: int) -> list[str]:
    """Split content into paragraphs, then further split long ones by sentence."""
    raw_paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    paragraphs: list[str] = []
    for para in raw_paragraphs:
        if len(para) <= chunk_size:
            paragraphs.append(para)
        else:
            # Split long paragraph on sentence boundaries
            sentences = _split_sentences(para)
            current = ""
            for sentence in sentences:
                if not current:
                    current = sentence
                elif len(current) + len(sentence) + 1 <= chunk_size:
                    current += sentence
                else:
                    if current:
                        paragraphs.append(current)
                    current = sentence
            if current:
                paragraphs.append(current)

    # Merge very short paragraphs into previous
    merged: list[str] = []
    for para in paragraphs:
        if merged and len(para) < 50:
            merged[-1] = merged[-1] + "\n\n" + para
        else:
            merged.append(para)

    return merged


def _split_sentences(text: str) -> list[str]:
    """Split text on Chinese/English sentence endings, preserving delimiters."""
    import re

    parts = re.split(r"(?<=[。！？.!?\n])", text)
    return [p for p in parts if p]


def _merge_into_chunks(
    paragraphs: list[str],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Merge paragraphs into chunks with overlap from previous chunk."""
    if not paragraphs:
        return []

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    overlap_prefix = ""

    for para in paragraphs:
        para_len = len(para)

        if current_len + para_len > chunk_size and current_parts:
            # Flush current chunk
            chunk_text = overlap_prefix + "\n\n".join(current_parts)
            chunks.append(chunk_text)

            # Compute overlap for next chunk
            combined = "\n\n".join(current_parts)
            if len(combined) > chunk_overlap:
                overlap_prefix = combined[-chunk_overlap:] + "\n\n"
            else:
                overlap_prefix = combined + "\n\n"

            current_parts = [para]
            current_len = para_len
        else:
            current_parts.append(para)
            current_len += para_len + 2  # +2 for "\n\n"

    if current_parts:
        chunk_text = overlap_prefix + "\n\n".join(current_parts)
        chunks.append(chunk_text)

    return chunks
