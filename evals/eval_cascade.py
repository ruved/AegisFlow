"""Model cascade evaluation script comparing model routing (E7).

Compares small vs large models for Planner and Verifier.
Measures schema validation rates, node latencies, and model-swap delays.
Outputs decision and results to results/cascade_evaluation.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aegisflow.config import CHAT_MODEL, JUDGE_MODEL  # noqa: E402
from aegisflow.workflow.models import call_structured  # noqa: E402
from aegisflow.workflow.planning import PLANNER_SYSTEM, planner_prompt  # noqa: E402
from aegisflow.workflow.schemas import PlannerOutput  # noqa: E402

logger = logging.getLogger("aegisflow.cascade")


@dataclass
class CascadeNodeMetrics:
    model: str
    node: str
    total_calls: int
    valid_schema_calls: int
    validation_rate_pct: float
    mean_latency_ms: float
    p95_latency_ms: float
    model_swap_delay_ms: float


def test_planner_model(model: str, questions: list[str]) -> CascadeNodeMetrics:
    """Test schema validity and latency for Planner using a specific model."""
    durations: list[float] = []
    valid_count = 0

    for q in questions:
        t0 = time.perf_counter()
        try:
            call = call_structured(
                model=model,
                system=PLANNER_SYSTEM,
                user=planner_prompt(q),
                schema=PlannerOutput,
                remaining_tokens=4000,
            )
            dur = (time.perf_counter() - t0) * 1000.0
            durations.append(dur)
            if isinstance(call.value, PlannerOutput):
                valid_count += 1
        except Exception as exc:
            dur = (time.perf_counter() - t0) * 1000.0
            durations.append(dur)
            logger.warning("Planner failed on %s: %s", model, exc)

    n = len(questions)
    durations_sorted = sorted(durations) if durations else [0.0]
    p95_idx = int(0.95 * (len(durations_sorted) - 1))
    mean_lat = sum(durations) / n if n > 0 else 0.0

    return CascadeNodeMetrics(
        model=model,
        node="planner",
        total_calls=n,
        valid_schema_calls=valid_count,
        validation_rate_pct=round((valid_count / n) * 100.0, 1) if n > 0 else 0.0,
        mean_latency_ms=round(mean_lat, 1),
        p95_latency_ms=round(durations_sorted[p95_idx], 1),
        model_swap_delay_ms=0.0,
    )


def test_model_swap_overhead(model_a: str, model_b: str) -> float:
    """Measure delay incurred by alternating model calls in local Ollama."""
    dummy_system = "You are a helpful assistant."
    dummy_user = "Return a valid plan for: check service status"

    # Call Model A
    t0 = time.perf_counter()
    call_structured(
        model=model_a,
        system=dummy_system,
        user=dummy_user,
        schema=PlannerOutput,
        remaining_tokens=4000,
    )
    _ = (time.perf_counter() - t0) * 1000.0

    # Call Model B immediately (triggers model swap if memory residency limit is 1)
    t_swap = time.perf_counter()
    call_structured(
        model=model_b,
        system=dummy_system,
        user=dummy_user,
        schema=PlannerOutput,
        remaining_tokens=4000,
    )
    dur_swap = (time.perf_counter() - t_swap) * 1000.0

    # Call Model B again (warm call without swap)
    t_warm = time.perf_counter()
    call_structured(
        model=model_b,
        system=dummy_system,
        user=dummy_user,
        schema=PlannerOutput,
        remaining_tokens=4000,
    )
    dur_warm = (time.perf_counter() - t_warm) * 1000.0

    swap_overhead = max(0.0, dur_swap - dur_warm)
    return round(swap_overhead, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate E7 Model Cascade")
    parser.add_argument(
        "--limit", type=int, default=3, help="Number of questions to test"
    )
    args = parser.parse_args()

    test_questions = [
        "When Order Service runs out of database connections, what to do?",
        "What was the active connection count at recorded peak for order-01?",
        "Which external dependency slowed the consumers in PM-003?",
    ][: args.limit]

    print("=" * 80)
    print("  AegisFlow E7 Model Cascade Evaluation")
    print(f"  Primary Model: {CHAT_MODEL} | Alternate Model: {JUDGE_MODEL}")
    print("=" * 80)

    print("\n[1/3] Benchmarking Primary Model for Planner...")
    m_primary = test_planner_model(CHAT_MODEL, test_questions)
    valid_p = f"{m_primary.valid_schema_calls}/{m_primary.total_calls}"
    print(
        f"  {m_primary.model} -> Valid: {valid_p} "
        f"({m_primary.validation_rate_pct}%), Latency: {m_primary.mean_latency_ms}ms"
    )

    print("\n[2/3] Benchmarking Alternate Model for Planner...")
    m_alternate = test_planner_model(JUDGE_MODEL, test_questions)
    valid_a = f"{m_alternate.valid_schema_calls}/{m_alternate.total_calls}"
    print(
        f"  {m_alternate.model} -> Valid: {valid_a} "
        f"({m_alternate.validation_rate_pct}%), "
        f"Latency: {m_alternate.mean_latency_ms}ms"
    )

    print("\n[3/3] Measuring Local Model Swap Overhead...")
    swap_delay = test_model_swap_overhead(CHAT_MODEL, JUDGE_MODEL)
    print(f"  Measured Model Swap Delay: {swap_delay} ms")

    print("\n" + "=" * 80)
    print("Decision Analysis:")
    if swap_delay > 1500.0:
        print("Recommendation: DROP E7 in default single-GPU environments.")
        diff_ms = abs(m_primary.mean_latency_ms - m_alternate.mean_latency_ms)
        print(
            f"Reason: Model swapping overhead ({swap_delay:.1f}ms) completely "
            f"wipes out the {diff_ms:.1f}ms difference between models."
        )
        print(f"Maintaining {CHAT_MODEL} across all nodes keeps models resident.")
        decision = "DROP"
    else:
        print("Recommendation: KEEP E7 (both models resident without swap penalty).")
        decision = "KEEP"
    print("=" * 80)

    results = {
        "primary_metrics": asdict(m_primary),
        "alternate_metrics": asdict(m_alternate),
        "model_swap_delay_ms": swap_delay,
        "decision": decision,
    }

    out_path = PROJECT_ROOT / "results" / "cascade_evaluation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved cascade evaluation to: {out_path}")


if __name__ == "__main__":
    main()
