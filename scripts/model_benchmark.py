"""Repeatable local Ollama benchmark for AegisFlow.

Run from the repository root:
    uv run python scripts/model_benchmark.py

Uses only the Python standard library. Writes artifacts/model_benchmark.json.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OLLAMA_URL = "http://localhost:11434"
CHAT_MODELS = ["qwen3.5:4b-q4_K_M", "llama3.1:8b", "gemma3:4b"]
EMBED_MODEL = "nomic-embed-text:latest"
TRIALS = 3
NUM_CTX = 4096
NUM_PREDICT = 160

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_name": {
            "type": "string",
            "enum": ["search_docs", "get_deployment_status", "none"],
        },
        "arguments": {
            "type": "object",
            "properties": {"service_name": {"type": "string"}},
            "required": ["service_name"],
            "additionalProperties": False,
        },
        "reason": {"type": "string"},
    },
    "required": ["tool_name", "arguments", "reason"],
    "additionalProperties": False,
}
PROMPT = (
    "The user asks: 'What is the current deployment status of payments-api?' "
    "Select get_deployment_status and set service_name to payments-api. "
    "Return one JSON object matching the supplied schema. Keep reason short. "
    "Do not claim the tool has already run."
)


def post_json(path: str, payload: dict[str, Any], timeout: int = 240) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def stream_generate(model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": PROMPT,
        "format": SCHEMA,
        "stream": True,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }
    if model.startswith("qwen3.5"):
        payload["think"] = False
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    first_output_seconds: float | None = None
    response_parts: list[str] = []
    final: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            chunk = json.loads(raw_line.decode("utf-8"))
            response_part = chunk.get("response", "")
            thinking_part = chunk.get("thinking", "")
            if first_output_seconds is None and (response_part or thinking_part):
                first_output_seconds = time.perf_counter() - start
            if response_part:
                response_parts.append(response_part)
            if chunk.get("done"):
                final = chunk

    wall_seconds = time.perf_counter() - start
    raw_output = "".join(response_parts).strip()
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    try:
        value = json.loads(raw_output)
        if isinstance(value, dict):
            parsed = value
        else:
            parse_error = "JSON root is not an object"
    except (json.JSONDecodeError, TypeError) as exc:
        parse_error = str(exc)

    schema_valid = (
        parsed is not None
        and set(parsed) == {"tool_name", "arguments", "reason"}
        and parsed.get("tool_name") in {"search_docs", "get_deployment_status", "none"}
        and isinstance(parsed.get("arguments"), dict)
        and set(parsed["arguments"]) == {"service_name"}
        and isinstance(parsed["arguments"].get("service_name"), str)
        and isinstance(parsed.get("reason"), str)
    )
    correct_selection = (
        schema_valid
        and parsed is not None
        and parsed["tool_name"] == "get_deployment_status"
        and parsed["arguments"]["service_name"] == "payments-api"
    )
    eval_count = int(final.get("eval_count", 0) or 0)
    generation_seconds = int(final.get("eval_duration", 0) or 0) / 1_000_000_000
    return {
        "model": model,
        "wall_seconds": round(wall_seconds, 3),
        "first_output_seconds": (
            round(first_output_seconds, 3) if first_output_seconds is not None else None
        ),
        "load_seconds": round(
            int(final.get("load_duration", 0) or 0) / 1_000_000_000, 3
        ),
        "prompt_tokens": int(final.get("prompt_eval_count", 0) or 0),
        "output_tokens": eval_count,
        "generation_seconds": round(generation_seconds, 3),
        "tokens_per_second": (
            round(eval_count / generation_seconds, 2)
            if generation_seconds > 0
            else None
        ),
        "done_reason": final.get("done_reason"),
        "json_parse_valid": parsed is not None,
        "schema_valid": bool(schema_valid),
        "correct_tool_selection": bool(correct_selection),
        "parse_error": parse_error,
        "response": parsed if parsed is not None else raw_output[:1000],
    }


def benchmark_embedding() -> dict[str, Any]:
    start = time.perf_counter()
    result = post_json(
        "/api/embed",
        {
            "model": EMBED_MODEL,
            "input": "AegisFlow records tool execution status and trace metadata.",
        },
        timeout=180,
    )
    elapsed = time.perf_counter() - start
    embeddings = result.get("embeddings", [])
    vector = embeddings[0] if embeddings else []
    return {
        "model": EMBED_MODEL,
        "wall_seconds": round(elapsed, 3),
        "vector_dimensions": len(vector),
        "success": bool(vector),
    }


def summarize_model(model: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    def median_of(key: str) -> float | None:
        values = [
            float(row[key]) for row in trials if isinstance(row.get(key), (int, float))
        ]
        return round(statistics.median(values), 3) if values else None

    latencies = sorted(float(row["wall_seconds"]) for row in trials)
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None
    return {
        "model": model,
        "trials": len(trials),
        "median_wall_seconds": median_of("wall_seconds"),
        "p95_wall_seconds": round(p95, 3) if p95 is not None else None,
        "median_first_output_seconds": median_of("first_output_seconds"),
        "median_tokens_per_second": median_of("tokens_per_second"),
        "schema_valid_trials": sum(bool(row["schema_valid"]) for row in trials),
        "correct_selection_trials": sum(
            bool(row["correct_tool_selection"]) for row in trials
        ),
        "trials_detail": trials,
    }


def main() -> None:
    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "ollama_url": OLLAMA_URL,
        "config": {
            "chat_models": CHAT_MODELS,
            "embedding_model": EMBED_MODEL,
            "trials_per_model": TRIALS,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "temperature": 0,
        },
        "model_summaries": [],
        "embedding": None,
        "concurrency_test": None,
        "notes": [
            "First-output latency is time to first non-empty response or thinking "
            "fragment, not strict user-visible TTFT.",
            "Memory usage is not measured in this first version.",
            "With three trials, p95 is effectively the maximum observation; increase "
            "TRIALS for a more stable estimate.",
        ],
    }
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
            tags = json.loads(response.read().decode("utf-8"))
        available = {item["name"] for item in tags.get("models", [])}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot reach Ollama at {OLLAMA_URL}: {exc}") from exc

    for model in CHAT_MODELS:
        if model not in available:
            print(f"SKIP {model}: exact tag not found in /api/tags")
            continue
        print(f"\n=== {model}: warm-up (not measured) ===", flush=True)
        try:
            stream_generate(model)
            trials = []
            for index in range(TRIALS):
                print(f"Trial {index + 1}/{TRIALS}...", flush=True)
                row = stream_generate(model)
                trials.append(row)
                print(
                    f"wall={row['wall_seconds']}s, "
                    f"tokens/s={row['tokens_per_second']}, "
                    f"schema={row['schema_valid']}, "
                    f"correct={row['correct_tool_selection']}",
                    flush=True,
                )
            results["model_summaries"].append(summarize_model(model, trials))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            results["model_summaries"].append({"model": model, "error": str(exc)})
            print(f"ERROR testing {model}: {exc}", flush=True)

    print("\n=== Embedding test ===", flush=True)
    try:
        results["embedding"] = benchmark_embedding()
        print(results["embedding"], flush=True)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        results["embedding"] = {"success": False, "error": str(exc)}
        print(f"Embedding test failed: {exc}", flush=True)

    concurrency_model = "llama3.1:8b"
    if concurrency_model in available:
        print("\n=== Two-request concurrency test (Llama 3.1 8B) ===", flush=True)
        start = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(stream_generate, concurrency_model) for _ in range(2)
                ]
                concurrent_rows = [future.result() for future in futures]
            results["concurrency_test"] = {
                "model": concurrency_model,
                "parallel_requests": 2,
                "wall_seconds": round(time.perf_counter() - start, 3),
                "schema_valid_responses": sum(
                    bool(row["schema_valid"]) for row in concurrent_rows
                ),
                "correct_tool_selections": sum(
                    bool(row["correct_tool_selection"]) for row in concurrent_rows
                ),
                "individual_wall_seconds": [
                    row["wall_seconds"] for row in concurrent_rows
                ],
            }
            print(results["concurrency_test"], flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            results["concurrency_test"] = {"error": str(exc)}
            print(f"Concurrency test failed: {exc}", flush=True)

    output_path = output_dir / "model_benchmark.json"
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nSaved results to {output_path.resolve()}", flush=True)


if __name__ == "__main__":
    main()
