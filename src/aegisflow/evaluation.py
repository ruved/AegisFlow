"""Dataset validation, direct RAG evaluation, metrics, and CSV reporting."""

import argparse
import csv
import json
import math
import statistics
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aegisflow.rag.generation import DetailedAnswerResult, generate_answer_with_details
from aegisflow.rag.retrieval import DEFAULT_STORE_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "eval" / "golden_v0.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results" / "baseline_E0.csv"
DEFAULT_RUNS = 3
DEFAULT_K = 3

CSV_FIELDS = [
    "question_id",
    "question",
    "answer",
    "gold_sources",
    "gold_source_details",
    "retrieved_sources",
    "retrieved_chunks",
    "latency_ms_median",
    "representative_run",
    "representative_latency_ms",
    "run_count",
    "attempted_runs",
    "failed_runs",
    "run_failures",
    "run_latencies_ms",
    "recall_at_k",
    "gold_key_facts",
    "key_facts_covered",
    "correctness_grade",
    "correctness_notes",
    "prompt_tokens",
    "completion_tokens",
]


class DatasetValidationError(ValueError):
    """The JSONL evaluation dataset is malformed or has duplicate IDs."""


@dataclass(frozen=True)
class GoldenCase:
    """Validated golden question, expected source filenames, and key facts."""

    id: str
    question: str
    gold_sources: tuple[str, ...]
    gold_key_facts: tuple[str, ...]
    gold_source_details: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class RunSuccess:
    """One successful full evaluation pass for a golden question."""

    run_number: int
    elapsed_ms: float
    result: DetailedAnswerResult


@dataclass(frozen=True)
class RunFailure:
    """One failed pass, preserving its category and diagnostic text."""

    run_number: int
    elapsed_ms: float
    error_type: str
    message: str


@dataclass(frozen=True)
class QuestionResult:
    """All attempted repetitions and the data selected for the CSV row."""

    case: GoldenCase
    successes: tuple[RunSuccess, ...]
    failures: tuple[RunFailure, ...]
    latency_median_ms: float | None
    recall_at_k: float | None
    representative: RunSuccess | None
    prompt_tokens: float | None
    completion_tokens: float | None


@dataclass(frozen=True)
class EvaluationSummary:
    """Aggregate metrics over the completed evaluation dataset."""

    question_count: int
    successful_questions: int
    failed_questions: int
    failed_runs: int
    recall_mean: float | None
    recall_excluded_questions: int
    latency_median_ms: float | None
    latency_p95_ms: float | None
    prompt_tokens_mean: float | None
    completion_tokens_mean: float | None
    manually_graded_answers: int
    correctness_grade_mean: float | None


def normalize_source_path(source: str) -> str:
    """Normalize separators and dot segments without dropping directories."""
    normalized = unicodedata.normalize("NFC", source.strip().replace("\\", "/"))
    path = PurePosixPath(normalized)
    return path.as_posix()


def load_golden_dataset(path: str | Path) -> list[GoldenCase]:
    """Load and validate JSONL records, reporting all discovered issues."""
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise DatasetValidationError(f"Dataset file not found: {dataset_path}")

    cases: list[GoldenCase] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            errors.append(f"line {line_number}: blank JSONL record")
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: malformed JSON ({exc.msg})")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number}: record must be a JSON object")
            continue

        record_id = record.get("id")
        question = record.get("question")
        raw_sources = record.get("gold_sources")
        raw_facts = record.get("gold_key_facts")
        if not isinstance(record_id, str) or not record_id.strip():
            errors.append(f"line {line_number}: missing or invalid id")
            continue
        record_id = record_id.strip()
        if record_id in seen_ids:
            errors.append(f"line {line_number}: duplicate id {record_id!r}")
        seen_ids.add(record_id)

        valid = True
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{record_id}: missing or invalid question")
            valid = False
        if not isinstance(raw_sources, list):
            errors.append(f"{record_id}: gold_sources must be a list")
            valid = False
        if (
            not isinstance(raw_facts, list)
            or not raw_facts
            or any(not isinstance(fact, str) or not fact.strip() for fact in raw_facts)
        ):
            errors.append(
                f"{record_id}: gold_key_facts must be a list of non-empty strings"
            )
            valid = False

        sources: list[str] = []
        source_details: list[tuple[str, str | None]] = []
        if isinstance(raw_sources, list):
            for source_index, source in enumerate(raw_sources, start=1):
                if isinstance(source, str) and source.strip():
                    normalized = normalize_source_path(source)
                    sources.append(normalized)
                    source_details.append((normalized, None))
                elif isinstance(source, dict):
                    doc = source.get("doc")
                    section = source.get("section")
                    if (
                        isinstance(doc, str)
                        and doc.strip()
                        and isinstance(section, str)
                        and section.strip()
                    ):
                        normalized = normalize_source_path(doc)
                        sources.append(normalized)
                        source_details.append((normalized, section.strip()))
                    else:
                        errors.append(
                            f"{record_id}: gold_sources[{source_index}] needs "
                            "non-empty doc and section"
                        )
                        valid = False
                else:
                    errors.append(
                        f"{record_id}: gold_sources[{source_index}] must be a "
                        "filename or doc/section object"
                    )
                    valid = False

        if valid and isinstance(question, str) and isinstance(raw_facts, list):
            cases.append(
                GoldenCase(
                    id=record_id,
                    question=question.strip(),
                    gold_sources=tuple(dict.fromkeys(sources)),
                    gold_key_facts=tuple(fact.strip() for fact in raw_facts),
                    gold_source_details=tuple(dict.fromkeys(source_details)),
                )
            )

    if errors:
        raise DatasetValidationError("Invalid golden dataset:\n" + "\n".join(errors))
    if not cases:
        raise DatasetValidationError("Invalid golden dataset: no questions found")
    return sorted(cases, key=lambda case: case.id)


def recall_at_k(
    gold_sources: tuple[str, ...] | list[str],
    ranked_sources: tuple[str, ...] | list[str],
    k: int,
) -> float | None:
    """Compute source-level Recall@k; return None when there are no gold files."""
    if k <= 0:
        raise ValueError("k must be positive")
    gold = {normalize_source_path(source) for source in gold_sources}
    if not gold:
        return None
    retrieved = {normalize_source_path(source) for source in ranked_sources[:k]}
    return len(gold & retrieved) / len(gold)


def evaluate_cases(
    cases: list[GoldenCase],
    runs: int = DEFAULT_RUNS,
    k: int = DEFAULT_K,
    store_path: str | Path = DEFAULT_STORE_PATH,
    evaluator: Callable[..., DetailedAnswerResult] = generate_answer_with_details,
) -> list[QuestionResult]:
    """Run each question repeatedly through the production RAG service path."""
    if runs <= 0:
        raise ValueError("runs must be positive")
    if k <= 0:
        raise ValueError("k must be positive")

    evaluated: list[QuestionResult] = []
    for case in sorted(cases, key=lambda item: item.id):
        successes: list[RunSuccess] = []
        failures: list[RunFailure] = []
        for run_number in range(1, runs + 1):
            started = time.perf_counter()
            try:
                result = evaluator(case.question, k=k, store_path=store_path)
                elapsed_ms = (time.perf_counter() - started) * 1000
                successes.append(RunSuccess(run_number, elapsed_ms, result))
            except Exception as exc:  # Keep later golden cases evaluable.
                failures.append(
                    RunFailure(
                        run_number,
                        (time.perf_counter() - started) * 1000,
                        type(exc).__name__,
                        str(exc),
                    )
                )

        representative = successes[-1] if successes else None
        retrieved_sources = (
            [
                str(chunk["source"])
                for chunk in representative.result["retrieved_chunks"]
                if isinstance(chunk.get("source"), str)
            ]
            if representative
            else []
        )
        prompt_counts = [
            success.result["prompt_tokens"]
            for success in successes
            if success.result["prompt_tokens"] is not None
        ]
        completion_counts = [
            success.result["completion_tokens"]
            for success in successes
            if success.result["completion_tokens"] is not None
        ]
        evaluated.append(
            QuestionResult(
                case=case,
                successes=tuple(successes),
                failures=tuple(failures),
                latency_median_ms=(
                    statistics.median(success.elapsed_ms for success in successes)
                    if successes
                    else None
                ),
                recall_at_k=recall_at_k(case.gold_sources, retrieved_sources, k),
                representative=representative,
                prompt_tokens=(
                    statistics.median(prompt_counts) if prompt_counts else None
                ),
                completion_tokens=(
                    statistics.median(completion_counts) if completion_counts else None
                ),
            )
        )
    return evaluated


def result_to_csv_row(result: QuestionResult, runs: int) -> dict[str, object]:
    """Serialize a full question result without truncating evidence or answers."""
    representative = result.representative
    chunks = representative.result["retrieved_chunks"] if representative else []
    retrieved_sources = list(
        dict.fromkeys(
            str(chunk["source"])
            for chunk in chunks
            if isinstance(chunk.get("source"), str)
        )
    )
    return {
        "question_id": result.case.id,
        "question": result.case.question,
        "answer": representative.result["answer"] if representative else "",
        "gold_sources": json.dumps(result.case.gold_sources, ensure_ascii=False),
        "gold_source_details": json.dumps(
            [
                {"doc": doc, "section": section}
                for doc, section in result.case.gold_source_details
            ],
            ensure_ascii=False,
        ),
        "retrieved_sources": json.dumps(retrieved_sources, ensure_ascii=False),
        "retrieved_chunks": json.dumps(chunks, ensure_ascii=False),
        "latency_ms_median": _csv_number(result.latency_median_ms),
        "representative_run": representative.run_number if representative else "",
        "representative_latency_ms": (
            _csv_number(representative.elapsed_ms) if representative else ""
        ),
        "run_count": len(result.successes),
        "attempted_runs": runs,
        "failed_runs": len(result.failures),
        "run_failures": json.dumps(
            [failure.__dict__ for failure in result.failures], ensure_ascii=False
        ),
        "run_latencies_ms": json.dumps(
            [
                {
                    "run": success.run_number,
                    "success": True,
                    "elapsed_ms": success.elapsed_ms,
                }
                for success in result.successes
            ]
            + [
                {
                    "run": failure.run_number,
                    "success": False,
                    "elapsed_ms": failure.elapsed_ms,
                }
                for failure in result.failures
            ],
            ensure_ascii=False,
        ),
        "recall_at_k": _csv_number(result.recall_at_k),
        "gold_key_facts": json.dumps(result.case.gold_key_facts, ensure_ascii=False),
        "key_facts_covered": "",
        "correctness_grade": "",
        "correctness_notes": "",
        "prompt_tokens": result.prompt_tokens
        if result.prompt_tokens is not None
        else "",
        "completion_tokens": (
            result.completion_tokens if result.completion_tokens is not None else ""
        ),
    }


def write_results_csv(
    results: list[QuestionResult], path: str | Path, runs: int
) -> None:
    """Write one stable, standards-compliant CSV row per golden question."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manual_grades = read_manual_grades(output)
    with output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        for result in sorted(results, key=lambda item: item.case.id):
            row = result_to_csv_row(result, runs)
            row.update(manual_grades.get(result.case.id, {}))
            writer.writerow(row)


def read_manual_grades(path: str | Path) -> dict[str, dict[str, str]]:
    """Load existing manual grading fields so reruns retain human review."""
    manual_grades: dict[str, dict[str, str]] = {}
    grade_file = Path(path)
    if not grade_file.is_file():
        return manual_grades
    with grade_file.open(encoding="utf-8", newline="") as existing_file:
        for previous in csv.DictReader(existing_file):
            question_id = previous.get("question_id")
            if question_id:
                manual_grades[question_id] = {
                    field: previous.get(field, "") or ""
                    for field in (
                        "key_facts_covered",
                        "correctness_grade",
                        "correctness_notes",
                    )
                }
    return manual_grades


def summarize_results(
    results: list[QuestionResult],
    manual_grades: dict[str, dict[str, str]] | None = None,
) -> EvaluationSummary:
    """Calculate reported aggregate metrics from per-question outcomes."""
    successful = [result for result in results if result.successes]
    latencies = [
        result.latency_median_ms
        for result in successful
        if result.latency_median_ms is not None
    ]
    recalls = [
        result.recall_at_k for result in results if result.recall_at_k is not None
    ]
    prompt_counts = [
        result.prompt_tokens
        for result in successful
        if result.prompt_tokens is not None
    ]
    completion_counts = [
        result.completion_tokens
        for result in successful
        if result.completion_tokens is not None
    ]
    grade_values: list[int] = []
    if manual_grades is not None:
        for result in results:
            grade = manual_grades.get(result.case.id, {}).get("correctness_grade", "")
            if grade in {"0", "1", "2", "3", "4", "5"}:
                grade_values.append(int(grade))
    return EvaluationSummary(
        question_count=len(results),
        successful_questions=len(successful),
        failed_questions=len(results) - len(successful),
        failed_runs=sum(len(result.failures) for result in results),
        recall_mean=statistics.mean(recalls) if recalls else None,
        recall_excluded_questions=sum(result.recall_at_k is None for result in results),
        latency_median_ms=statistics.median(latencies) if latencies else None,
        latency_p95_ms=(_percentile_95(latencies) if len(latencies) >= 20 else None),
        prompt_tokens_mean=(statistics.mean(prompt_counts) if prompt_counts else None),
        completion_tokens_mean=(
            statistics.mean(completion_counts) if completion_counts else None
        ),
        manually_graded_answers=len(grade_values),
        correctness_grade_mean=(
            statistics.mean(grade_values) if grade_values else None
        ),
    )


def _percentile_95(values: list[float]) -> float:
    """Nearest-rank 95th percentile, used only with >=20 observations."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _csv_number(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def print_summary(summary: EvaluationSummary, k: int, output_path: Path) -> None:
    """Print aggregate results without implying unmeasured values."""
    print(f"Golden questions: {summary.question_count}")
    print(f"Successfully evaluated: {summary.successful_questions}")
    print(f"Failed questions: {summary.failed_questions}")
    print(f"Failed runs: {summary.failed_runs}")
    print(
        f"Mean source Recall@{k}: "
        f"{_display(summary.recall_mean)} "
        f"(excluded {summary.recall_excluded_questions} with no gold sources)"
    )
    print(
        "Median of per-question median latency: "
        f"{_display(summary.latency_median_ms)} ms"
    )
    print(f"P95 of per-question median latency: {_display(summary.latency_p95_ms)} ms")
    print(f"Average prompt tokens: {_display(summary.prompt_tokens_mean)}")
    print(f"Average completion tokens: {_display(summary.completion_tokens_mean)}")
    print(f"Manually graded answers: {summary.manually_graded_answers}")
    print(f"Mean manual correctness grade: {_display(summary.correctness_grade_mean)}")
    print(f"CSV: {output_path}")


def _display(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.3f}"


def main() -> None:
    """Run the local baseline evaluation CLI."""
    parser = argparse.ArgumentParser(
        description="Evaluate the local AegisFlow RAG pipeline against JSONL gold data."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    args = parser.parse_args()

    if args.runs <= 0 or args.k <= 0:
        parser.error("--runs and --k must be positive integers")
    try:
        cases = load_golden_dataset(args.dataset)
    except (DatasetValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    manual_grades = read_manual_grades(args.output)
    results = evaluate_cases(cases, runs=args.runs, k=args.k, store_path=args.store)
    write_results_csv(results, args.output, args.runs)
    summary = summarize_results(results, manual_grades)
    print_summary(summary, args.k, args.output)
    if summary.failed_runs:
        for result in results:
            for failure in result.failures:
                print(
                    f"Failed {result.case.id} run {failure.run_number}: "
                    f"{failure.error_type}: {failure.message}",
                    file=sys.stderr,
                )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
