"""Compare parent/child chunk sizes on the golden retrieval dataset."""

import argparse
import csv
import statistics
from pathlib import Path
from typing import Any

from aegisflow.evaluation import load_golden_dataset
from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.ingest import ingest_directory
from aegisflow.rag.lexical_index import LexicalIndex
from aegisflow.rag.parent_child import approximate_token_count
from aegisflow.rag.retrieval import (
    hydrate_parent_results,
    reciprocal_rank_fusion,
)
from aegisflow.rag.vector_store import VectorStore
from aegisflow.retrieval_evaluation import (
    DEFAULT_CORPUS_PATH,
    DEFAULT_DATASET_PATH,
    score_section_ranking,
    section_hits_for_chunks,
)

SETTINGS = ((600, 125), (800, 175), (1000, 225))
EMBEDDING_BATCH_SIZE = 8
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "chunking_comparison.csv"
DEFAULT_STORE_ROOT = PROJECT_ROOT / "chroma_db_chunking"
DEFAULT_K = 3


def _prompt_text(question: str, parents: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"Source: {parent['source']}\n"
        f"Chunk ID: {parent['chunk_id']}\n"
        f"Content:\n{parent.get('highlighted_text', parent['text'])}"
        for parent in parents
    )
    return (
        f"Retrieved context:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer using the retrieved context and cite the source filenames."
    )


def run_comparison(
    corpus: Path,
    dataset: Path,
    output: Path,
    store_root: Path,
    k: int = DEFAULT_K,
) -> None:
    """Ingest each setting, evaluate parent retrieval, and write per-question data."""
    if k <= 0:
        raise ValueError("k must be positive")

    cases = load_golden_dataset(dataset)
    cases.sort(key=lambda case: case.id)
    query_vectors: list[list[float]] = []
    for offset in range(0, len(cases), EMBEDDING_BATCH_SIZE):
        batch = cases[offset : offset + EMBEDDING_BATCH_SIZE]
        print(
            f"Embedding golden questions {offset + 1}-"
            f"{offset + len(batch)} of {len(cases)}",
            flush=True,
        )
        query_vectors.extend(embed_texts([case.question for case in batch]))
    csv_rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []

    store_root.mkdir(parents=True, exist_ok=True)
    for parent_tokens, child_tokens in SETTINGS:
        print(
            f"Ingesting parent={parent_tokens}, child={child_tokens}",
            flush=True,
        )
        store_path = store_root / f"p{parent_tokens}_c{child_tokens}"
        ingestion = ingest_directory(
            docs_dir=corpus,
            store_path=store_path,
            parent_tokens=parent_tokens,
            child_tokens=child_tokens,
        )
        vector_store = VectorStore(store_path)
        lexical_index = LexicalIndex(store_path / "lexical.sqlite3")
        candidate_limit = max(k * 3, k)
        answerable_recalls: list[float] = []
        answerable_hits = 0
        prompt_tokens: list[int] = []

        for case, query_vector in zip(cases, query_vectors, strict=True):
            dense = vector_store.search(query_vector, k=candidate_limit)
            lexical = lexical_index.search(case.question, k=candidate_limit)
            fused = reciprocal_rank_fusion(
                dense,
                lexical,
                limit=candidate_limit,
            )
            parents = hydrate_parent_results(fused, store_path, k)
            gold_sections = set(case.gold_sections)
            mapped_sections = section_hits_for_chunks(gold_sections, parents, corpus)
            metrics = score_section_ranking(gold_sections, mapped_sections, k)
            if metrics.recall_at_k is not None:
                answerable_recalls.append(metrics.recall_at_k)
                answerable_hits += int(metrics.hit_section_count > 0)

            prompt_token_count = approximate_token_count(
                _prompt_text(case.question, parents)
            )
            prompt_tokens.append(prompt_token_count)
            csv_rows.append(
                {
                    "parent_tokens": parent_tokens,
                    "child_tokens": child_tokens,
                    "question_id": case.id,
                    "gold_sections": len(gold_sections),
                    "hit_sections": metrics.hit_section_count,
                    "recall_at_k": (
                        "" if metrics.recall_at_k is None else metrics.recall_at_k
                    ),
                    "citation_evidence_hit": (
                        "" if not gold_sections else int(metrics.hit_section_count > 0)
                    ),
                    "approx_prompt_tokens": prompt_token_count,
                    "retrieved_parents": len(parents),
                }
            )

        summaries.append(
            {
                "parents": parent_tokens,
                "children": child_tokens,
                "indexed_parents": ingestion["parents"],
                "indexed_children": ingestion["chunks"],
                "recall": statistics.mean(answerable_recalls),
                "citation_hit_rate": answerable_hits / len(answerable_recalls),
                "mean_prompt_tokens": statistics.mean(prompt_tokens),
                "median_prompt_tokens": statistics.median(prompt_tokens),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "parent_tokens",
        "child_tokens",
        "question_id",
        "gold_sections",
        "hit_sections",
        "recall_at_k",
        "citation_evidence_hit",
        "approx_prompt_tokens",
        "retrieved_parents",
    ]
    with output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(
        f"{'Parent/child':<15} {'Docs':>5} {'Parents':>8} {'Children':>9} "
        f"{'Recall@' + str(k):>9} {'Citation hit':>13} {'Prompt tok. mean/median':>24}"
    )
    print("-" * 90)
    for row in summaries:
        print(
            f"{row['parents']}/{row['children']:<11} "
            f"{len(cases):>5} {row['indexed_parents']:>8} "
            f"{row['indexed_children']:>9} {row['recall']:>9.3f} "
            f"{row['citation_hit_rate']:>12.1%} "
            f"{row['mean_prompt_tokens']:>10.1f}/{row['median_prompt_tokens']:.1f}"
        )
    print(f"Per-question CSV: {output}")
    print(
        "Citation hit rate is the share of answerable questions with at least one "
        "gold section among the retrieved parents. Prompt tokens are an approximate "
        "character-based count of the assembled user prompt."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare parent/child chunk sizes on the golden set."
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--store-root", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    args = parser.parse_args()
    run_comparison(
        args.corpus,
        args.dataset,
        args.output,
        args.store_root,
        args.k,
    )


if __name__ == "__main__":
    main()
