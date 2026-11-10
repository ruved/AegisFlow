"""Tests for context builder token budgeting, deduplication, and diversity (E5)."""

from aegisflow.rag.context_builder import ContextBuilder


def test_context_builder_deduplication() -> None:
    builder = ContextBuilder(max_subquestion_tokens=1000, max_total_tokens=2000)

    subq_results = [
        (
            "subq 1",
            [
                {"chunk_id": "c1", "source": "docA.md", "heading": "Sec1", "text": "Unique text 1"},
                {"chunk_id": "c2", "source": "docB.md", "heading": "Sec1", "text": "Unique text 2"},
            ],
        ),
        (
            "subq 2",
            [
                {"chunk_id": "c1", "source": "docA.md", "heading": "Sec1", "text": "Unique text 1"},  # duplicate id & text
                {"chunk_id": "c3", "source": "docC.md", "heading": "Sec1", "text": "Unique text 3"},
            ],
        ),
    ]

    res = builder.build_context(subq_results)

    selected_ids = [c["chunk_id"] for c in res.selected_chunks]
    assert selected_ids == ["c1", "c2", "c3"]
    assert len(res.excluded_chunks) == 1
    assert res.excluded_chunks[0].chunk_id == "c1"
    assert res.excluded_chunks[0].reason == "duplicate"


def test_context_builder_subquestion_budget_cap() -> None:
    # 50 tokens max per subquestion (~200 chars)
    builder = ContextBuilder(max_subquestion_tokens=50, max_total_tokens=2000)

    long_text = "This is a detailed sentence. " * 15  # ~435 chars => ~108 tokens
    short_text = "Short text."  # ~11 chars => ~3 tokens

    subq_results = [
        (
            "subq 1",
            [
                {
                    "chunk_id": "c1",
                    "source": "docA.md",
                    "heading": "Sec1",
                    "text": short_text,
                },
                {
                    "chunk_id": "c2",
                    "source": "docB.md",
                    "heading": "Sec2",
                    "text": long_text,
                },
            ],
        ),
    ]

    res = builder.build_context(subq_results)

    assert len(res.selected_chunks) == 1
    assert res.selected_chunks[0]["chunk_id"] == "c1"
    assert len(res.excluded_chunks) == 1
    assert res.excluded_chunks[0].reason == "subquestion_budget_exceeded"


def test_context_builder_global_budget_cap() -> None:
    # 60 tokens total max (~240 chars)
    builder = ContextBuilder(max_subquestion_tokens=1000, max_total_tokens=60)

    med_text_1 = "Alpha beta gamma delta epsilon. " * 4  # ~128 chars => ~32 tokens
    med_text_2 = "One two three four five six seven. " * 4  # ~140 chars => ~35 tokens

    subq_results = [
        (
            "subq 1",
            [
                {
                    "chunk_id": "c1",
                    "source": "docA.md",
                    "heading": "Sec1",
                    "text": med_text_1,
                },
                {
                    "chunk_id": "c2",
                    "source": "docB.md",
                    "heading": "Sec2",
                    "text": med_text_2,
                },
            ],
        ),
    ]

    res = builder.build_context(subq_results)

    assert len(res.selected_chunks) == 1
    assert res.selected_chunks[0]["chunk_id"] == "c1"
    assert len(res.excluded_chunks) == 1
    assert res.excluded_chunks[0].reason == "global_budget_exceeded"


def test_context_builder_section_diversity() -> None:
    # Max 1 chunk per section
    builder = ContextBuilder(
        max_subquestion_tokens=1000,
        max_total_tokens=2000,
        max_chunks_per_section=1,
    )

    subq_results = [
        (
            "subq 1",
            [
                {
                    "chunk_id": "c1",
                    "source": "runbook.md",
                    "heading": "Diagnosis",
                    "text": "First passage",
                },
                {
                    "chunk_id": "c2",
                    "source": "runbook.md",
                    "heading": "Diagnosis",
                    "text": "Second passage",
                },
                {
                    "chunk_id": "c3",
                    "source": "runbook.md",
                    "heading": "Mitigation",
                    "text": "Third passage",
                },
            ],
        ),
    ]

    res = builder.build_context(subq_results)

    selected_ids = [c["chunk_id"] for c in res.selected_chunks]
    assert selected_ids == ["c1", "c3"]
    assert len(res.excluded_chunks) == 1
    assert res.excluded_chunks[0].chunk_id == "c2"
    assert res.excluded_chunks[0].reason == "redundant_section"
