"""Extractive sentence-level context pruning and compression (E6).

Provides:
- Sentence segmentation with neighbor-window preservation.
- Exact technical identifier preservation (UUIDs, error codes, endpoints, IPs).
- Content-type guardrails (skips code blocks, log files, and small chunks).
- Cosine similarity scoring using local embedding cache.
- Threshold sweep evaluation helper to measure net latency vs citation recall.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from aegisflow.rag.embeddings import embed_texts

logger = logging.getLogger("aegisflow.sentence_pruner")

# Feature flag for ablation studies
ENABLE_SENTENCE_PRUNING: bool = False  # Evaluated via threshold sweep

# Regex patterns for sentence splitting and exact technical identifiers
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_IDENTIFIER_PATTERN = re.compile(
    r"\b("
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|ERR-[A-Z0-9_\-]+"  # Error codes
    r"|PM-\d{3}|RB-\d{3}"  # Document identifiers
    r"|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"  # IPv4
    r"|[A-Za-z0-9_\-]+-service"  # Service names
    r"|v\d+\.\d+\.\d+"  # Semantic versions
    r")\b",
    re.IGNORECASE,
)


@dataclass
class PruningResult:
    """Result of sentence pruning on a single text chunk."""

    original_text: str
    pruned_text: str
    original_tokens: int
    pruned_tokens: int
    compression_ratio: float  # pruned_tokens / original_tokens
    skipped_reason: str | None = None  # e.g., 'too_short', 'code_or_log', 'disabled'


def count_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def is_unsuitable_for_pruning(text: str, source: str = "") -> bool:
    """Check if content is code, structured table, or log file."""
    if source.endswith(".log.md") or source.startswith("logs/"):
        return True
    if "```" in text:
        return True
    if text.count("|") > 6 and "-|-" in text:
        return True
    return False


def split_into_sentences(text: str) -> list[str]:
    """Segment text into individual sentences, trimming empty whitespace."""
    raw = _SENTENCE_SPLIT_PATTERN.split(text.strip())
    return [s.strip() for s in raw if s.strip()]


def contains_exact_identifiers(sentence: str, query: str) -> bool:
    """Check if sentence contains key technical identifiers present in the query."""
    query_identifiers = set(_IDENTIFIER_PATTERN.findall(query))
    if not query_identifiers:
        # If no identifiers in query, check if sentence has high-value identifiers
        return bool(_IDENTIFIER_PATTERN.search(sentence))

    sentence_identifiers = set(_IDENTIFIER_PATTERN.findall(sentence))
    return bool(query_identifiers.intersection(sentence_identifiers))


def prune_chunk(
    text: str,
    query: str,
    source: str = "",
    threshold: float = 0.65,
    window_size: int = 1,
    min_tokens: int = 120,
) -> PruningResult:
    """Selectively compress text by pruning low-relevance sentences.

    Retains:
    - Sentences with embedding cosine similarity >= threshold.
    - Neighboring sentences within window_size.
    - Sentences containing matched technical identifiers.
    """
    orig_toks = count_tokens(text)

    # 1. Guardrails
    if orig_toks < min_tokens:
        return PruningResult(
            original_text=text,
            pruned_text=text,
            original_tokens=orig_toks,
            pruned_tokens=orig_toks,
            compression_ratio=1.0,
            skipped_reason="too_short",
        )

    if is_unsuitable_for_pruning(text, source):
        return PruningResult(
            original_text=text,
            pruned_text=text,
            original_tokens=orig_toks,
            pruned_tokens=orig_toks,
            compression_ratio=1.0,
            skipped_reason="code_or_log",
        )

    sentences = split_into_sentences(text)
    if len(sentences) <= 2:
        return PruningResult(
            original_text=text,
            pruned_text=text,
            original_tokens=orig_toks,
            pruned_tokens=orig_toks,
            compression_ratio=1.0,
            skipped_reason="too_few_sentences",
        )

    # 2. Embed query and candidate sentences
    all_texts = [query] + sentences
    try:
        vectors = embed_texts(all_texts)
    except Exception as exc:
        logger.warning("Embedding failed during pruning: %s; returning raw text", exc)
        return PruningResult(
            original_text=text,
            pruned_text=text,
            original_tokens=orig_toks,
            pruned_tokens=orig_toks,
            compression_ratio=1.0,
            skipped_reason="embedding_error",
        )

    q_vec = vectors[0]
    s_vecs = vectors[1:]

    # 3. Identify sentences to retain
    retained_indices: set[int] = set()

    for idx, (sent, s_vec) in enumerate(zip(sentences, s_vecs, strict=True)):
        sim = cosine_similarity(q_vec, s_vec)
        has_id = contains_exact_identifiers(sent, query)

        if sim >= threshold or has_id:
            # Add sentence and its neighbor window
            start_win = max(0, idx - window_size)
            end_win = min(len(sentences), idx + window_size + 1)
            for w in range(start_win, end_win):
                retained_indices.add(w)

    if not retained_indices:
        # Fallback: keep top 1 most similar sentence to avoid empty text
        sims = [cosine_similarity(q_vec, sv) for sv in s_vecs]
        best_idx = int(sims.index(max(sims)))
        retained_indices.add(best_idx)

    # 4. Reconstruct pruned text in original order
    selected_sentences = [sentences[i] for i in sorted(retained_indices)]
    pruned_text = " ".join(selected_sentences)
    pruned_toks = count_tokens(pruned_text)
    ratio = pruned_toks / orig_toks if orig_toks > 0 else 1.0

    return PruningResult(
        original_text=text,
        pruned_text=pruned_text,
        original_tokens=orig_toks,
        pruned_tokens=pruned_toks,
        compression_ratio=round(ratio, 3),
        skipped_reason=None,
    )


def prune_chunks(
    chunks: list[dict[str, Any]],
    query: str,
    threshold: float = 0.65,
    window_size: int = 1,
) -> list[dict[str, Any]]:
    """Prune candidate chunks in-place or returning updated dictionaries."""
    if not ENABLE_SENTENCE_PRUNING:
        return chunks

    results = []
    for chunk in chunks:
        raw_text = str(chunk.get("text", ""))
        source = str(chunk.get("source", ""))
        res = prune_chunk(
            raw_text,
            query,
            source=source,
            threshold=threshold,
            window_size=window_size,
        )
        results.append(
            {**chunk, "text": res.pruned_text, "_pruned": res.skipped_reason is None}
        )
    return results
