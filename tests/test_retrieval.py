import pytest

from aegisflow.rag import retrieval
from aegisflow.rag.chunking import TextChunk
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
