import csv
import json

import pytest

from aegisflow import retrieval_experiment
from aegisflow.evaluation import GoldenCase


def test_experiment_compares_two_candidate_limits_and_writes_per_question_outcome(
    monkeypatch, tmp_path
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "runbook.md").write_text(
        "## 1. Saturation\nPool saturated.\n## 2. Recovery\nRestore capacity.\n",
        encoding="utf-8",
    )
    dense_results = [
        {"chunk_id": "a", "source": "runbook.md", "text": "Pool saturated."},
        {"chunk_id": "noise", "source": "other.md", "text": "Unrelated."},
    ]
    lexical_results = [
        {"chunk_id": "b", "source": "runbook.md", "text": "Restore capacity."},
        {"chunk_id": "a", "source": "runbook.md", "text": "Pool saturated."},
    ]

    monkeypatch.setattr(
        retrieval_experiment, "retrieve_chunks", lambda *args: dense_results
    )
    monkeypatch.setattr(
        retrieval_experiment, "retrieve_lexical_chunks", lambda *args: lexical_results
    )
    case = GoldenCase(
        "G1",
        "How recover?",
        ("runbook.md",),
        ("pool",),
        (
            ("runbook.md", "1. Saturation"),
            ("runbook.md", "2. Recovery"),
        ),
        slice="multi_part",
    )

    results = retrieval_experiment.evaluate_experiment(
        [case], ks=(1, 2), store_path=tmp_path / "store", corpus_dir=corpus
    )
    candidates = results[0].candidates

    assert [candidate.k for candidate in candidates] == [1, 2]
    assert candidates[0].fused_vs_dense == "tie"
    assert candidates[1].fused_vs_dense == "win"
    assert candidates[1].metrics["fused"].recall_at_k == 1.0
    assert candidates[1].metrics["dense"].recall_at_k == 0.5

    output = tmp_path / "E1.csv"
    retrieval_experiment.write_experiment_csv(results, output)
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["fused_vs_dense"] for row in rows] == ["tie", "win"]
    assert json.loads(rows[1]["fused_hit_sections"]) == [
        {"doc": "runbook.md", "section": "1. Saturation"},
        {"doc": "runbook.md", "section": "2. Recovery"},
    ]


def test_experiment_rejects_more_than_three_candidate_settings():
    with pytest.raises(ValueError, match="one to three"):
        retrieval_experiment.evaluate_experiment([], ks=(1, 2, 3, 4))
