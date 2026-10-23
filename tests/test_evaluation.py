"""Deterministic unit tests for the golden evaluation utilities."""

import csv
import json
from dataclasses import replace

import pytest

from aegisflow.evaluation import (
    CSV_FIELDS,
    DatasetValidationError,
    GoldenCase,
    QuestionResult,
    RunSuccess,
    evaluate_cases,
    load_golden_dataset,
    normalize_source_path,
    recall_at_k,
    result_to_csv_row,
    summarize_results,
    write_results_csv,
)


def test_load_dataset_preserves_current_gold_schema_and_sorts_ids(tmp_path):
    dataset = tmp_path / "gold.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "G002",
                        "question": "Second?",
                        "gold_sources": [
                            {"doc": "runbooks\\pool.md", "section": "4. Diagnosis"}
                        ],
                        "gold_key_facts": ["fact"],
                    }
                ),
                json.dumps(
                    {
                        "id": "G001",
                        "question": "First?",
                        "gold_sources": ["architecture.md"],
                        "gold_key_facts": ["fact"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_golden_dataset(dataset)

    assert [case.id for case in cases] == ["G001", "G002"]
    assert cases[1].gold_sources == ("runbooks/pool.md",)
    assert cases[1].gold_source_details == (("runbooks/pool.md", "4. Diagnosis"),)


@pytest.mark.parametrize(
    "contents, expected",
    [
        ('{"id":"x","question":"q","gold_sources":[],"gold_key_facts":["fact"]}', ""),
        (
            '{"id":"x","question":"q","gold_sources":[],"gold_key_facts":[]}\n'
            '{"id":"x","question":"q","gold_sources":[],"gold_key_facts":[]}',
            "duplicate id",
        ),
        ("not json", "malformed JSON"),
        ('{"id":"x","question":" ","gold_sources":[],"gold_key_facts":[]}', "question"),
    ],
)
def test_dataset_validation_errors_are_clear(tmp_path, contents, expected):
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text(contents, encoding="utf-8")

    if expected:
        with pytest.raises(DatasetValidationError, match=expected):
            load_golden_dataset(dataset)
    else:
        assert load_golden_dataset(dataset)[0].id == "x"


def test_source_normalization_and_recall_deduplicate_without_basename_collapse():
    assert normalize_source_path("./runbooks\\RB-1.md") == "runbooks/RB-1.md"
    assert recall_at_k(
        ["runbooks/RB-1.md", "postmortems/RB-1.md", "runbooks/RB-1.md"],
        ["runbooks\\RB-1.md", "runbooks/RB-1.md", "elsewhere.md"],
        3,
    ) == pytest.approx(0.5)


def test_empty_gold_sources_are_excluded_and_k_must_be_positive():
    assert recall_at_k([], ["a.md"], 3) is None
    with pytest.raises(ValueError, match="positive"):
        recall_at_k(["a.md"], [], 0)


def test_evaluation_uses_monotonic_elapsed_and_keeps_failed_attempts(monkeypatch):
    case = GoldenCase("G1", "Question?", ("a.md",), ("fact",))
    elapsed = iter([0.0, 0.010, 1.0, 1.030, 2.0, 2.020])
    monkeypatch.setattr("aegisflow.evaluation.time.perf_counter", lambda: next(elapsed))
    calls = 0

    def evaluator(question, k, store_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated failure")
        return {
            "answer": "Supported answer",
            "sources": ["a.md"],
            "retrieved_chunks": [
                {
                    "chunk_id": "a::0",
                    "source": "a.md",
                    "text": "evidence",
                    "distance": 0.1,
                }
            ],
            "prompt_tokens": None,
            "completion_tokens": None,
        }

    results = evaluate_cases([case], runs=3, k=1, evaluator=evaluator)

    assert len(results[0].successes) == 2
    assert len(results[0].failures) == 1
    assert results[0].latency_median_ms == pytest.approx(15.0)
    assert results[0].recall_at_k == 1.0
    assert results[0].representative is not None
    assert results[0].representative.run_number == 3


def test_csv_quotes_full_content_and_leaves_manual_grading_and_usage_blank(tmp_path):
    case = GoldenCase("G1", 'Question, "quoted"?', ("a.md",), ("fact",))
    result = QuestionResult(
        case=case,
        successes=(
            RunSuccess(
                3,
                123.456,
                {
                    "answer": 'line one, "quoted"\nline two',
                    "sources": ["a.md"],
                    "retrieved_chunks": [
                        {
                            "chunk_id": "a::0",
                            "source": "a.md",
                            "text": "full\nchunk",
                            "distance": 0.2,
                        }
                    ],
                    "prompt_tokens": None,
                    "completion_tokens": None,
                },
            ),
        ),
        failures=(),
        latency_median_ms=123.456,
        recall_at_k=1.0,
        representative=None,
        prompt_tokens=None,
        completion_tokens=None,
    )
    # No successful representative means no answer/evidence is claimed.
    row = result_to_csv_row(result, runs=3)
    assert row["correctness_grade"] == ""
    assert row["correctness_notes"] == ""
    assert row["key_facts_covered"] == ""
    assert row["prompt_tokens"] == ""
    assert row["completion_tokens"] == ""

    successful = QuestionResult(
        **{
            **result.__dict__,
            "representative": result.successes[0],
        }
    )
    output = tmp_path / "results" / "baseline.csv"
    write_results_csv([successful], output, runs=3)
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == CSV_FIELDS
    assert rows[0]["answer"] == 'line one, "quoted"\nline two'
    assert json.loads(rows[0]["retrieved_chunks"])[0]["text"] == "full\nchunk"
    assert rows[0]["correctness_grade"] == ""
    assert rows[0]["prompt_tokens"] == ""

    rows[0]["correctness_grade"] = "4"
    rows[0]["correctness_notes"] = "Reviewed against evidence"
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    second_case = replace(successful, case=replace(case, id="G0"))
    write_results_csv([successful, second_case], output, runs=3)
    with output.open(encoding="utf-8", newline="") as stream:
        rerun_rows = list(csv.DictReader(stream))
    assert [row["question_id"] for row in rerun_rows] == ["G0", "G1"]
    assert rerun_rows[1]["correctness_grade"] == "4"
    assert rerun_rows[1]["correctness_notes"] == "Reviewed against evidence"


def test_summary_metrics_exclude_unanswerable_from_recall_denominator():
    cases = [
        GoldenCase("G1", "q1", ("a.md",), ("fact",)),
        GoldenCase("G2", "q2", (), ("fact",)),
    ]
    successful_result = {
        "answer": "ok",
        "sources": ["a.md"],
        "retrieved_chunks": [
            {"chunk_id": "a", "source": "a.md", "text": "x", "distance": 0.1}
        ],
        "prompt_tokens": 10,
        "completion_tokens": 3,
    }

    results = evaluate_cases(
        cases,
        runs=1,
        k=1,
        evaluator=lambda question, k, store_path: successful_result,
    )
    summary = summarize_results(results)

    assert summary.question_count == 2
    assert summary.successful_questions == 2
    assert summary.recall_mean == 1.0
    assert summary.recall_excluded_questions == 1
    assert summary.prompt_tokens_mean == 10
    assert summary.completion_tokens_mean == 3
    assert summary.manually_graded_answers == 0
    assert summary.correctness_grade_mean is None
    graded_summary = summarize_results(
        results,
        {
            "G1": {"correctness_grade": "4"},
            "G2": {"correctness_grade": "invalid"},
        },
    )
    assert graded_summary.manually_graded_answers == 1
    assert graded_summary.correctness_grade_mean == 4.0
    two_question_summary = summarize_results(
        [
            replace(results[0], latency_median_ms=10.0),
            replace(results[1], latency_median_ms=30.0),
        ]
    )
    assert two_question_summary.latency_median_ms == 20.0
    assert two_question_summary.latency_p95_ms is None

    twenty_question_results = [
        replace(
            results[0],
            case=replace(cases[0], id=f"G{index:02d}"),
            latency_median_ms=float(index),
        )
        for index in range(1, 21)
    ]
    twenty_question_summary = summarize_results(twenty_question_results)
    assert twenty_question_summary.latency_median_ms == 10.5
    assert twenty_question_summary.latency_p95_ms == 19.0
