"""Concurrency load testing harness (D3).

Evaluates configuration across virtual user concurrency levels:
1, 4, 10, and 25 virtual users with 3 repetitions per level.
Measures p50, p95, p99 latency, throughput, and error rates.
Saves results to results/load_test_week9.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aegisflow.concurrency import InferenceLimiter, RequestPriority  # noqa: E402
from aegisflow.rag.retrieval import retrieve  # noqa: E402

logger = logging.getLogger("aegisflow.load_test")


@dataclass
class LoadTierResult:
    concurrency_users: int
    repetition: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_pct: float
    throughput_rps: float
    latency_mean_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * (pct / 100.0)
    floor_idx = math.floor(k)
    ceil_idx = math.ceil(k)
    if floor_idx == ceil_idx:
        return data[int(k)]
    d0 = data[floor_idx] * (ceil_idx - k)
    d1 = data[ceil_idx] * (k - floor_idx)
    return d0 + d1


async def simulate_user_request(
    limiter: InferenceLimiter,
    query: str,
    work_s: float = 0.05,
) -> float:
    """Execute a single query through concurrency limiter with simulated generation."""
    t0 = time.monotonic()
    async with limiter.acquire(priority=RequestPriority.NORMAL, timeout=30.0):
        # 1. Retrieve evidence
        _ = await retrieve(query, k=2)
        # 2. Simulated generation step
        await asyncio.sleep(work_s)
    return (time.monotonic() - t0) * 1000.0


async def run_single_tier(
    concurrency: int,
    rep: int,
    questions: list[str],
    requests_per_user: int = 2,
    k: int = 2,
) -> LoadTierResult:
    """Run a single load test repetition at a specific concurrency tier."""
    limiter = InferenceLimiter(k=k)
    durations: list[float] = []
    errors = 0

    t_start = time.monotonic()

    async def user_worker(user_id: int) -> None:
        nonlocal errors
        for i in range(requests_per_user):
            q = questions[(user_id + i) % len(questions)]
            try:
                dur = await simulate_user_request(limiter, q, work_s=0.04)
                durations.append(dur)
            except Exception as exc:
                errors += 1
                logger.warning("User %d request failed: %s", user_id, exc)

    tasks = [asyncio.create_task(user_worker(u)) for u in range(concurrency)]
    await asyncio.gather(*tasks)

    total_s = time.monotonic() - t_start
    total_reqs = len(durations) + errors
    durations_sorted = sorted(durations) if durations else [0.0]

    mean_lat = sum(durations) / len(durations) if durations else 0.0
    p50_lat = percentile(durations_sorted, 50)
    p95_lat = percentile(durations_sorted, 95)
    p99_lat = percentile(durations_sorted, 99)
    throughput = len(durations) / total_s if total_s > 0 else 0.0
    err_rate = (errors / total_reqs * 100.0) if total_reqs > 0 else 0.0

    return LoadTierResult(
        concurrency_users=concurrency,
        repetition=rep,
        total_requests=total_reqs,
        successful_requests=len(durations),
        failed_requests=errors,
        error_rate_pct=round(err_rate, 2),
        throughput_rps=round(throughput, 2),
        latency_mean_ms=round(mean_lat, 1),
        latency_p50_ms=round(p50_lat, 1),
        latency_p95_ms=round(p95_lat, 1),
        latency_p99_ms=round(p99_lat, 1),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisFlow Concurrency Load Test")
    parser.add_argument(
        "--repetitions", type=int, default=3, help="Reps per concurrency tier"
    )
    args = parser.parse_args()

    workload_path = PROJECT_ROOT / "data" / "eval" / "benchmark_workload.json"
    questions = [
        item["question"]
        for item in json.loads(workload_path.read_text(encoding="utf-8"))
    ]

    tiers = [1, 4, 10, 25]
    all_results: list[LoadTierResult] = []

    print("=" * 85)
    print("  AegisFlow Concurrency Load Testing (1, 4, 10, 25 Virtual Users)")
    print(
        f"  Repetitions: {args.repetitions} | OS: {platform.system()} "
        f"| CPU: {os.cpu_count()}"
    )
    print("=" * 85)

    for c in tiers:
        print(f"\n--- Testing Concurrency Level: {c} Virtual Users ---")
        for r in range(1, args.repetitions + 1):
            res = asyncio.run(
                run_single_tier(concurrency=c, rep=r, questions=questions, k=2)
            )
            all_results.append(res)
            print(
                f"  Rep {r}: p50: {res.latency_p50_ms:6.1f}ms | "
                f"p95: {res.latency_p95_ms:6.1f}ms | "
                f"p99: {res.latency_p99_ms:6.1f}ms | "
                f"Throughput: {res.throughput_rps:5.2f} req/s | "
                f"Errors: {res.failed_requests}"
            )

    print("\n" + "=" * 85)
    print("Summary Aggregates by Concurrency Tier:")
    header = (
        f"{'Users':<8} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | "
        f"{'p99 (ms)':<10} | {'Throughput':<12} | {'Error Rate'}"
    )
    print(header)
    print("-" * 85)

    summary_by_tier = {}
    for c in tiers:
        tier_runs = [r for r in all_results if r.concurrency_users == c]
        avg_p50 = sum(r.latency_p50_ms for r in tier_runs) / len(tier_runs)
        avg_p95 = sum(r.latency_p95_ms for r in tier_runs) / len(tier_runs)
        avg_p99 = sum(r.latency_p99_ms for r in tier_runs) / len(tier_runs)
        avg_rps = sum(r.throughput_rps for r in tier_runs) / len(tier_runs)
        avg_err = sum(r.error_rate_pct for r in tier_runs) / len(tier_runs)

        summary_by_tier[c] = {
            "p50_ms": round(avg_p50, 1),
            "p95_ms": round(avg_p95, 1),
            "p99_ms": round(avg_p99, 1),
            "throughput_rps": round(avg_rps, 2),
            "error_rate_pct": round(avg_err, 2),
        }
        row = (
            f"{c:<8} | {avg_p50:8.1f}ms | {avg_p95:8.1f}ms | {avg_p99:8.1f}ms | "
            f"{avg_rps:6.2f} req/s   | {avg_err:.1f}%"
        )
        print(row)
    print("=" * 85)

    out_file = PROJECT_ROOT / "results" / "load_test_week9.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_payload = {
        "hardware": {
            "os": platform.platform(),
            "cpu_cores": os.cpu_count(),
            "python": platform.python_version(),
        },
        "tiers_summary": summary_by_tier,
        "raw_trials": [asdict(r) for r in all_results],
    }
    out_file.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(f"\nSaved load test results to: {out_file}")


if __name__ == "__main__":
    main()
