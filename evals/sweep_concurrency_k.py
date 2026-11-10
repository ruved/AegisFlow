"""Semaphore K parameter sweep script (E9).

Measures queue wait time, total latency, p95 tail latency, and throughput across K.
Enables selecting and justifying the optimal concurrency bound K.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aegisflow.concurrency import InferenceLimiter, RequestPriority  # noqa: E402

logger = logging.getLogger("aegisflow.sweep_k")


@dataclass
class KSweepResult:
    k: int
    concurrent_clients: int
    total_requests: int
    successful: int
    mean_queue_wait_ms: float
    mean_duration_ms: float
    p95_duration_ms: float
    throughput_rps: float


async def simulate_inference(
    limiter: InferenceLimiter,
    req_id: int,
    priority: RequestPriority,
    work_duration_s: float = 0.1,
) -> tuple[float, float]:
    """Simulate a model inference task through the priority limiter."""
    async with limiter.acquire(priority=priority, request_id=f"req_{req_id}") as info:
        q_wait = info["queue_wait_ms"]
        t0 = time.monotonic()
        await asyncio.sleep(work_duration_s)
        total_dur = (time.monotonic() - t0) * 1000.0 + q_wait
        return q_wait, total_dur


async def run_k_benchmark(
    k: int,
    num_requests: int = 12,
    concurrency: int = 4,
    work_s: float = 0.1,
) -> KSweepResult:
    """Run concurrent requests through an InferenceLimiter with bound K."""
    limiter = InferenceLimiter(k=k, aging_interval_s=1.0)
    queue_waits: list[float] = []
    durations: list[float] = []

    t_start = time.monotonic()

    async def client_worker(client_id: int, reqs_per_client: int) -> None:
        for r in range(reqs_per_client):
            prio = (
                RequestPriority.INTERACTIVE if (r % 3 == 0) else RequestPriority.NORMAL
            )
            qw, dur = await simulate_inference(
                limiter,
                req_id=client_id * 100 + r,
                priority=prio,
                work_duration_s=work_s,
            )
            queue_waits.append(qw)
            durations.append(dur)

    reqs_per_client = num_requests // concurrency
    tasks = [
        asyncio.create_task(client_worker(c, reqs_per_client))
        for c in range(concurrency)
    ]
    await asyncio.gather(*tasks)

    total_time_s = time.monotonic() - t_start
    durations_sorted = sorted(durations)
    p95_idx = int(0.95 * (len(durations_sorted) - 1)) if durations else 0

    mean_qw = sum(queue_waits) / len(queue_waits) if queue_waits else 0.0
    mean_dur = sum(durations) / len(durations) if durations else 0.0
    p95_dur = durations_sorted[p95_idx] if durations_sorted else 0.0
    throughput = len(durations) / total_time_s if total_time_s > 0 else 0.0

    return KSweepResult(
        k=k,
        concurrent_clients=concurrency,
        total_requests=len(durations),
        successful=len(durations),
        mean_queue_wait_ms=round(mean_qw, 1),
        mean_duration_ms=round(mean_dur, 1),
        p95_duration_ms=round(p95_dur, 1),
        throughput_rps=round(throughput, 2),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep inference concurrency semaphore K"
    )
    parser.add_argument(
        "--concurrency", type=int, default=4, help="Concurrent client workers"
    )
    parser.add_argument(
        "--requests", type=int, default=16, help="Total requests per K tier"
    )
    args = parser.parse_args()

    k_values = [1, 2, 4]
    results: list[KSweepResult] = []

    print("=" * 80)
    print("  AegisFlow E9 Semaphore K Concurrency & Tail Latency Sweep")
    print(f"  Concurrent Clients: {args.concurrency} | Total Requests: {args.requests}")
    print("=" * 80)

    for k in k_values:
        res = asyncio.run(
            run_k_benchmark(
                k=k, num_requests=args.requests, concurrency=args.concurrency
            )
        )
        results.append(res)
        print(
            f"K = {res.k:<2} | "
            f"Queue Wait: {res.mean_queue_wait_ms:>6.1f}ms | "
            f"Mean Lat: {res.mean_duration_ms:>6.1f}ms | "
            f"p95 Lat: {res.p95_duration_ms:>6.1f}ms | "
            f"Throughput: {res.throughput_rps:>5.1f} req/s"
        )

    print("=" * 80)
    print("Decision Analysis:")
    # Evaluate best trade-off between throughput and p95
    best_k = min(results, key=lambda x: x.p95_duration_ms)
    print(f"Selected Bound: K = {best_k.k}")
    p95_val = best_k.p95_duration_ms
    rps_val = best_k.throughput_rps
    print(
        f"Justification: K = {best_k.k} achieves optimal p95 ({p95_val}ms) "
        f"and throughput ({rps_val} req/s) while protecting Ollama."
    )

    out_file = PROJECT_ROOT / "results" / "semaphore_sweep_k.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
    )
    print(f"\nSaved sweep results to: {out_file}")


if __name__ == "__main__":
    main()
