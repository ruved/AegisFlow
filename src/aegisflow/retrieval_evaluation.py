"""Section-level retrieval metrics and a compact dense/lexical/fused report."""

import argparse
import asyncio
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aegisflow.evaluation import (
    GoldenCase,
    load_golden_dataset,
    normalize_source_path,
)
from aegisflow.rag.document_parser import parse_document
from aegisflow.rag.retrieval import (
    DEFAULT_STORE_PATH,
    reciprocal_rank_fusion,
    retrieve_ranked_lists,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_PATH = PROJECT_ROOT / "data" / "corpus"
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "eval" / "golden_v0.jsonl"
_HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
RetrieverName = str
GoldSection = tuple[str, str]


@dataclass(frozen=True)
class SectionSpan:
    """Source character range belonging to one Markdown heading."""

    heading: str
    start: int
    end: int


@dataclass(frozen=True)
class SectionMetrics:
    """Section-level outcome for one retrieval method and question."""

    gold_section_count: int
    hit_section_count: int
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None


@dataclass(frozen=True)
class RetrievalCaseResult:
    """Metrics for one golden case across all retrieval methods."""

    case: GoldenCase
    metrics: dict[RetrieverName, SectionMetrics]


def markdown_section_spans(text: str) -> list[SectionSpan]:
    """Return heading spans using each next heading as the section boundary."""
    headings: list[tuple[str, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        match = _HEADING_PATTERN.match(line.rstrip("\r\n"))
        if match is not None:
            heading = match.group(2).rstrip("#").strip()
            headings.append((heading, offset))
        offset += len(line)

    return [
        SectionSpan(
            heading=heading,
            start=start,
            end=headings[index + 1][1] if index + 1 < len(headings) else len(text),
        )
        for index, (heading, start) in enumerate(headings)
    ]


def section_hits_for_chunks(
    gold_sections: set[GoldSection],
    ranked_chunks: list[dict[str, Any]],
    corpus_dir: str | Path,
) -> list[set[GoldSection]]:
    """Map each chunk to gold heading spans it overlaps in its source document."""
    corpus_root = Path(corpus_dir).resolve()
    target_headings: dict[str, set[str]] = defaultdict(set)
    for doc, section in gold_sections:
        target_headings[doc].add(section)

    source_texts: dict[str, str] = {}
    source_spans: dict[str, list[SectionSpan]] = {}
    mapped_chunks: list[set[GoldSection]] = []

    for chunk in ranked_chunks:
        source = chunk.get("source")
        chunk_text = chunk.get("text")
        if not isinstance(source, str) or not isinstance(chunk_text, str):
            mapped_chunks.append(set())
            continue
        source = normalize_source_path(source)
        if source not in target_headings:
            mapped_chunks.append(set())
            continue

        if source not in source_texts:
            source_path = (corpus_root / source).resolve()
            if not source_path.is_relative_to(corpus_root):
                raise ValueError(f"Gold source escapes corpus directory: {source}")
            raw_text = source_path.read_text(encoding="utf-8")
            source_texts[source] = parse_document(raw_text, source_path.suffix)
            source_spans[source] = [
                span
                for span in markdown_section_spans(source_texts[source])
                if span.heading in target_headings[source]
            ]

        source_text = source_texts[source]
        spans = source_spans[source]
        matching_sections: set[GoldSection] = set()
        start = source_text.find(chunk_text)
        while start >= 0:
            end = start + len(chunk_text)
            matching_sections.update(
                (source, span.heading)
                for span in spans
                if start < span.end and end > span.start
            )
            start = source_text.find(chunk_text, start + 1)
        mapped_chunks.append(matching_sections)

    return mapped_chunks


def score_section_ranking(
    gold_sections: set[GoldSection],
    ranked_chunk_sections: list[set[GoldSection]],
    k: int,
) -> SectionMetrics:
    """Compute section Recall@k, first-hit MRR, and binary chunk nDCG@k."""
    if k <= 0:
        raise ValueError("k must be positive")
    if not gold_sections:
        return SectionMetrics(0, 0, None, None, None)

    covered: set[GoldSection] = set()
    first_relevant_rank: int | None = None
    dcg = 0.0
    for rank, chunk_sections in enumerate(ranked_chunk_sections[:k], start=1):
        newly_covered = (chunk_sections & gold_sections) - covered
        if newly_covered:
            if first_relevant_rank is None:
                first_relevant_rank = rank
            # One retrieved chunk occupies one rank, even if it spans headings.
            dcg += 1.0 / math.log2(rank + 1)
            covered.update(newly_covered)

    ideal_hits = min(k, len(gold_sections))
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return SectionMetrics(
        gold_section_count=len(gold_sections),
        hit_section_count=len(covered),
        recall_at_k=len(covered) / len(gold_sections),
        mrr=(1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0),
        ndcg_at_k=dcg / ideal_dcg,
    )


def evaluate_retrieval_cases(
    cases: list[GoldenCase],
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
    corpus_dir: str | Path = DEFAULT_CORPUS_PATH,
) -> list[RetrievalCaseResult]:
    """Evaluate dense, lexical, and fused rankings without calling an LLM."""
    if k <= 0:
        raise ValueError("k must be positive")

    results: list[RetrievalCaseResult] = []
    for case in sorted(cases, key=lambda item: item.id):
        dense, lexical = asyncio.run(
            retrieve_ranked_lists(case.question, k=k, store_path=store_path)
        )
        fused = reciprocal_rank_fusion(dense, lexical, limit=k)
        rankings = {"dense": dense, "lexical": lexical, "fused": fused}
        gold_sections = set(case.gold_sections)
        metrics = {
            name: score_section_ranking(
                gold_sections,
                section_hits_for_chunks(gold_sections, chunks, corpus_dir),
                k,
            )
            for name, chunks in rankings.items()
        }
        results.append(RetrievalCaseResult(case=case, metrics=metrics))
    return results


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _format_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def print_retrieval_report(results: list[RetrievalCaseResult], k: int) -> None:
    """Print macro-average metrics and sample counts by dataset slice."""
    slices = sorted({result.case.slice for result in results})
    row_slices = ["all", *slices]
    print(
        f"{'Retriever':<10} {'Slice':<16} {'Questions':>9} {'Answerable':>10} "
        f"{'Gold sec.':>10} {f'Recall@{k}':>9} {'MRR':>7} {f'nDCG@{k}':>9}"
    )
    print("-" * 86)
    for retriever in ("dense", "lexical", "fused"):
        for slice_name in row_slices:
            selected = [
                result
                for result in results
                if slice_name == "all" or result.case.slice == slice_name
            ]
            metrics = [result.metrics[retriever] for result in selected]
            answerable = [metric for metric in metrics if metric.gold_section_count]
            gold_count = sum(metric.gold_section_count for metric in metrics)
            recall = _mean(
                [
                    metric.recall_at_k
                    for metric in answerable
                    if metric.recall_at_k is not None
                ]
            )
            mrr = _mean([metric.mrr for metric in answerable if metric.mrr is not None])
            ndcg = _mean(
                [
                    metric.ndcg_at_k
                    for metric in answerable
                    if metric.ndcg_at_k is not None
                ]
            )
            print(
                f"{retriever:<10} {slice_name:<16} {len(selected):>9} "
                f"{len(answerable):>10} {gold_count:>10} "
                f"{_format_metric(recall):>9} {_format_metric(mrr):>7} "
                f"{_format_metric(ndcg):>9}"
            )
    print(
        "Metrics are macro-averaged per answerable question; '-' means no section gold."
    )


def main() -> None:
    """Run the retrieval-only metrics CLI."""
    parser = argparse.ArgumentParser(
        description="Report section-level dense, lexical, and fused retrieval metrics."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if args.k <= 0:
        parser.error("--k must be a positive integer")

    try:
        cases = load_golden_dataset(args.dataset)
        results = evaluate_retrieval_cases(
            cases,
            k=args.k,
            store_path=args.store,
            corpus_dir=args.corpus,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print_retrieval_report(results, args.k)


if __name__ == "__main__":
    main()
