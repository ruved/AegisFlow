"""Token-efficient evidence selection and context budgeting (E5).

Provides:
- Deduplication across sub-questions (by chunk ID and content hash).
- Per-sub-question and global evidence token budgets.
- Section-level diversity (avoids near-duplicate excerpts from the same heading).
- Structured audit logging of selected vs excluded evidence chunks.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aegisflow.context_builder")

# Feature flag for ablation studies
ENABLE_CONTEXT_BUILDER: bool = True


def count_tokens(text: str) -> int:
    """Fast approximation of token length (characters / 4)."""
    return max(1, (len(text) + 3) // 4)


def content_hash(text: str) -> str:
    """Hash normalized text to detect exact duplicates."""
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class ExcludedEvidence:
    """Record of an evidence chunk excluded by context budgeting."""

    chunk_id: str
    source: str
    heading: str
    # 'duplicate', 'subquestion_budget_exceeded', 'global_budget_exceeded',
    # or 'redundant_section'
    reason: str
    tokens: int


@dataclass
class ContextBuilderResult:
    """Result of context building with selected chunks and exclusion log."""

    selected_chunks: list[dict[str, Any]]
    excluded_chunks: list[ExcludedEvidence] = field(default_factory=list)
    total_selected_tokens: int = 0
    total_excluded_tokens: int = 0


class ContextBuilder:
    """Builds token-budgeted, diversified evidence sets for prompt generation."""

    def __init__(
        self,
        max_subquestion_tokens: int = 500,
        max_total_tokens: int = 1500,
        max_chunks_per_section: int = 1,
    ) -> None:
        self.max_subquestion_tokens = max_subquestion_tokens
        self.max_total_tokens = max_total_tokens
        self.max_chunks_per_section = max_chunks_per_section

    def build_context(
        self,
        subquestion_results: list[tuple[str, list[dict[str, Any]]]],
    ) -> ContextBuilderResult:
        """Select and budget chunks across subquestions.

        Args:
            subquestion_results: List of (subquestion_text, candidate_chunks).

        Returns:
            ContextBuilderResult containing selected chunks and audit exclusions.
        """
        if not ENABLE_CONTEXT_BUILDER:
            # Bypass mode: simple flattening without budgets
            all_chunks: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for _, chunks in subquestion_results:
                for c in chunks:
                    cid = str(c.get("chunk_id", ""))
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        all_chunks.append(dict(c))
            tokens = sum(count_tokens(c.get("text", "")) for c in all_chunks)
            return ContextBuilderResult(
                selected_chunks=all_chunks,
                excluded_chunks=[],
                total_selected_tokens=tokens,
                total_excluded_tokens=0,
            )

        selected: list[dict[str, Any]] = []
        excluded: list[ExcludedEvidence] = []
        seen_chunk_ids: set[str] = set()
        seen_hashes: set[str] = set()
        section_counts: dict[str, int] = {}
        total_tokens = 0

        for _subq_text, chunks in subquestion_results:
            subq_tokens = 0
            for chunk in chunks:
                cid = str(chunk.get("chunk_id", chunk.get("evidence_id", "")))
                text = str(chunk.get("text", ""))
                tokens = count_tokens(text)
                source = str(chunk.get("source", ""))
                heading = str(chunk.get("heading", ""))
                sec_key = f"{source}:{heading}"
                h = content_hash(text)

                # 1. Deduplication check
                if cid in seen_chunk_ids or h in seen_hashes:
                    excluded.append(
                        ExcludedEvidence(
                            chunk_id=cid,
                            source=source,
                            heading=heading,
                            reason="duplicate",
                            tokens=tokens,
                        )
                    )
                    continue

                # 2. Section diversity check (avoid redundant excerpts)
                current_sec_count = section_counts.get(sec_key, 0)
                if current_sec_count >= self.max_chunks_per_section:
                    excluded.append(
                        ExcludedEvidence(
                            chunk_id=cid,
                            source=source,
                            heading=heading,
                            reason="redundant_section",
                            tokens=tokens,
                        )
                    )
                    continue

                # 3. Per-subquestion budget check
                if subq_tokens + tokens > self.max_subquestion_tokens:
                    excluded.append(
                        ExcludedEvidence(
                            chunk_id=cid,
                            source=source,
                            heading=heading,
                            reason="subquestion_budget_exceeded",
                            tokens=tokens,
                        )
                    )
                    continue

                # 4. Global budget check
                if total_tokens + tokens > self.max_total_tokens:
                    excluded.append(
                        ExcludedEvidence(
                            chunk_id=cid,
                            source=source,
                            heading=heading,
                            reason="global_budget_exceeded",
                            tokens=tokens,
                        )
                    )
                    continue

                # Accept chunk
                seen_chunk_ids.add(cid)
                seen_hashes.add(h)
                section_counts[sec_key] = current_sec_count + 1
                subq_tokens += tokens
                total_tokens += tokens
                selected.append(dict(chunk))

        excluded_tokens = sum(e.tokens for e in excluded)
        logger.info(
            "ContextBuilder: selected %d chunks (%d tokens), "
            "excluded %d chunks (%d tokens)",
            len(selected),
            total_tokens,
            len(excluded),
            excluded_tokens,
        )

        return ContextBuilderResult(
            selected_chunks=selected,
            excluded_chunks=excluded,
            total_selected_tokens=total_tokens,
            total_excluded_tokens=excluded_tokens,
        )


def build_evidence_context(
    subquestion_results: list[tuple[str, list[dict[str, Any]]]],
    max_subquestion_tokens: int = 500,
    max_total_tokens: int = 1500,
    max_chunks_per_section: int = 1,
) -> ContextBuilderResult:
    """Convenience helper to run ContextBuilder."""
    builder = ContextBuilder(
        max_subquestion_tokens=max_subquestion_tokens,
        max_total_tokens=max_total_tokens,
        max_chunks_per_section=max_chunks_per_section,
    )
    return builder.build_context(subquestion_results)
