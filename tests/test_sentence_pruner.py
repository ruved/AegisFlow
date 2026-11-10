"""Tests for sentence-level context pruning and identifier preservation (E6)."""

from aegisflow.rag.sentence_pruner import (
    contains_exact_identifiers,
    cosine_similarity,
    is_unsuitable_for_pruning,
    prune_chunk,
    split_into_sentences,
)


def test_split_into_sentences() -> None:
    text = "First sentence here. Second sentence with details! Third sentence? Yes."
    sents = split_into_sentences(text)
    assert len(sents) == 4
    assert sents[0] == "First sentence here."
    assert sents[1] == "Second sentence with details!"
    assert sents[2] == "Third sentence?"
    assert sents[3] == "Yes."


def test_is_unsuitable_for_pruning() -> None:
    assert is_unsuitable_for_pruning("some text", source="logs/incident.log.md")
    assert is_unsuitable_for_pruning(
        "```python\nprint('hello')\n```", source="runbook.md"
    )
    assert not is_unsuitable_for_pruning(
        "Normal prose describing an incident.", source="runbook.md"
    )


def test_contains_exact_identifiers() -> None:
    # Query mentions order-service and ERR-502
    query = "Why did order-service throw ERR-502 during checkout?"

    sent_hit = "At 14:02, order-service reported degraded database pool."
    sent_miss = "The weather was completely fine on Tuesday."

    assert contains_exact_identifiers(sent_hit, query)
    assert not contains_exact_identifiers(sent_miss, query)


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert 0.99 < cosine_similarity([1.0, 1.0], [2.0, 2.0]) <= 1.0


def test_prune_chunk_skips_short_text() -> None:
    short_text = "Short text under min tokens limit."
    res = prune_chunk(short_text, query="any query", min_tokens=100)
    assert res.skipped_reason == "too_short"
    assert res.compression_ratio == 1.0
    assert res.pruned_text == short_text
