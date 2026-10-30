import asyncio
import threading

import pytest

from aegisflow.rag import retrieval
from aegisflow.rag.chunking import ParentChunk, TextChunk
from aegisflow.rag.lexical_index import LexicalIndex
from aegisflow.rag.vector_store import VectorStore


def test_retrieve_chunks_ranks_relevant_document_first(tmp_path, monkeypatch):
    store = VectorStore(path=tmp_path / "test_db")
    chunks = [
        TextChunk(
            chunk_id="architecture::chunk-0",
            source="architecture.md",
            text="AegisFlow coordinates agent workflows.",
        ),
        TextChunk(
            chunk_id="ingestion::chunk-0",
            source="ingestion.md",
            text="Documents are split and embedded.",
        ),
    ]

    store.add_chunks(
        chunks,
        embeddings=[
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
    )

    monkeypatch.setattr(
        retrieval,
        "embed_texts",
        lambda texts: [[0.99, 0.01, 0.0]],
    )

    results = retrieval.retrieve_chunks(
        "How does AegisFlow work?",
        k=2,
        store_path=tmp_path / "test_db",
    )

    assert len(results) == 2
    assert results[0]["source"] == "architecture.md"


def test_retrieve_chunks_rejects_empty_query():
    with pytest.raises(ValueError, match="Query must not be empty"):
        retrieval.retrieve_chunks("   ")


def test_retrieve_chunks_rejects_non_positive_k():
    with pytest.raises(ValueError, match="k must be positive"):
        retrieval.retrieve_chunks("architecture", k=0)


def test_retrieve_chunks_returns_empty_for_empty_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        retrieval,
        "embed_texts",
        lambda texts: [[1.0, 0.0, 0.0]],
    )

    results = retrieval.retrieve_chunks(
        "architecture",
        store_path=tmp_path / "empty_db",
    )

    assert results == []


def test_reciprocal_rank_fusion_math_deduplicates_by_chunk_id():
    dense = [
        {"chunk_id": "a", "source": "a.md", "distance": 0.1},
        {"chunk_id": "b", "source": "b.md", "distance": 0.2},
        {"chunk_id": "shared", "source": "shared.md", "distance": 0.3},
    ]
    lexical = [
        {"chunk_id": "shared", "source": "shared.md", "score": -0.4},
        {"chunk_id": "a", "source": "a.md", "score": -0.2},
        {"chunk_id": "c", "source": "c.md", "score": -0.1},
    ]

    fused = retrieval.reciprocal_rank_fusion(dense, lexical, limit=5)

    assert [item["chunk_id"] for item in fused] == ["a", "shared", "b", "c"]
    assert fused[0]["rrf_score"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[1]["rrf_score"] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[0]["distance"] == 0.1
    assert fused[0]["score"] == -0.2


def test_reciprocal_rank_fusion_breaks_ties_in_first_seen_order():
    dense = [{"chunk_id": "dense", "source": "dense.md"}]
    lexical = [{"chunk_id": "lexical", "source": "lexical.md"}]

    fused = retrieval.reciprocal_rank_fusion(dense, lexical, limit=2)

    assert [item["chunk_id"] for item in fused] == ["dense", "lexical"]


def test_retrieve_runs_sync_retrievers_in_separate_threads(monkeypatch, tmp_path):
    barrier = threading.Barrier(2)

    def dense(query, k, store_path):
        barrier.wait(timeout=2)
        return [
            {"chunk_id": "shared", "source": "shared.md", "distance": 0.1},
            {"chunk_id": "dense", "source": "dense.md"},
        ]

    def lexical(query, k, store_path):
        barrier.wait(timeout=2)
        return [
            {"chunk_id": "shared", "source": "shared.md", "score": -0.1},
            {"chunk_id": "lexical", "source": "lexical.md"},
        ]

    monkeypatch.setattr(retrieval, "retrieve_chunks", dense)
    monkeypatch.setattr(retrieval, "retrieve_lexical_chunks", lexical)

    fused = asyncio.run(retrieval.retrieve("incident", k=3, store_path=tmp_path))

    assert [item["chunk_id"] for item in fused] == ["shared", "dense", "lexical"]
    assert fused[0]["distance"] == 0.1
    assert fused[0]["score"] == -0.1
    assert fused[0]["rrf_score"] == pytest.approx(2 / 61)


def test_retrieve_hydrates_and_deduplicates_parent_context(monkeypatch, tmp_path):
    parent = ParentChunk(
        "guide.md::parent-0",
        "guide.md",
        "A guide covers pool exhaustion and recovery.",
        "Guide",
    )
    child = TextChunk(
        "guide.md::parent-0::child-0",
        "guide.md",
        "pool exhaustion",
        parent.parent_id,
        15,
        31,
    )
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    index.replace_documents([], [child], parents=[parent])

    child_result = {
        "chunk_id": child.chunk_id,
        "source": child.source,
        "text": child.text,
        "parent_id": child.parent_id,
        "parent_start": child.parent_start,
        "parent_end": child.parent_end,
    }
    monkeypatch.setattr(
        retrieval,
        "retrieve_ranked_lists",
        lambda *args, **kwargs: asyncio.sleep(
            0,
            result=(
                [child_result],
                [child_result],
            ),
        ),
    )

    results = asyncio.run(retrieval.retrieve("pool recovery", k=2, store_path=tmp_path))

    assert len(results) == 1
    assert results[0]["chunk_id"] == parent.parent_id
    assert results[0]["matched_child_id"] == child.chunk_id
    assert results[0]["text"] == parent.text
    assert results[0]["highlighted_text"] == (
        "A guide covers **pool exhaustion** and recovery."
    )


def test_async_retrieve_rejects_empty_query():
    with pytest.raises(ValueError, match="Query must not be empty"):
        asyncio.run(retrieval.retrieve("   "))
