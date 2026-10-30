from pathlib import Path

import pytest

from aegisflow.rag import ingest as ingest_module
from aegisflow.rag.chunking import TextChunk
from aegisflow.rag.ingest import ingest_directory
from aegisflow.rag.ingest_state import CorpusManifest
from aegisflow.rag.lexical_index import LexicalIndex
from aegisflow.rag.vector_store import VectorStore


@pytest.fixture
def embedding_calls(monkeypatch):
    calls: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(ingest_module, "embed_texts", embed)
    return calls


def test_unchanged_corpus_skips_embedding(embedding_calls, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("RAG stores useful context.", encoding="utf-8")
    store_path = tmp_path / "store"

    first = ingest_directory(docs, store_path)
    second = ingest_directory(docs, store_path)

    assert first["changed"] == 1
    assert first["chunks"] == 1
    assert first["corpus_version"] == 1
    assert second["changed"] == 0
    assert second["unchanged"] == 1
    assert second["chunks"] == 0
    assert second["corpus_version"] == 1
    assert len(embedding_calls) == 1
    assert second["total_chunks"] == 1
    lexical = LexicalIndex(store_path / "lexical.sqlite3")
    assert lexical.search("context")[0]["source"] == "guide.md"


def test_edit_reindexes_only_that_document_and_removes_old_tail_chunks(
    embedding_calls, tmp_path
):
    docs = tmp_path / "docs"
    docs.mkdir()
    edited_path = docs / "edited.md"
    unchanged_path = docs / "unchanged.md"
    edited_path.write_text("one two three four five six", encoding="utf-8")
    unchanged_path.write_text("keep it", encoding="utf-8")
    store_path = tmp_path / "store"

    first = ingest_directory(docs, store_path, parent_tokens=20, child_tokens=2)
    edited_path.write_text("short", encoding="utf-8")
    second = ingest_directory(docs, store_path, parent_tokens=20, child_tokens=2)

    assert first["chunks"] > second["chunks"]
    assert second["changed"] == 1
    assert second["unchanged"] == 1
    assert second["total_chunks"] == 2
    assert embedding_calls[1] == ["short"]

    store = VectorStore(path=store_path)
    edited_chunks = store.collection.get(
        where={"source": "edited.md"}, include=["documents"]
    )
    assert edited_chunks["documents"] == ["short"]
    lexical = LexicalIndex(store_path / "lexical.sqlite3")
    assert lexical.search("six") == []
    assert lexical.search("short")[0]["source"] == "edited.md"


def test_deleting_a_file_removes_its_chunks_and_bumps_version(
    embedding_calls, tmp_path
):
    docs = tmp_path / "docs"
    docs.mkdir()
    removed = docs / "remove.md"
    keep = docs / "keep.md"
    removed.write_text("remove me", encoding="utf-8")
    keep.write_text("keep me", encoding="utf-8")
    store_path = tmp_path / "store"

    first = ingest_directory(docs, store_path)
    removed.unlink()
    second = ingest_directory(docs, store_path)

    assert first["total_chunks"] == 2
    assert second["deleted"] == 1
    assert second["unchanged"] == 1
    assert second["total_chunks"] == 1
    assert second["corpus_version"] == first["corpus_version"] + 1
    assert len(embedding_calls) == 1

    manifest = CorpusManifest.load(Path(store_path) / "ingestion_manifest.json")
    assert set(manifest.documents) == {"keep.md"}
    lexical = LexicalIndex(store_path / "lexical.sqlite3")
    assert lexical.search("remove") == []


def test_embedding_failure_keeps_old_chunks_and_manifest(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "service.md"
    source.write_text("old content", encoding="utf-8")
    store_path = tmp_path / "store"
    monkeypatch.setattr(
        ingest_module,
        "embed_texts",
        lambda texts: [[1.0, 0.0, 0.0] for _ in texts],
    )
    ingest_directory(docs, store_path)
    old_manifest = CorpusManifest.load(Path(store_path) / "ingestion_manifest.json")

    source.write_text("new content", encoding="utf-8")
    monkeypatch.setattr(
        ingest_module,
        "embed_texts",
        lambda texts: (_ for _ in ()).throw(RuntimeError("embedding failed")),
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        ingest_directory(docs, store_path)

    store = VectorStore(path=store_path)
    chunks = store.collection.get(where={"source": "service.md"}, include=["documents"])
    assert chunks["documents"] == ["old content"]
    assert (
        CorpusManifest.load(Path(store_path) / "ingestion_manifest.json")
        == old_manifest
    )


def test_first_manifest_run_removes_legacy_sources_missing_from_corpus(
    embedding_calls, tmp_path
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "current.md").write_text("current content", encoding="utf-8")
    store_path = tmp_path / "store"
    legacy_store = VectorStore(path=store_path)
    legacy_store.add_chunks(
        [
            TextChunk("current.md::chunk-0", "current.md", "old current content"),
            TextChunk("removed.md::chunk-0", "removed.md", "legacy orphan"),
        ],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    result = ingest_directory(docs, store_path)

    assert result["total_chunks"] == 1
    assert result["corpus_version"] == 1
    assert len(embedding_calls) == 1
    assert legacy_store.list_document_ids() == {"current.md"}


def test_missing_lexical_index_backfills_without_reembedding(embedding_calls, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("ERR_POOL_01 connection exhausted", encoding="utf-8")
    store_path = tmp_path / "store"

    first = ingest_directory(docs, store_path)
    (store_path / "lexical.sqlite3").unlink()
    second = ingest_directory(docs, store_path)

    assert second["changed"] == 0
    assert second["unchanged"] == 1
    assert second["lexical_chunks"] == first["chunks"]
    assert second["corpus_version"] == first["corpus_version"]
    assert len(embedding_calls) == 1
    lexical = LexicalIndex(store_path / "lexical.sqlite3")
    assert lexical.search("ERR_POOL_01")[0]["source"] == "guide.md"


def test_large_document_embeddings_are_sent_in_bounded_batches(
    embedding_calls, tmp_path
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "large.md").write_text("0123456789" * 9, encoding="utf-8")

    result = ingest_directory(
        docs,
        tmp_path / "store",
        parent_tokens=100,
        child_tokens=2,
    )

    assert result["chunks"] == 12
    assert [len(batch) for batch in embedding_calls] == [8, 4]
