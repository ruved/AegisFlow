"""CI Quality Gate: Evaluates retrieval quality against baseline thresholds.

Runs deterministically using recorded test fixtures without requiring a GPU or live LLM.
Fails with exit code 1 if metrics drop below (baseline - tolerance).
Supports --simulate-regression to verify that deliberate degradation trips the gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "ci_eval_fixtures.json"


def evaluate_case(
    gold_sections: list[list[str]],
    retrieved_chunks: list[dict[str, Any]],
    k: int = 3,
) -> tuple[float, float]:
    """Calculate Recall@k and MRR for a single case.

    gold_sections: list of [doc, section] pairs.
    retrieved_chunks: list of chunk dicts with 'source' and 'heading'.
    """
    if not gold_sections:
        return 1.0, 1.0

    gold_set = {
        (doc.strip().lower(), sec.strip().lower()) for doc, sec in gold_sections
    }

    hits: list[int] = []
    found_gold: set[tuple[str, str]] = set()

    for rank, chunk in enumerate(retrieved_chunks[:k], start=1):
        src = str(chunk.get("source", "")).strip().lower()
        heading = str(chunk.get("heading", "")).strip().lower()
        pair = (src, heading)
        if pair in gold_set:
            hits.append(rank)
            found_gold.add(pair)

    recall = len(found_gold) / len(gold_set) if gold_set else 1.0
    mrr = (1.0 / hits[0]) if hits else 0.0
    return recall, mrr


def run_gate(
    fixtures_path: Path,
    baseline_recall: float = 0.70,
    baseline_mrr: float = 0.60,
    tolerance: float = 0.05,
    simulate_regression: bool = False,
    k: int = 3,
) -> tuple[bool, dict[str, Any]]:
    """Run the CI evaluation gate.

    Returns (passed, details_dict).
    """
    if not fixtures_path.exists():
        raise FileNotFoundError(f"Evaluation fixtures not found at {fixtures_path}")

    cases = json.loads(fixtures_path.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError("Evaluation fixtures file is empty")

    recalls: list[float] = []
    mrrs: list[float] = []

    for case in cases:
        gold = case.get("gold_sections", [])
        chunks = case.get("retrieved_chunks", [])
        if simulate_regression:
            # Deliberately strip or reverse chunks to simulate a regression PR
            chunks = []
        rec, mrr = evaluate_case(gold, chunks, k=k)
        recalls.append(rec)
        mrrs.append(mrr)

    macro_recall = sum(recalls) / len(recalls) if recalls else 0.0
    macro_mrr = sum(mrrs) / len(mrrs) if mrrs else 0.0

    min_recall = max(0.0, baseline_recall - tolerance)
    min_mrr = max(0.0, baseline_mrr - tolerance)

    passed = (macro_recall >= min_recall) and (macro_mrr >= min_mrr)

    details = {
        "passed": passed,
        "cases_evaluated": len(cases),
        "k": k,
        "measured_recall": round(macro_recall, 4),
        "baseline_recall": baseline_recall,
        "min_recall_threshold": round(min_recall, 4),
        "measured_mrr": round(macro_mrr, 4),
        "baseline_mrr": baseline_mrr,
        "min_mrr_threshold": round(min_mrr, 4),
        "tolerance": tolerance,
        "simulated_regression": simulate_regression,
    }
    return passed, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--baseline-recall", type=float, default=0.70)
    parser.add_argument("--baseline-mrr", type=float, default=0.60)
    parser.add_argument("--tolerance", type=float, default=0.05)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument(
        "--simulate-regression",
        action="store_true",
        help="Simulate a degrading PR to verify that the CI gate rejects it.",
    )
    args = parser.parse_args()

    passed, details = run_gate(
        fixtures_path=args.fixtures,
        baseline_recall=args.baseline_recall,
        baseline_mrr=args.baseline_mrr,
        tolerance=args.tolerance,
        simulate_regression=args.simulate_regression,
        k=args.k,
    )

    print("=" * 70)
    print("  AegisFlow CI Quality Gate")
    print("=" * 70)
    print(f"Cases Evaluated:      {details['cases_evaluated']}")
    print(
        f"Recall@{args.k}:           {details['measured_recall']:.3f} "
        f"(Threshold: {details['min_recall_threshold']:.3f})"
    )
    print(
        f"MRR:                 {details['measured_mrr']:.3f} "
        f"(Threshold: {details['min_mrr_threshold']:.3f})"
    )

    if passed:
        print("\n[PASS] CI Quality Gate Met: Retrieval quality meets baseline.")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n[FAIL] CI Quality Gate Tripped: Quality below tolerance!")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
