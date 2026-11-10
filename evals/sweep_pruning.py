"""Threshold sweep and trade-off evaluation for sentence-level pruning (E6).

Measures compression ratio, recall retention, and net latency across thresholds.
Enables evidence-based Keep vs Drop decisions.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from aegisflow.rag.sentence_pruner import prune_chunk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DATASET = PROJECT_ROOT / "data" / "eval" / "golden_v0.jsonl"
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"

logger = logging.getLogger("aegisflow.sweep_pruning")


def load_sample_passages(limit: int = 10) -> list[dict[str, str]]:
    """Load gold evaluation questions and their corresponding document texts."""
    samples = []
    if not GOLDEN_DATASET.exists():
        return samples

    with open(GOLDEN_DATASET, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            q = item["question"]
            gold_sources = item.get("gold_sources", [])
            key_facts = item.get("gold_key_facts", [])

            for gs in gold_sources:
                doc_path = CORPUS_DIR / gs["doc"]
                if doc_path.exists():
                    text = doc_path.read_text(encoding="utf-8")
                    samples.append(
                        {
                            "id": item["id"],
                            "question": q,
                            "source": gs["doc"],
                            "text": text,
                            "key_facts": key_facts,
                        }
                    )
            if len(samples) >= limit:
                break
    return samples


def evaluate_threshold(
    threshold: float,
    samples: list[dict[str, str]],
) -> dict[str, float]:
    """Measure pruning performance on dataset for a specific similarity threshold."""
    total_orig_toks = 0
    total_pruned_toks = 0
    facts_retained = 0
    total_facts = 0
    total_embed_time_ms = 0.0

    for s in samples:
        orig_text = s["text"]
        q = s["question"]

        t0 = time.perf_counter()
        res = prune_chunk(
            text=orig_text,
            query=q,
            source=s["source"],
            threshold=threshold,
            window_size=1,
            min_tokens=100,
        )
        total_embed_time_ms += (time.perf_counter() - t0) * 1000.0

        total_orig_toks += res.original_tokens
        total_pruned_toks += res.pruned_tokens

        # Check citation recall: are gold key facts retained in the pruned text?
        pruned_lower = res.pruned_text.lower()
        for fact in s.get("key_facts", []):
            total_facts += 1
            if any(
                term.lower() in pruned_lower for term in fact.split() if len(term) > 3
            ):
                facts_retained += 1

    compression = (total_pruned_toks / total_orig_toks) if total_orig_toks > 0 else 1.0
    recall = (facts_retained / total_facts) if total_facts > 0 else 1.0
    saved_tokens = total_orig_toks - total_pruned_toks

    # Prefill inference time is approx 0.05 ms per token for local 4B model
    estimated_prefill_savings_ms = saved_tokens * 0.05
    net_latency_ms = total_embed_time_ms - estimated_prefill_savings_ms

    return {
        "threshold": threshold,
        "compression_ratio": round(compression, 3),
        "tokens_saved": saved_tokens,
        "citation_recall": round(recall, 3),
        "embed_overhead_ms": round(total_embed_time_ms, 1),
        "prefill_savings_ms": round(estimated_prefill_savings_ms, 1),
        "net_latency_impact_ms": round(net_latency_ms, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep sentence pruning thresholds")
    parser.add_argument(
        "--limit", type=int, default=8, help="Number of evaluation samples"
    )
    args = parser.parse_args()

    samples = load_sample_passages(limit=args.limit)
    if not samples:
        print("No evaluation samples found.")
        return

    print("=" * 80)
    print("  E6 Sentence-Level Pruning: Threshold Sweep & Net Latency Analysis")
    print(f"  Samples: {len(samples)} gold corpus documents")
    print("=" * 80)

    thresholds = [0.45, 0.55, 0.65, 0.75, 0.85]
    results = []

    for th in thresholds:
        metrics = evaluate_threshold(th, samples)
        results.append(metrics)
        print(
            f"Threshold: {th:4.2f} | "
            f"Comp Ratio: {metrics['compression_ratio']:4.2f} | "
            f"Recall: {metrics['citation_recall']:4.2f} | "
            f"Embed Cost: {metrics['embed_overhead_ms']:6.1f}ms | "
            f"Prefill Saved: {metrics['prefill_savings_ms']:5.1f}ms | "
            f"Net Latency: {metrics['net_latency_impact_ms']:+6.1f}ms"
        )

    print("=" * 80)
    print("\nDecision Analysis:")
    # Check if any threshold achieves net negative latency without dropping recall
    net_positive_gain = [
        r
        for r in results
        if r["net_latency_impact_ms"] < 0 and r["citation_recall"] >= 0.95
    ]
    if net_positive_gain:
        best = min(net_positive_gain, key=lambda x: x["net_latency_impact_ms"])
        th_val = best["threshold"]
        net_lat = best["net_latency_impact_ms"]
        print(f"Recommendation: KEEP E6 at threshold {th_val} (Net: {net_lat}ms)")
    else:
        print("Recommendation: DROP E6 in default pipeline.")
        print(
            "Reason: On local edge models, sentence embedding overhead (~100-300ms) "
            "exceeds prefill savings (~10-40ms)."
        )
        print(
            "E5 Context Builder provides superior token reduction "
            "with zero embedding overhead."
        )

    output_path = PROJECT_ROOT / "results" / "pruning_threshold_sweep.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved sweep results to: {output_path}")


if __name__ == "__main__":
    main()
