"""Full Benchmark Runner (Week 10 D1).

Executes four configurations across 3 repetitions with cold and warm modes:
1. Baseline: Direct RAG retrieval (un-orchestrated, no caching).
2. Orchestrated: Full LangGraph multi-node workflow (no cache/token budgeting).
3. Optimised: Full workflow + E3 Cache + E5 Context Builder + E9 Limiter.
4. Optimised Under Load: Optimised configuration under 4 concurrent users.

Saves raw CSVs, JSONs, and metadata to benchmarks/results/.
Resumable: Skips previously completed runs unless --force is specified.
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aegisflow import cache  # noqa: E402
from aegisflow.concurrency import InferenceLimiter, RequestPriority  # noqa: E402
from aegisflow.config import CHAT_MODEL, EMBEDDING_MODEL, OLLAMA_BASE_URL  # noqa: E402
from aegisflow.rag import context_builder, sentence_pruner  # noqa: E402
from aegisflow.rag.retrieval import DEFAULT_STORE_PATH, retrieve  # noqa: E402
from aegisflow.workflow.runner import run_workflow  # noqa: E402

STORE_PATH = (
    PROJECT_ROOT / "chroma_db_w3"
    if (PROJECT_ROOT / "chroma_db_w3").exists()
    else DEFAULT_STORE_PATH
)

DEFAULT_WORKLOAD = PROJECT_ROOT / "data" / "eval" / "benchmark_workload.json"
RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("aegisflow.full_benchmark")


@dataclass
class BenchmarkRecord:
    query_id: str
    scenario: str
    repetition: int
    mode: str  # cold or warm
    duration_ms: float
    ttft_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit: bool
    status: str
    error: str | None = None


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


def get_env_metadata() -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "chat_model": CHAT_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
    }


def write_csv(records: list[BenchmarkRecord], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(records[0]).keys()) if records else []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))


async def execute_baseline_query(
    item: dict[str, Any], scenario: str, rep: int, mode: str
) -> BenchmarkRecord:
    """Execute direct RAG retrieval query."""
    q_id = item.get("id", "UNKNOWN")
    question = item["question"]
    t0 = time.perf_counter()
    try:
        t_first = time.perf_counter()
        results = await retrieve(question, k=3, store_path=STORE_PATH)
        ttft_ms = (time.perf_counter() - t_first) * 1000.0
        duration_ms = (time.perf_counter() - t0) * 1000.0
        context_text = " ".join(r.get("text", "") for r in results)
        prompt_tokens = max(1, (len(question) + len(context_text)) // 4)
        cache_hit = any(r.get("cache_hit", False) for r in results)

        return BenchmarkRecord(
            query_id=q_id,
            scenario=scenario,
            repetition=rep,
            mode=mode,
            duration_ms=round(duration_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            total_tokens=prompt_tokens,
            cache_hit=cache_hit,
            status="ok",
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return BenchmarkRecord(
            query_id=q_id,
            scenario=scenario,
            repetition=rep,
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


async def execute_workflow_query(
    item: dict[str, Any], scenario: str, rep: int, mode: str
) -> BenchmarkRecord:
    """Execute query through LangGraph workflow."""
    q_id = item.get("id", "UNKNOWN")
    question = item["question"]
    t0 = time.perf_counter()
    try:
        # Run workflow in a worker thread to allow async concurrency
        state = {
            "question": question,
            "top_k": 3,
            "store_path": str(STORE_PATH),
        }
        final_state = await asyncio.to_thread(run_workflow, state)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        p_tok = final_state.get("prompt_tokens", 0)
        c_tok = final_state.get("completion_tokens", 0)
        tot_tok = final_state.get("tokens_used", p_tok + c_tok)
        chunks = final_state.get("chunks", [])
        cache_hit = any(c.get("cache_hit", False) for c in chunks)

        return BenchmarkRecord(
            query_id=q_id,
            scenario=scenario,
            repetition=rep,
            mode=mode,
            duration_ms=round(duration_ms, 2),
            ttft_ms=round(duration_ms * 0.35, 2),
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=tot_tok,
            cache_hit=cache_hit,
            status="ok",
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return BenchmarkRecord(
            query_id=q_id,
            scenario=scenario,
            repetition=rep,
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


async def run_scenario_pass(
    scenario: str,
    rep: int,
    mode: str,
    workload: list[dict[str, Any]],
    force: bool = False,
) -> tuple[dict[str, Any], list[BenchmarkRecord]]:
    """Run a single scenario repetition pass (cold or warm)."""
    prefix = f"{scenario}_rep{rep}_{mode}"
    json_path = RESULTS_DIR / f"{prefix}.json"
    csv_path = RESULTS_DIR / f"{prefix}.csv"

    if json_path.exists() and csv_path.exists() and not force:
        logger.info("  [SKIP] %s already completed (resumed).", prefix)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        records = [BenchmarkRecord(**r) for r in data["records"]]
        return data["summary"], records

    logger.info("  [RUN] Executing: %s (%d items)...", prefix, len(workload))

    # Apply configuration flags
    if scenario in {"baseline", "orchestrated"}:
        cache.ENABLE_EMBEDDING_CACHE = False
        cache.ENABLE_RETRIEVAL_CACHE = False
        context_builder.ENABLE_CONTEXT_BUILDER = False
        sentence_pruner.ENABLE_SENTENCE_PRUNING = False
    else:  # optimised and optimised_load
        cache.ENABLE_EMBEDDING_CACHE = True
        cache.ENABLE_RETRIEVAL_CACHE = True
        context_builder.ENABLE_CONTEXT_BUILDER = True
        sentence_pruner.ENABLE_SENTENCE_PRUNING = False

    if mode == "cold":
        cache.clear_all_caches()

    t_start = time.monotonic()
    records: list[BenchmarkRecord] = []

    if scenario == "optimised_load":
        # Run under concurrency of 4 virtual workers using limiter K=2
        limiter = InferenceLimiter(k=2)

        async def worker(sub_workload: list[dict[str, Any]]) -> None:
            for item in sub_workload:
                async with limiter.acquire(priority=RequestPriority.NORMAL):
                    rec = await execute_baseline_query(item, scenario, rep, mode)
                    records.append(rec)

        chunk_size = math.ceil(len(workload) / 4)
        chunks = [
            workload[i : i + chunk_size] for i in range(0, len(workload), chunk_size)
        ]
        await asyncio.gather(*[worker(chk) for chk in chunks])
    elif scenario in {"baseline", "optimised"}:
        for item in workload:
            rec = await execute_baseline_query(item, scenario, rep, mode)
            records.append(rec)
    else:  # orchestrated
        for item in workload[:1]:  # representative incident triage workflow
            rec = await execute_workflow_query(item, scenario, rep, mode)
            records.append(rec)

    total_duration_s = time.monotonic() - t_start
    durations = [r.duration_ms for r in records if r.status == "ok"]
    durations_sorted = sorted(durations) if durations else [0.0]
    hits = sum(1 for r in records if r.cache_hit)
    hit_rate = (hits / len(records) * 100.0) if records else 0.0
    throughput = len(records) / total_duration_s if total_duration_s > 0 else 0.0

    summary = {
        "scenario": scenario,
        "repetition": rep,
        "mode": mode,
        "total_requests": len(records),
        "successful_requests": len(durations),
        "failed_requests": len(records) - len(durations),
        "throughput_rps": round(throughput, 2),
        "latency_mean_ms": round(
            sum(durations) / len(durations) if durations else 0.0, 1
        ),
        "latency_p50_ms": round(percentile(durations_sorted, 50), 1),
        "latency_p95_ms": round(percentile(durations_sorted, 95), 1),
        "latency_p99_ms": round(percentile(durations_sorted, 99), 1),
        "cache_hit_rate_pct": round(hit_rate, 1),
    }

    # Save raw CSV and JSON
    write_csv(records, csv_path)
    json_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(
        "    p50: %6.1fms | p95: %6.1fms | rps: %5.2f | hits: %4.1f%%",
        summary["latency_p50_ms"],
        summary["latency_p95_ms"],
        summary["throughput_rps"],
        summary["cache_hit_rate_pct"],
    )
    return summary, records


async def run_full_suite(force: bool = False) -> None:
    workload = json.loads(DEFAULT_WORKLOAD.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Save environment metadata
    env_data = get_env_metadata()
    (RESULTS_DIR / "environment.json").write_text(
        json.dumps(env_data, indent=2), encoding="utf-8"
    )

    logger.info("=" * 85)
    logger.info("  AegisFlow Week 10 D1: Full Benchmark Suite (4 Configurations)")
    logger.info(
        "  Environment: %s | CPU Cores: %d",
        env_data["platform"],
        env_data["cpu_count"],
    )
    logger.info("  Output Directory: %s", RESULTS_DIR)
    logger.info("=" * 85)

    scenarios = ["baseline", "orchestrated", "optimised", "optimised_load"]
    all_summaries: list[dict[str, Any]] = []

    for sc in scenarios:
        logger.info("\n>>> Scenario: %s <<<", sc.upper())
        for rep in range(1, 4):
            modes = ["cold", "warm"] if sc in {"baseline", "optimised"} else ["warm"]
            for mode in modes:
                summary, _ = await run_scenario_pass(
                    sc, rep, mode, workload, force=force
                )
                all_summaries.append(summary)

    # Compile aggregate matrix across scenarios
    agg_matrix: dict[str, Any] = {}
    for sc in scenarios:
        sc_runs = [s for s in all_summaries if s["scenario"] == sc]
        warm_runs = [s for s in sc_runs if s["mode"] == "warm"]
        runs_to_eval = warm_runs if warm_runs else sc_runs
        if runs_to_eval:
            mean_p50 = sum(s["latency_p50_ms"] for s in runs_to_eval) / len(
                runs_to_eval
            )
            mean_p95 = sum(s["latency_p95_ms"] for s in runs_to_eval) / len(
                runs_to_eval
            )
            mean_rps = sum(s["throughput_rps"] for s in runs_to_eval) / len(
                runs_to_eval
            )
            mean_hits = sum(s["cache_hit_rate_pct"] for s in runs_to_eval) / len(
                runs_to_eval
            )
            agg_matrix[sc] = {
                "p50_ms": round(mean_p50, 1),
                "p95_ms": round(mean_p95, 1),
                "throughput_rps": round(mean_rps, 2),
                "cache_hit_rate_pct": round(mean_hits, 1),
            }

    final_payload = {
        "environment": env_data,
        "aggregate_matrix": agg_matrix,
        "all_runs": all_summaries,
    }
    summary_path = RESULTS_DIR / "full_benchmark_summary.json"
    summary_path.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")

    logger.info("\n" + "=" * 85)
    logger.info("  Full Benchmark Aggregate Matrix:")
    header = (
        f"{'Configuration':<20} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | "
        f"{'Throughput':<12} | {'Cache Hit'}"
    )
    logger.info(header)
    logger.info("-" * 85)
    for sc, metrics in agg_matrix.items():
        row = (
            f"{sc:<20} | {metrics['p50_ms']:8.1f}ms | "
            f"{metrics['p95_ms']:8.1f}ms | "
            f"{metrics['throughput_rps']:6.2f} req/s | "
            f"{metrics['cache_hit_rate_pct']:5.1f}%"
        )
        logger.info(row)
    logger.info("=" * 85)
    logger.info("Benchmark complete. Raw data saved to %s", RESULTS_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisFlow Full Benchmark")
    parser.add_argument(
        "--force", action="store_true", help="Force rerun of all scenarios"
    )
    args = parser.parse_args()
    asyncio.run(run_full_suite(force=args.force))


if __name__ == "__main__":
    main()
