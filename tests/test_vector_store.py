import pytest

from aegisflow.rag.chunking import TextChunk
from aegisflow.rag.vector_store import VectorStore


@pytest.fixture
def store(tmp_path):
    return VectorStore(path=tmp_path / "chroma_db")


def test_store_adds_and_counts_chunks(store):
    chunks = [
        TextChunk("doc1::chunk-0", "doc1.md", "RAG retrieves relevant context."),
        TextChunk("doc1::chunk-1", "doc1.md", "Embeddings represent text as vectors."),
    ]
    vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    store.add_chunks(chunks, vectors)

    assert store.count() == 2


def test_search_returns_most_similar_chunk(store):
    chunks = [
        TextChunk("a", "a.md", "Relevant passage"),
        TextChunk("b", "b.md", "Unrelated passage"),
    ]
    vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    store.add_chunks(chunks, vectors)

    results = store.search([0.99, 0.01, 0.0], k=1)

    assert len(results) == 1
    assert results[0]["chunk_id"] == "a"
    assert results[0]["source"] == "a.md"


def test_search_empty_store_returns_no_results(store):
    assert store.search([1.0, 0.0, 0.0]) == []


def test_search_rejects_missing_chroma_result_fields(store, monkeypatch):
    store.add_chunks(
        [TextChunk("a", "a.md", "passage")],
        [[1.0, 0.0, 0.0]],
    )
    monkeypatch.setattr(
        store.collection,
        "query",
        lambda **kwargs: {
            "ids": [["a"]],
            "documents": None,
            "metadatas": [[{"source": "a.md"}]],
            "distances": [[0.0]],
        },
    )

    with pytest.raises(RuntimeError, match="omitted requested result fields"):
        store.search([1.0, 0.0, 0.0])


def test_search_rejects_inconsistent_chroma_result_lengths(store, monkeypatch):
    store.add_chunks(
        [TextChunk("a", "a.md", "passage")],
        [[1.0, 0.0, 0.0]],
    )
    monkeypatch.setattr(
        store.collection,
        "query",
        lambda **kwargs: {
            "ids": [["a"]],
            "documents": [["passage", "extra"]],
            "metadatas": [[{"source": "a.md"}]],
            "distances": [[0.0]],
        },
    )

    with pytest.raises(RuntimeError, match="inconsistent result lengths"):
        store.search([1.0, 0.0, 0.0])


def test_invalid_arguments_are_rejected(store):
    with pytest.raises(ValueError, match="one embedding"):
        store.add_chunks(
            [TextChunk("a", "a.md", "hello")],
            [],
        )

    with pytest.raises(ValueError, match="positive"):
        store.search([1.0, 0.0, 0.0], k=0)


def test_store_persists_between_instances(tmp_path):
    path = tmp_path / "persistent_db"
    first = VectorStore(path=path)
    first.add_chunks(
        [TextChunk("persist-1", "notes.md", "Persistent vector data")],
        [[1.0, 0.0, 0.0]],
    )

    second = VectorStore(path=path)

    assert second.count() == 1
    assert second.search([1.0, 0.0, 0.0], k=1)[0]["text"] == ("Persistent vector data")
