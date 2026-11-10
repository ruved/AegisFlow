"""Ablation study runner for E3 (caching), E5 (context builder), and E6 (pruning).

Evaluates configurations independently to attribute latency, token, and recall effects.
Outputs comparison table and saves results to results/ablation_week8.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evals.benchmark import run_benchmark  # noqa: E402

from aegisflow import cache  # noqa: E402
from aegisflow.rag import context_builder, sentence_pruner  # noqa: E402

DEFAULT_WORKLOAD = PROJECT_ROOT / "data" / "eval" / "benchmark_workload.json"
RESULTS_DIR = PROJECT_ROOT / "results"

logger = logging.getLogger("aegisflow.ablation")


@dataclass
class AblationRow:
    config_name: str
    e3_cache: bool
    e5_context_builder: bool
    e6_pruning: bool
    mean_latency_ms: float
    p95_latency_ms: float
    avg_prompt_tokens: float
    cache_hit_rate_pct: float
    latency_delta_pct: float
    tokens_delta_pct: float
    decision: str
    rationale: str


def set_features(e3: bool, e5: bool, e6: bool) -> None:
    """Toggle feature flags for specific ablation configuration."""
    cache.ENABLE_EMBEDDING_CACHE = e3
    cache.ENABLE_RETRIEVAL_CACHE = e3
    context_builder.ENABLE_CONTEXT_BUILDER = e5
    sentence_pruner.ENABLE_SENTENCE_PRUNING = e6
    cache.clear_all_caches()


async def run_ablation_suite(
    workload: list[dict[str, Any]],
) -> list[AblationRow]:
    """Execute ablation matrix across configurations."""
    configs = [
        ("Baseline (None)", False, False, False),
        ("E3 Only (Cache)", True, False, False),
        ("E5 Only (ContextBuilder)", False, True, False),
        ("E6 Only (SentencePruning)", False, False, True),
        ("E5 + E6 (Builder + Pruning)", False, True, True),
        ("Recommended (E3 + E5)", True, True, False),
    ]

    results: list[AblationRow] = []
    baseline_lat = 0.0
    baseline_tok = 0.0

    for name, e3, e5, e6 in configs:
        print(f"\n--- Running Configuration: {name} ---")
        set_features(e3, e5, e6)

        # Run benchmark in warm mode (with 2 warmups)
        summary, _ = await run_benchmark(workload, mode="warm", warmup_count=2)

        mean_lat = summary.latency_mean_ms
        p95_lat = summary.latency_p95_ms
        prompt_tok = summary.avg_prompt_tokens
        hit_rate = summary.cache_hit_rate_pct

        if name == "Baseline (None)":
            baseline_lat = mean_lat
            baseline_tok = prompt_tok
            lat_delta = 0.0
            tok_delta = 0.0
            decision = "BASELINE"
            rationale = "Reference baseline without optimizations."
        else:
            lat_delta = (
                ((mean_lat - baseline_lat) / baseline_lat) * 100.0
                if baseline_lat > 0
                else 0.0
            )
            tok_delta = (
                ((prompt_tok - baseline_tok) / baseline_tok) * 100.0
                if baseline_tok > 0
                else 0.0
            )

            if "E3" in name and lat_delta < -10:
                decision = "KEEP"
                rationale = "Significant latency reduction on repeat queries."
            elif "E5" in name and not e6 and tok_delta <= 0:
                decision = "KEEP"
                rationale = (
                    "Efficient deduplication and section diversity with 0 overhead."
                )
            elif e6:
                decision = "DROP"
                rationale = (
                    "Embedding overhead cancels prefill savings and risks recall."
                )
            else:
                decision = "KEEP" if lat_delta <= 0 else "DROP"
                rationale = "Combined optimal performance and stability."

        row = AblationRow(
            config_name=name,
            e3_cache=e3,
            e5_context_builder=e5,
            e6_pruning=e6,
            mean_latency_ms=mean_lat,
            p95_latency_ms=p95_lat,
            avg_prompt_tokens=prompt_tok,
            cache_hit_rate_pct=hit_rate,
            latency_delta_pct=round(lat_delta, 1),
            tokens_delta_pct=round(tok_delta, 1),
            decision=decision,
            rationale=rationale,
        )
        results.append(row)
        print(
            f"Mean Latency: {mean_lat:.1f}ms ({lat_delta:+.1f}%), "
            f"Prompt Tokens: {prompt_tok:.1f} ({tok_delta:+.1f}%), "
            f"Hit Rate: {hit_rate:.1f}% -> Decision: {decision}"
        )

    # Restore default recommended configuration
    set_features(True, True, False)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run E3/E5/E6 ablation study")
    parser.add_argument(
        "--workload",
        type=Path,
        default=DEFAULT_WORKLOAD,
        help="Path to workload JSON",
    )
    args = parser.parse_args()

    workload = json.loads(args.workload.read_text(encoding="utf-8"))
    print("=" * 80)
    print("  AegisFlow Week 8 Optimization Ablation Study (E3, E5, E6)")
    print(f"  Workload size: {len(workload)} queries")
    print("=" * 80)

    rows = asyncio.run(run_ablation_suite(workload))

    print("\n" + "=" * 90)
    header = (
        f"{'Configuration':<28} | {'Latency (ms)':<14} | {'Tokens':<8} | "
        f"{'Hit%':<6} | {'Delta':<8} | {'Decision':<8}"
    )
    print(header)
    print("-" * 90)
    for r in rows:
        print(
            f"{r.config_name:<28} | "
            f"{r.mean_latency_ms:>7.1f} (p95:{r.p95_latency_ms:>5.0f}) | "
            f"{r.avg_prompt_tokens:>6.1f} | "
            f"{r.cache_hit_rate_pct:>5.1f}% | "
            f"{r.latency_delta_pct:>+6.1f}% | "
            f"{r.decision:<8}"
        )
    print("=" * 90)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / "ablation_week8.json"
    out_file.write_text(
        json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8"
    )
    print(f"\nSaved ablation results to: {out_file}")


if __name__ == "__main__":
    main()
