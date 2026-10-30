"""Measure planner schema validity on a deterministic 15-question sample."""

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from aegisflow.config import CHAT_MODEL
from aegisflow.evaluation import DEFAULT_DATASET_PATH, load_golden_dataset
from aegisflow.workflow.models import call_structured
from aegisflow.workflow.planning import PLANNER_SYSTEM, normalize_plan, planner_prompt
from aegisflow.workflow.schemas import PlannerOutput

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results" / "W4_planner_validity.csv"


def run(dataset: Path, output: Path, model: str) -> dict[str, Any]:
    cases = load_golden_dataset(dataset)
    singles = [case for case in cases if case.slice == "single_hop"][:10]
    multi = [case for case in cases if case.slice == "multi_part"][:5]
    sample = singles + multi
    rows: list[dict[str, Any]] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(sample, start=1):
        started = time.perf_counter()
        try:
            call = call_structured(
                model=model,
                system=PLANNER_SYSTEM,
                user=planner_prompt(case.question),
                schema=PlannerOutput,
                remaining_tokens=1200,
            )
            plan = call.value
            if not isinstance(plan, PlannerOutput):
                raise TypeError("Planner returned an unexpected schema")
            normalized = normalize_plan(plan, case.question)
            rows.append(
                {
                    "question_id": case.id,
                    "slice": case.slice,
                    "valid": True,
                    "direct": plan.direct,
                    "subquestion_count": len(normalized),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "prompt_tokens": call.prompt_tokens,
                    "completion_tokens": call.completion_tokens,
                    "tokens_estimated": call.tokens_estimated,
                    "subquestions": json.dumps(normalized, ensure_ascii=False),
                    "error": "",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "question_id": case.id,
                    "slice": case.slice,
                    "valid": False,
                    "direct": "",
                    "subquestion_count": 0,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "tokens_estimated": "",
                    "subquestions": "[]",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(
            f"[{index}/{len(sample)}] {case.id}: valid={rows[-1]['valid']}", flush=True
        )

    valid_rows = [row for row in rows if row["valid"]]
    summary = {
        "dataset": str(dataset),
        "model": model,
        "sample_size": len(sample),
        "single_hop_count": len(singles),
        "multi_part_count": len(multi),
        "valid_count": len(valid_rows),
        "invalid_count": len(rows) - len(valid_rows),
        "schema_valid_rate": len(valid_rows) / len(rows) if rows else None,
        "mean_latency_ms": sum(float(row["latency_ms"]) for row in rows) / len(rows)
        if rows
        else None,
        "result_csv": str(output),
    }
    output.with_suffix(".json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=CHAT_MODEL)
    args = parser.parse_args()
    run(args.dataset, args.output, args.model)


if __name__ == "__main__":
    main()
