import json
import sys

import pytest

from aegisflow import retrieval_evaluation
from aegisflow.evaluation import GoldenCase, load_golden_dataset
from aegisflow.retrieval_evaluation import (
    RetrievalCaseResult,
    SectionMetrics,
    markdown_section_spans,
    print_retrieval_report,
    score_section_ranking,
    section_hits_for_chunks,
)


def test_golden_loader_keeps_slice_and_difficulty_for_reporting(tmp_path):
    dataset = tmp_path / "gold.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "G1",
                "question": "What failed?",
                "slice": "single_hop",
                "difficulty": "easy",
                "gold_sources": [{"doc": "runbook.md", "section": "2. Diagnosis"}],
                "gold_key_facts": ["pool exhausted"],
            }
        ),
        encoding="utf-8",
    )

    case = load_golden_dataset(dataset)[0]

    assert case.slice == "single_hop"
    assert case.difficulty == "easy"
    assert case.gold_sections == (("runbook.md", "2. Diagnosis"),)


def test_markdown_sections_end_at_the_next_heading():
    source = (
        "# Guide\n"
        "intro\n"
        "## 2. Diagnosis\n"
        "look at the pool\n"
        "## 3. Fix\n"
        "restore capacity\n"
    )
    spans = markdown_section_spans(source)

    assert [span.heading for span in spans] == ["Guide", "2. Diagnosis", "3. Fix"]
    assert spans[1].end == spans[2].start


def test_chunk_spanning_two_gold_sections_maps_to_both(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = (
        "## 2. Diagnosis\nPool saturation was caused by slow queries.\n"
        "## 3. Mitigation\nDisable the affected query path.\n"
    )
    (corpus / "runbook.md").write_text(source, encoding="utf-8")
    gold = {("runbook.md", "2. Diagnosis"), ("runbook.md", "3. Mitigation")}
    retrieved = [
        {
            "chunk_id": "runbook.md::chunk-0",
            "source": "runbook.md",
            "text": source.strip(),
        }
    ]

    mapped = section_hits_for_chunks(gold, retrieved, corpus)

    assert mapped == [gold]


def test_section_metrics_report_recall_mrr_and_ndcg_at_k():
    gold = {("a.md", "1. First"), ("a.md", "2. Second")}
    ranked_sections = [
        set(),
        {("a.md", "1. First")},
        {("a.md", "1. First")},
        {("a.md", "2. Second")},
    ]

    metrics = score_section_ranking(gold, ranked_sections, k=3)

    assert metrics.gold_section_count == 2
    assert metrics.hit_section_count == 1
    assert metrics.recall_at_k == 0.5
    assert metrics.mrr == 0.5
    expected_ndcg = (1 / 1.584962500721156) / (1 + 1 / 1.584962500721156)
    assert metrics.ndcg_at_k == pytest.approx(expected_ndcg)


def test_unanswerable_cases_are_excluded_from_metric_means_and_table(capsys):
    answerable = GoldenCase(
        "G1",
        "Question?",
        ("runbook.md",),
        ("fact",),
        (("runbook.md", "2. Diagnosis"),),
        slice="single_hop",
        difficulty="easy",
    )
    unanswerable = GoldenCase(
        "G2", "Unknown?", (), ("not in corpus",), slice="unanswerable"
    )
    populated = SectionMetrics(1, 1, 1.0, 1.0, 1.0)
    excluded = SectionMetrics(0, 0, None, None, None)
    results = [
        RetrievalCaseResult(
            answerable,
            {"dense": populated, "lexical": populated, "fused": populated},
        ),
        RetrievalCaseResult(
            unanswerable,
            {"dense": excluded, "lexical": excluded, "fused": excluded},
        ),
    ]

    print_retrieval_report(results, k=3)
    output = capsys.readouterr().out

    assert "Retriever" in output and "Recall@3" in output and "nDCG@3" in output
    assert "single_hop" in output and "unanswerable" in output
    assert "dense" in output and "lexical" in output and "fused" in output
    assert "Questions" in output and "Answerable" in output


def test_eval_retrieval_command_prints_dense_lexical_and_fused_rows(
    monkeypatch, tmp_path, capsys
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "runbook.md").write_text(
        "## 2. Diagnosis\nPool saturation caused checkout failures.\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "gold.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "G1",
                "question": "Why did checkout fail?",
                "slice": "single_hop",
                "difficulty": "easy",
                "gold_sources": [{"doc": "runbook.md", "section": "2. Diagnosis"}],
                "gold_key_facts": ["pool saturation"],
            }
        ),
        encoding="utf-8",
    )

    async def ranked_lists(query, k, store_path):
        chunk = {
            "chunk_id": "runbook::0",
            "source": "runbook.md",
            "text": "Pool saturation caused checkout failures.",
        }
        return [chunk], [chunk]

    monkeypatch.setattr(retrieval_evaluation, "retrieve_ranked_lists", ranked_lists)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval-retrieval",
            "--dataset",
            str(dataset),
            "--corpus",
            str(corpus),
            "--store",
            str(tmp_path / "store"),
            "--k",
            "1",
        ],
    )

    retrieval_evaluation.main()

    output = capsys.readouterr().out
    assert "dense" in output and "lexical" in output and "fused" in output
    assert "single_hop" in output and "Recall@1" in output
