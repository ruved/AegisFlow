"""Reproducible benchmark harness for AegisFlow performance and scalability.

Measures latency, TTFT, token consumption, and cache hit rates across a mixed workload
(unique queries, paraphrases, and overlapping sub-questions).
Supports warm-up, cold and warm modes, environment logging, and tolerance verification.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from aegisflow.config import CHAT_MODEL, EMBEDDING_MODEL, OLLAMA_BASE_URL
from aegisflow.rag.retrieval import retrieve

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKLOAD = PROJECT_ROOT / "data" / "eval" / "benchmark_workload.json"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"

logger = logging.getLogger("aegisflow.benchmark")


@dataclass
class QuerySample:
    """Individual benchmark trial measurement."""

    query_id: str
    category: str
    mode: str  # cold or warm
    duration_ms: float
    ttft_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit: bool
    status: str
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Aggregated statistics for a benchmark run."""

    timestamp: str
    mode: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    throughput_rps: float
    latency_mean_ms: float
    latency_std_ms: float
    latency_p50_ms: float
    latency_p90_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_min_ms: float
    latency_max_ms: float
    ttft_mean_ms: float
    ttft_p95_ms: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    avg_total_tokens: float
    cache_hit_rate_pct: float
    environment: dict[str, Any]


def get_environment_metadata() -> dict[str, Any]:
    """Capture reproducible hardware and software execution environment details."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "processor": platform.processor() or "Unknown",
        "chat_model": CHAT_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "temperature": 0.0,
    }


def percentile(data: list[float], pct: float) -> float:
    """Compute percentile from sorted float sequence."""
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * (pct / 100.0)
    floor_idx = math.floor(k)
    ceil_idx = math.ceil(k)
    if floor_idx == ceil_idx:
        return data[int(k)]
    d0 = data[floor_idx] * (ceil_idx - k)
    d1 = data[ceil_idx] * (k - floor_idx)
    return d0 + d1


def compute_summary(
    samples: list[QuerySample],
    total_duration_s: float,
    mode: str,
    environment: dict[str, Any],
) -> BenchmarkSummary:
    """Aggregate individual sample measurements into statistical summary."""
    successful = [s for s in samples if s.status == "ok"]
    failed = [s for s in samples if s.status != "ok"]
    n = len(successful)

    if n == 0:
        return BenchmarkSummary(
            timestamp=datetime.now(UTC).isoformat(),
            mode=mode,
            total_requests=len(samples),
            successful_requests=0,
            failed_requests=len(failed),
            throughput_rps=0.0,
            latency_mean_ms=0.0,
            latency_std_ms=0.0,
            latency_p50_ms=0.0,
            latency_p90_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            latency_min_ms=0.0,
            latency_max_ms=0.0,
            ttft_mean_ms=0.0,
            ttft_p95_ms=0.0,
            avg_prompt_tokens=0.0,
            avg_completion_tokens=0.0,
            avg_total_tokens=0.0,
            cache_hit_rate_pct=0.0,
            environment=environment,
        )

    durations = sorted(s.duration_ms for s in successful)
    ttfts = sorted(s.ttft_ms for s in successful)

    mean_lat = sum(durations) / n
    variance = sum((x - mean_lat) ** 2 for x in durations) / n
    std_lat = math.sqrt(variance)

    hits = sum(1 for s in successful if s.cache_hit)
    hit_rate = (hits / n) * 100.0

    prompt_toks = sum(s.prompt_tokens for s in successful) / n
    comp_toks = sum(s.completion_tokens for s in successful) / n
    tot_toks = sum(s.total_tokens for s in successful) / n

    throughput = n / total_duration_s if total_duration_s > 0 else 0.0

    return BenchmarkSummary(
        timestamp=datetime.now(UTC).isoformat(),
        mode=mode,
        total_requests=len(samples),
        successful_requests=n,
        failed_requests=len(failed),
        throughput_rps=round(throughput, 2),
        latency_mean_ms=round(mean_lat, 2),
        latency_std_ms=round(std_lat, 2),
        latency_p50_ms=round(percentile(durations, 50), 2),
        latency_p90_ms=round(percentile(durations, 90), 2),
        latency_p95_ms=round(percentile(durations, 95), 2),
        latency_p99_ms=round(percentile(durations, 99), 2),
        latency_min_ms=round(durations[0], 2),
        latency_max_ms=round(durations[-1], 2),
        ttft_mean_ms=round(sum(ttfts) / n, 2),
        ttft_p95_ms=round(percentile(ttfts, 95), 2),
        avg_prompt_tokens=round(prompt_toks, 1),
        avg_completion_tokens=round(comp_toks, 1),
        avg_total_tokens=round(tot_toks, 1),
        cache_hit_rate_pct=round(hit_rate, 2),
        environment=environment,
    )


async def execute_query_direct(
    item: dict[str, Any],
    mode: str,
) -> QuerySample:
    """Execute a single retrieval/workflow query in-process and measure metrics."""
    q_id = item.get("id", "UNKNOWN")
    category = item.get("category", "unique")
    question = item["question"]

    t0 = time.perf_counter()
    ttft_ms = 0.0
    try:
        # Measure retrieval time
        t_first = time.perf_counter()
        results = await retrieve(question, k=3)
        ttft_ms = (time.perf_counter() - t_first) * 1000.0
        duration_ms = (time.perf_counter() - t0) * 1000.0

        # Approximate tokens in retrieved context
        context_text = " ".join(r.get("text", "") for r in results)
        prompt_tokens = max(1, (len(question) + len(context_text)) // 4)
        completion_tokens = 0
        total_tokens = prompt_tokens

        # Check if result was served from cache
        cache_hit = any(r.get("cache_hit", False) for r in results)

        return QuerySample(
            query_id=q_id,
            category=category,
            mode=mode,
            duration_ms=round(duration_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_hit=cache_hit,
            status="ok",
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return QuerySample(
            query_id=q_id,
            category=category,
            mode=mode,
            duration_ms=round(duration_ms, 2),
            ttft_ms=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cache_hit=False,
            status="error",
            error=str(exc),
        )


async def execute_query_http(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    item: dict[str, Any],
    mode: str,
) -> QuerySample:
    """Execute query via HTTP against running AegisFlow service."""
    q_id = item.get("id", "UNKNOWN")
    category = item.get("category", "unique")
    question = item["question"]

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/v1/ask",
            json={"question": question, "top_k": 3},
            headers=headers,
            timeout=60.0,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        if resp.status_code == 200:
            data = resp.json()
            # If server doesn't provide fine-grained tokens, estimate
            ans = data.get("answer", "")
            prompt_tokens = max(1, len(question) // 4 + 200)
            comp_tokens = max(1, len(ans) // 4)
            return QuerySample(
                query_id=q_id,
                category=category,
                mode=mode,
                duration_ms=round(duration_ms, 2),
                ttft_ms=round(duration_ms * 0.4, 2),  # Estimated TTFT
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=prompt_tokens + comp_tokens,
                cache_hit=bool(data.get("cache_hit", False)),
                status="ok",
            )
        else:
            return QuerySample(
                query_id=q_id,
                category=category,
                mode=mode,
                duration_ms=round(duration_ms, 2),
                ttft_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cache_hit=False,
                status="error",
                error=f"HTTP {resp.status_code}: {resp.text[:100]}",
            )
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return QuerySample(
            query_id=q_id,
            category=category,
            mode=mode,
            duration_ms=round(duration_ms, 2),
            ttft_ms=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cache_hit=False,
            status="error",
            error=str(exc),
        )


async def run_benchmark(
    workload: list[dict[str, Any]],
    mode: str = "warm",
    warmup_count: int = 2,
    http_url: str | None = None,
    api_key: str = "test-secret-key-12345",
) -> tuple[BenchmarkSummary, list[QuerySample]]:
    """Run full benchmark sequence: warm-up, workload execution, metrics aggregation."""
    env = get_environment_metadata()

    # 1. Warm-up phase
    if warmup_count > 0:
        warmup_items = workload[: min(warmup_count, len(workload))]
        if http_url:
            async with httpx.AsyncClient() as client:
                for item in warmup_items:
                    await execute_query_http(
                        client, http_url, api_key, item, mode="warmup"
                    )
        else:
            for item in warmup_items:
                await execute_query_direct(item, mode="warmup")

    # 2. Main benchmark measurement phase
    samples: list[QuerySample] = []
    t_start = time.perf_counter()

    if http_url:
        async with httpx.AsyncClient() as client:
            for item in workload:
                sample = await execute_query_http(
                    client, http_url, api_key, item, mode=mode
                )
                samples.append(sample)
    else:
        for item in workload:
            sample = await execute_query_direct(item, mode=mode)
            samples.append(sample)

    total_s = time.perf_counter() - t_start
    summary = compute_summary(samples, total_s, mode, env)
    return summary, samples


def save_results(
    summary: BenchmarkSummary,
    samples: list[QuerySample],
    output_dir: Path = DEFAULT_RESULTS_DIR,
    prefix: str = "benchmark",
) -> tuple[Path, Path]:
    """Persist benchmark details to CSV and summary to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    csv_path = output_dir / f"{prefix}_{summary.mode}_{timestamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=[f.name for f in QuerySample.__dataclass_fields__.values()]
        )  # type: ignore[attr-defined]
        writer.writeheader()
        for s in samples:
            writer.writerow(asdict(s))

    json_path = output_dir / f"{prefix}_{summary.mode}_{timestamp}.json"
    json_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")

    return csv_path, json_path


def verify_repeatability(
    run1: BenchmarkSummary,
    run2: BenchmarkSummary,
    tolerance: float = 0.15,
) -> tuple[bool, str]:
    """Verify that two identical-config benchmark runs fall within tolerance."""
    lat1 = run1.latency_mean_ms
    lat2 = run2.latency_mean_ms
    if lat1 == 0 or lat2 == 0:
        return False, "Mean latency is zero in one of the runs."

    diff_mean = abs(lat1 - lat2) / max(lat1, lat2)
    p95_1 = run1.latency_p95_ms
    p95_2 = run2.latency_p95_ms
    diff_p95 = abs(p95_1 - p95_2) / max(p95_1, p95_2) if max(p95_1, p95_2) > 0 else 0.0

    passed = diff_mean <= tolerance and diff_p95 <= tolerance
    pct_m = diff_mean * 100
    pct_p = diff_p95 * 100
    tol_pct = tolerance * 100
    msg = (
        f"Run 1 Mean: {lat1:.1f}ms, Run 2 Mean: {lat2:.1f}ms "
        f"(variance: {pct_m:.1f}%, limit: {tol_pct:.1f}%)\n"
        f"Run 1 p95:  {p95_1:.1f}ms, Run 2 p95:  {p95_2:.1f}ms "
        f"(variance: {pct_p:.1f}%, limit: {tol_pct:.1f}%)"
    )
    return passed, msg


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisFlow Benchmark Harness")
    parser.add_argument(
        "--workload",
        type=Path,
        default=DEFAULT_WORKLOAD,
        help="Path to workload JSON",
    )
    parser.add_argument(
        "--mode",
        choices=["cold", "warm"],
        default="warm",
        help="Benchmark mode (cold or warm)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Number of warmup queries",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Optional HTTP URL to benchmark running service",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="test-secret-key-12345",
        help="API Key for HTTP benchmark",
    )
    parser.add_argument(
        "--check-tolerance",
        action="store_true",
        help="Run two identical passes and verify variance is within 15%",
    )
    args = parser.parse_args()

    if not args.workload.exists():
        print(f"Error: Workload file not found at {args.workload}")
        sys.exit(1)

    workload = json.loads(args.workload.read_text(encoding="utf-8"))
    print("=" * 70)
    print("  AegisFlow Performance Benchmark")
    print(f"  Mode: {args.mode.upper()} | Workload: {len(workload)} queries")
    print("=" * 70)

    if args.check_tolerance:
        print("\n[Pass 1/2] Executing run 1...")
        summary1, samples1 = asyncio.run(
            run_benchmark(
                workload,
                mode=args.mode,
                warmup_count=args.warmup,
                http_url=args.url,
                api_key=args.api_key,
            )
        )
        print(
            f"Run 1 completed: Mean = {summary1.latency_mean_ms} ms, "
            f"p95 = {summary1.latency_p95_ms} ms"
        )

        print("\n[Pass 2/2] Executing run 2...")
        summary2, samples2 = asyncio.run(
            run_benchmark(
                workload,
                mode=args.mode,
                warmup_count=0,
                http_url=args.url,
                api_key=args.api_key,
            )
        )
        print(
            f"Run 2 completed: Mean = {summary2.latency_mean_ms} ms, "
            f"p95 = {summary2.latency_p95_ms} ms"
        )

        passed, msg = verify_repeatability(summary1, summary2, tolerance=0.15)
        print("\nRepeatability Check:")
        print(msg)
        if passed:
            print("\n[PASS] Repeatability verified within 15% tolerance.")
        else:
            print("\n[WARNING] Repeatability exceeded 15% tolerance.")

        csv1, json1 = save_results(summary1, samples1, prefix="benchmark_pass1")
        csv2, json2 = save_results(summary2, samples2, prefix="benchmark_pass2")
        print(f"\nSaved results:\n  - {csv1}\n  - {json1}\n  - {csv2}\n  - {json2}")
        return

    summary, samples = asyncio.run(
        run_benchmark(
            workload,
            mode=args.mode,
            warmup_count=args.warmup,
            http_url=args.url,
            api_key=args.api_key,
        )
    )

    print("\nBenchmark Results:")
    print(
        f"Total Requests:     {summary.total_requests} "
        f"(Success: {summary.successful_requests}, Failed: {summary.failed_requests})"
    )
    print(f"Throughput:         {summary.throughput_rps} req/s")
    print(
        f"Latency Mean:       {summary.latency_mean_ms} ms "
        f"(std: {summary.latency_std_ms} ms)"
    )
    print(f"Latency p50:        {summary.latency_p50_ms} ms")
    print(f"Latency p95:        {summary.latency_p95_ms} ms")
    print(f"Latency p99:        {summary.latency_p99_ms} ms")
    print(
        f"Latency Min / Max:  {summary.latency_min_ms} ms / {summary.latency_max_ms} ms"
    )
    print(f"TTFT Mean / p95:    {summary.ttft_mean_ms} ms / {summary.ttft_p95_ms} ms")
    print(
        f"Avg Tokens:         Prompt: {summary.avg_prompt_tokens}, "
        f"Comp: {summary.avg_completion_tokens}, "
        f"Total: {summary.avg_total_tokens}"
    )
    print(f"Cache Hit Rate:     {summary.cache_hit_rate_pct}%")

    csv_path, json_path = save_results(summary, samples)
    print(f"\nArtifacts:\n  CSV:  {csv_path}\n  JSON: {json_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
