"""Tests for the CI Quality and Evaluation Gate."""

from evals.ci_eval_gate import DEFAULT_FIXTURES, evaluate_case, run_gate


def test_evaluate_case_perfect_hit() -> None:
    gold = [["runbooks/RB-001.md", "4. Diagnosis"]]
    retrieved = [
        {"source": "runbooks/RB-001.md", "heading": "4. Diagnosis"},
        {"source": "other.md", "heading": "Intro"},
    ]
    recall, mrr = evaluate_case(gold, retrieved, k=3)
    assert recall == 1.0
    assert mrr == 1.0  # Hit at rank 1


def test_evaluate_case_miss() -> None:
    gold = [["runbooks/RB-001.md", "4. Diagnosis"]]
    retrieved = [{"source": "wrong.md", "heading": "Intro"}]
    recall, mrr = evaluate_case(gold, retrieved, k=3)
    assert recall == 0.0
    assert mrr == 0.0


def test_ci_eval_gate_passes_on_fixtures() -> None:
    passed, details = run_gate(
        fixtures_path=DEFAULT_FIXTURES,
        baseline_recall=0.70,
        baseline_mrr=0.60,
        tolerance=0.05,
    )
    assert passed is True
    assert details["measured_recall"] >= details["min_recall_threshold"]
    assert details["measured_mrr"] >= details["min_mrr_threshold"]


def test_ci_eval_gate_fails_on_simulated_regression() -> None:
    passed, details = run_gate(
        fixtures_path=DEFAULT_FIXTURES,
        baseline_recall=0.70,
        baseline_mrr=0.60,
        tolerance=0.05,
        simulate_regression=True,
    )
    assert passed is False
    assert details["measured_recall"] < details["min_recall_threshold"]
