"""Compare the bounded LangGraph workflow with saved E1 answer results."""

import argparse
import csv
import json
import statistics
import time
from pathlib import Path
from typing import Any

from aegisflow.config import CHAT_MODEL
from aegisflow.evaluation import (
    DEFAULT_DATASET_PATH,
    load_golden_dataset,
    normalize_source_path,
)
from aegisflow.workflow.runner import run_workflow

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_E1 = ROOT / "results" / "baseline_E1_answer.csv"
DEFAULT_OUTPUT = ROOT / "results" / "E4_workflow.csv"
DEFAULT_W3_STORE = ROOT / "chroma_db_w3"
FIELDS = [
    "question_id",
    "slice",
    "question",
    "planner_valid",
    "subquestion_count",
    "diagnosis",
    "abstained",
    "missing",
    "citations",
    "citation_precision",
    "citation_recall",
    "task_completed",
    "latency_ms",
    "steps",
    "tokens_used",
    "telemetry",
    "error",
]


def _scores(
    citations: list[dict[str, Any]], gold_sections: tuple[tuple[str, str], ...]
) -> tuple[float | None, float | None]:
    if not gold_sections:
        return None, None
    gold = {
        (normalize_source_path(source), section) for source, section in gold_sections
    }
    cited = {
        (
            normalize_source_path(str(citation.get("source", ""))),
            str(citation.get("heading", "")),
        )
        for citation in citations
    }
    true_positive = len(gold & cited)
    precision = true_positive / len(cited) if cited else 0.0
    recall = true_positive / len(gold)
    return precision, recall


def run(
    dataset: Path,
    store: Path,
    output: Path,
    limit: int | None,
    e1_path: Path = DEFAULT_E1,
    slice_filter: str | None = None,
) -> dict[str, Any]:
    cases = load_golden_dataset(dataset)
    if slice_filter:
        cases = [case for case in cases if case.slice == slice_filter]
    if limit is not None:
        cases = cases[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        row: dict[str, Any] = {
            "question_id": case.id,
            "slice": case.slice,
            "question": case.question,
        }
        try:
            state = run_workflow({"question": case.question, "store_path": str(store)})
            report = state.get("report", {})
            citations = report.get("citations", [])
            precision, recall = _scores(citations, case.gold_sections)
            row.update(
                diagnosis=report.get("diagnosis", ""),
                planner_valid=bool(state.get("planner_output")),
                subquestion_count=len(state.get("subquestions", [])),
                abstained=state.get("abstained", True),
                missing=json.dumps(report.get("missing", []), ensure_ascii=False),
                citations=json.dumps(citations, ensure_ascii=False),
                citation_precision=precision,
                citation_recall=recall,
                task_completed=(
                    bool(state.get("abstained"))
                    if case.slice == "unanswerable"
                    else bool(
                        not state.get("abstained") and recall is not None and recall > 0
                    )
                ),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                steps=state.get("steps", 0),
                tokens_used=state.get("tokens_used", 0),
                telemetry=json.dumps(state.get("telemetry", []), ensure_ascii=False),
                error="",
            )
        except Exception as exc:
            row.update(
                diagnosis="",
                planner_valid=False,
                subquestion_count=0,
                slice=case.slice,
                abstained=True,
                missing="[]",
                citations="[]",
                citation_precision=0.0,
                citation_recall=0.0,
                task_completed=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                steps=0,
                tokens_used=0,
                telemetry="[]",
                error=f"{type(exc).__name__}: {exc}",
            )
        rows.append(row)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(
            f"[{index}/{len(cases)}] {case.id}: "
            f"error={bool(row['error'])}, abstained={row['abstained']}, "
            f"latency_ms={row['latency_ms']}",
            flush=True,
        )

    evaluated = [row for row in rows if not row["error"]]
    citation_precision = [
        row["citation_precision"]
        for row in evaluated
        if row["citation_precision"] is not None
    ]
    citation_recall = [
        row["citation_recall"]
        for row in evaluated
        if row["citation_recall"] is not None
    ]
    timings = [float(row["latency_ms"]) for row in evaluated]
    slice_metrics = {
        slice_name: {
            "count": sum(row["slice"] == slice_name for row in evaluated),
            "task_completion_rate": (
                sum(
                    bool(row["task_completed"])
                    for row in evaluated
                    if row["slice"] == slice_name
                )
                / sum(row["slice"] == slice_name for row in evaluated)
                if any(row["slice"] == slice_name for row in evaluated)
                else None
            ),
            "abstention_rate": (
                sum(
                    bool(row["abstained"])
                    for row in evaluated
                    if row["slice"] == slice_name
                )
                / sum(row["slice"] == slice_name for row in evaluated)
                if any(row["slice"] == slice_name for row in evaluated)
                else None
            ),
        }
        for slice_name in sorted({row["slice"] for row in evaluated})
    }
    e1_rows: dict[str, dict[str, str]] = {}
    if e1_path.is_file():
        with e1_path.open(encoding="utf-8", newline="") as handle:
            e1_rows = {
                row["question_id"]: row
                for row in csv.DictReader(handle)
                if row.get("question_id")
            }
    paired = [row for row in evaluated if row["question_id"] in e1_rows]
    baseline_latencies = [
        float(e1_rows[row["question_id"]]["latency_ms_median"])
        for row in paired
        if e1_rows[row["question_id"]].get("latency_ms_median")
    ]
    baseline_successes = [
        row
        for row in paired
        if int(e1_rows[row["question_id"]].get("failed_runs", "1")) == 0
    ]
    node_times: dict[str, list[float]] = {}
    node_tokens: dict[str, list[int]] = {}
    for row in evaluated:
        for event in json.loads(row["telemetry"]):
            node_times.setdefault(event["node"], []).append(event["duration_ms"])
            node_tokens.setdefault(event["node"], []).append(
                event["prompt_tokens"] + event["completion_tokens"]
            )
    summary = {
        "dataset": str(dataset),
        "store": str(store),
        "planner_model": CHAT_MODEL,
        "analyst_reporter_verifier_model": CHAT_MODEL,
        "workflow_prompt_version": "w4-analyst-evidence-extraction-v2",
        "max_steps": 14,
        "max_tokens": 6000,
        "max_retries": 1,
        "question_count": len(cases),
        "successful_runs": len(evaluated),
        "failed_runs": len(rows) - len(evaluated),
        "planner_valid_rate": (
            sum(bool(row["planner_valid"]) for row in evaluated) / len(evaluated)
            if evaluated
            else None
        ),
        "task_completion_rate": (
            sum(bool(row["task_completed"]) for row in evaluated) / len(evaluated)
        )
        if evaluated
        else None,
        "abstention_rate": (
            sum(bool(row["abstained"]) for row in evaluated) / len(evaluated)
        )
        if evaluated
        else None,
        "mean_citation_precision": statistics.mean(citation_precision)
        if citation_precision
        else None,
        "mean_citation_recall": statistics.mean(citation_recall)
        if citation_recall
        else None,
        "per_slice": slice_metrics,
        "median_latency_ms": statistics.median(timings) if timings else None,
        "p95_latency_ms": sorted(timings)[
            max(0, int(0.95 * len(timings) + 0.999999) - 1)
        ]
        if timings
        else None,
        "per_node": {
            node: {
                "calls": len(values),
                "mean_duration_ms": statistics.mean(values),
                "median_duration_ms": statistics.median(values),
                "mean_tokens": statistics.mean(node_tokens[node]),
            }
            for node, values in sorted(node_times.items())
        },
        "result_csv": str(output),
        "e1_comparison": {
            "file": str(e1_path),
            "matched_questions": len(paired),
            "baseline_success_rate": len(baseline_successes) / len(paired)
            if paired
            else None,
            "workflow_task_completion_rate": sum(
                bool(row["task_completed"]) for row in paired
            )
            / len(paired)
            if paired
            else None,
            "baseline_median_latency_ms": statistics.median(baseline_latencies)
            if baseline_latencies
            else None,
            "workflow_median_latency_ms": statistics.median(
                float(row["latency_ms"]) for row in paired
            )
            if paired
            else None,
        },
        "limit": limit,
        "slice_filter": slice_filter,
    }
    summary_path = output.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--store", type=Path, default=DEFAULT_W3_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--e1", type=Path, default=DEFAULT_E1)
    parser.add_argument(
        "--slice",
        choices=["single_hop", "multi_part", "unanswerable", "conflicting_documents"],
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N questions (pilot; not a full-set result).",
    )
    args = parser.parse_args()
    run(args.dataset, args.store, args.output, args.limit, args.e1, args.slice)


if __name__ == "__main__":
    main()
