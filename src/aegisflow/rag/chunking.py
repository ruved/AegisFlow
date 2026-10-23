"""Fixed-size text chunking for the baseline RAG pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    source: str
    text: str


def chunk_text(
    text: str,
    source: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[TextChunk]:
    """Split text into overlapping character-based chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    text = text.strip()
    if not text:
        return []

    chunks: list[TextChunk] = []
    step = chunk_size - overlap

    for index, start in enumerate(range(0, len(text), step)):
        content = text[start : start + chunk_size].strip()
        if content:
            chunks.append(
                TextChunk(
                    chunk_id=f"{source}::chunk-{index}",
                    source=source,
                    text=content,
                )
            )

    return chunks
