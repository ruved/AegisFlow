"""Run a bounded E0 dense versus E1 fused retrieval experiment."""

import argparse
import asyncio
import csv
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aegisflow.evaluation import GoldenCase, load_golden_dataset
from aegisflow.rag.retrieval import (
    DEFAULT_STORE_PATH,
    reciprocal_rank_fusion,
    retrieve_chunks,
    retrieve_lexical_chunks,
)
from aegisflow.retrieval_evaluation import (
    DEFAULT_CORPUS_PATH,
    DEFAULT_DATASET_PATH,
    SectionMetrics,
    score_section_ranking,
    section_hits_for_chunks,
)

DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2] / "results" / "E1_retrieval_comparison.csv"
)
DEFAULT_KS = (3, 5)
MODES = ("dense", "lexical", "fused")


@dataclass(frozen=True)
class CandidateResult:
    """Metrics and section hits for one question at one candidate limit."""

    k: int
    metrics: dict[str, SectionMetrics]
    hits: dict[str, tuple[tuple[str, str], ...]]
    fused_vs_dense: str


@dataclass(frozen=True)
class ExperimentQuestion:
    """Per-question rankings, outcomes, and measured retrieval timings."""

    case: GoldenCase
    candidates: tuple[CandidateResult, ...]
    dense_ms: float
    lexical_ms: float
    hybrid_ms: float


def _timed_retriever(
    retriever: Any,
    query: str,
    k: int,
    store_path: str | Path,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    results = retriever(query, k, store_path)
    return results, (time.perf_counter() - started) * 1000


async def _retrieve_timed(
    query: str, k: int, store_path: str | Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float, float, float]:
    """Run both blocking retrievers concurrently and measure their wall times."""
    started = time.perf_counter()
    (dense, dense_ms), (lexical, lexical_ms) = await asyncio.gather(
        asyncio.to_thread(_timed_retriever, retrieve_chunks, query, k, store_path),
        asyncio.to_thread(
            _timed_retriever, retrieve_lexical_chunks, query, k, store_path
        ),
    )
    hybrid_ms = (time.perf_counter() - started) * 1000
    return dense, lexical, dense_ms, lexical_ms, hybrid_ms


def _hit_sections(
    gold_sections: set[tuple[str, str]],
    ranked_chunks: list[dict[str, Any]],
    corpus_dir: str | Path,
    k: int,
) -> tuple[tuple[str, str], ...]:
    mapped = section_hits_for_chunks(gold_sections, ranked_chunks[:k], corpus_dir)
    hits = set().union(*mapped) & gold_sections if mapped else set()
    return tuple(sorted(hits))


def evaluate_experiment(
    cases: list[GoldenCase],
    ks: tuple[int, ...] = DEFAULT_KS,
    store_path: str | Path = DEFAULT_STORE_PATH,
    corpus_dir: str | Path = DEFAULT_CORPUS_PATH,
) -> list[ExperimentQuestion]:
    """Measure dense and hybrid rankings at a small set of candidate limits."""
    if not ks or len(ks) > 3 or any(k <= 0 for k in ks):
        raise ValueError("ks must contain one to three positive integers")
    if len(set(ks)) != len(ks):
        raise ValueError("ks must not contain duplicates")

    max_k = max(ks)
    evaluated: list[ExperimentQuestion] = []
    for case in sorted(cases, key=lambda item: item.id):
        dense, lexical, dense_ms, lexical_ms, hybrid_ms = asyncio.run(
            _retrieve_timed(case.question, max_k, store_path)
        )
        gold_sections = set(case.gold_sections)
        candidate_results: list[CandidateResult] = []
        for k in sorted(ks):
            dense_top_k = dense[:k]
            lexical_top_k = lexical[:k]
            fused_top_k = reciprocal_rank_fusion(dense_top_k, lexical_top_k, limit=k)
            rankings = {
                "dense": dense_top_k,
                "lexical": lexical_top_k,
                "fused": fused_top_k,
            }
            metrics = {
                mode: score_section_ranking(
                    gold_sections,
                    section_hits_for_chunks(gold_sections, chunks, corpus_dir),
                    k,
                )
                for mode, chunks in rankings.items()
            }
            hits = {
                mode: _hit_sections(gold_sections, chunks, corpus_dir, k)
                for mode, chunks in rankings.items()
            }
            if not gold_sections:
                outcome = "excluded"
            elif (
                metrics["fused"].hit_section_count > metrics["dense"].hit_section_count
            ):
                outcome = "win"
            elif (
                metrics["fused"].hit_section_count < metrics["dense"].hit_section_count
            ):
                outcome = "loss"
            else:
                outcome = "tie"
            candidate_results.append(
                CandidateResult(k=k, metrics=metrics, hits=hits, fused_vs_dense=outcome)
            )
        evaluated.append(
            ExperimentQuestion(
                case=case,
                candidates=tuple(candidate_results),
                dense_ms=dense_ms,
                lexical_ms=lexical_ms,
                hybrid_ms=hybrid_ms,
            )
        )
    return evaluated


def _mean_metric(
    results: list[ExperimentQuestion], k: int, mode: str, metric_name: str
) -> float | None:
    values = [
        getattr(candidate.metrics[mode], metric_name)
        for result in results
        if result.case.gold_sections
        for candidate in result.candidates
        if candidate.k == k
        and getattr(candidate.metrics[mode], metric_name) is not None
    ]
    return statistics.mean(values) if values else None


def _format_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def print_experiment_summary(
    results: list[ExperimentQuestion], ks: tuple[int, ...], output_path: Path
) -> None:
    """Print metric rows, per-question outcome counts, and latency evidence."""
    print(
        f"{'k':>3} {'Retriever':<9} {'Questions':>9} {'Answerable':>10} "
        f"{'Gold sec.':>10} {'Recall':>8} {'MRR':>7} {'nDCG':>8}"
    )
    print("-" * 72)
    for k in sorted(ks):
        answerable = sum(bool(result.case.gold_sections) for result in results)
        gold_sections = sum(len(result.case.gold_sections) for result in results)
        for mode in MODES:
            print(
                f"{k:>3} {mode:<9} {len(results):>9} {answerable:>10} "
                f"{gold_sections:>10} "
                f"{_format_metric(_mean_metric(results, k, mode, 'recall_at_k')):>8} "
                f"{_format_metric(_mean_metric(results, k, mode, 'mrr')):>7} "
                f"{_format_metric(_mean_metric(results, k, mode, 'ndcg_at_k')):>8}"
            )

        outcomes = {name: 0 for name in ("win", "loss", "tie", "excluded")}
        for result in results:
            candidate = next(item for item in result.candidates if item.k == k)
            outcomes[candidate.fused_vs_dense] += 1
        print(
            f"k={k} fused vs dense by section Recall: "
            f"{outcomes['win']} wins, {outcomes['loss']} losses, "
            f"{outcomes['tie']} ties, {outcomes['excluded']} excluded"
        )
        wins = [
            result.case.id
            for result in results
            if next(item for item in result.candidates if item.k == k).fused_vs_dense
            == "win"
        ]
        losses = [
            result.case.id
            for result in results
            if next(item for item in result.candidates if item.k == k).fused_vs_dense
            == "loss"
        ]
        print(f"k={k} per-question wins: {', '.join(wins) or '-'}")
        print(f"k={k} per-question losses: {', '.join(losses) or '-'}")

    if results:
        dense_times = [result.dense_ms for result in results]
        hybrid_times = [result.hybrid_ms for result in results]
        print(
            f"Concurrent latency at candidate k={max(ks)}: "
            f"dense median {statistics.median(dense_times):.1f} ms; "
            f"dense+lexical median {statistics.median(hybrid_times):.1f} ms"
        )
    print(f"Per-question CSV: {output_path}")


def write_experiment_csv(results: list[ExperimentQuestion], path: str | Path) -> None:
    """Write section hits and dense-versus-fused outcomes for each question/k."""
    fields = [
        "question_id",
        "slice",
        "question",
        "k",
        "gold_sections",
        "dense_hit_sections",
        "lexical_hit_sections",
        "fused_hit_sections",
        "dense_recall_at_k",
        "dense_mrr",
        "dense_ndcg_at_k",
        "lexical_recall_at_k",
        "lexical_mrr",
        "lexical_ndcg_at_k",
        "fused_recall_at_k",
        "fused_mrr",
        "fused_ndcg_at_k",
        "fused_vs_dense",
        "dense_ms_at_max_k",
        "lexical_ms_at_max_k",
        "hybrid_ms_at_max_k",
    ]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        for result in results:
            for candidate in result.candidates:
                row: dict[str, object] = {
                    "question_id": result.case.id,
                    "slice": result.case.slice,
                    "question": result.case.question,
                    "k": candidate.k,
                    "gold_sections": _json_sections(result.case.gold_sections),
                    "dense_hit_sections": _json_sections(candidate.hits["dense"]),
                    "lexical_hit_sections": _json_sections(candidate.hits["lexical"]),
                    "fused_hit_sections": _json_sections(candidate.hits["fused"]),
                    "fused_vs_dense": candidate.fused_vs_dense,
                    "dense_ms_at_max_k": f"{result.dense_ms:.3f}",
                    "lexical_ms_at_max_k": f"{result.lexical_ms:.3f}",
                    "hybrid_ms_at_max_k": f"{result.hybrid_ms:.3f}",
                }
                for mode in MODES:
                    metric = candidate.metrics[mode]
                    row[f"{mode}_recall_at_k"] = _csv_metric(metric.recall_at_k)
                    row[f"{mode}_mrr"] = _csv_metric(metric.mrr)
                    row[f"{mode}_ndcg_at_k"] = _csv_metric(metric.ndcg_at_k)
                writer.writerow(row)


def _json_sections(sections: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(
        [{"doc": doc, "section": section} for doc, section in sections],
        ensure_ascii=False,
    )


def _csv_metric(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare dense E0 with fused E1 at a few retrieval limits."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ks", type=int, nargs="+", default=list(DEFAULT_KS))
    args = parser.parse_args()
    if not args.ks or len(args.ks) > 3 or any(k <= 0 for k in args.ks):
        parser.error("--ks needs one to three positive candidate limits")
    try:
        cases = load_golden_dataset(args.dataset)
        results = evaluate_experiment(
            cases,
            ks=tuple(args.ks),
            store_path=args.store,
            corpus_dir=args.corpus,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    write_experiment_csv(results, args.output)
    print_experiment_summary(results, tuple(args.ks), args.output)


if __name__ == "__main__":
    main()
