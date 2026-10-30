"""Incrementally ingest local documents into the AegisFlow vector store."""

import argparse
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aegisflow.rag.document_parser import parse_document
from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.ingest_state import CorpusManifest, content_hash, document_id
from aegisflow.rag.lexical_index import LexicalIndex
from aegisflow.rag.parent_child import (
    DEFAULT_CHILD_TOKENS,
    DEFAULT_PARENT_TOKENS,
    parent_child_chunks,
)
from aegisflow.rag.vector_store import VectorStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs" / "rag_samples"
DEFAULT_STORE_PATH = PROJECT_ROOT / "chroma_db"
SUPPORTED_EXTENSIONS = {".md", ".txt", ".log", ".html", ".htm"}
EMBEDDING_BATCH_SIZE = 8


@contextmanager
def _ingestion_lock(store_path: str | Path) -> Iterator[None]:
    """Serialize ingestion runs targeting the same persistent store."""
    lock_path = Path(store_path) / "ingestion.lock.sqlite3"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(lock_path, timeout=60.0)
    try:
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _embed_in_batches(texts: list[str]) -> list[list[float]]:
    """Embed bounded groups so large corpora fit the local request timeout."""
    embeddings: list[list[float]] = []
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[offset : offset + EMBEDDING_BATCH_SIZE]
        batch_embeddings = embed_texts(batch)
        if len(batch_embeddings) != len(batch):
            raise ValueError(
                "Embedding service returned a different number of vectors than inputs"
            )
        for embedding in batch_embeddings:
            if not embedding or any(
                not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in embedding
            ):
                raise ValueError("Embedding service returned an invalid vector")
        embeddings.extend(batch_embeddings)
    return embeddings


def ingest_directory(
    docs_dir: str | Path = DEFAULT_DOCS_DIR,
    store_path: str | Path = DEFAULT_STORE_PATH,
    parent_tokens: int = DEFAULT_PARENT_TOKENS,
    child_tokens: int = DEFAULT_CHILD_TOKENS,
) -> dict[str, int]:
    """Update only new or changed documents and remove deleted documents."""
    with _ingestion_lock(store_path):
        return _ingest_directory_locked(
            docs_dir, store_path, parent_tokens=parent_tokens, child_tokens=child_tokens
        )


def _ingest_directory_locked(
    docs_dir: str | Path,
    store_path: str | Path,
    *,
    parent_tokens: int,
    child_tokens: int,
) -> dict[str, int]:
    """Run ingestion while holding the store's cross-process write lock."""
    source_dir = Path(docs_dir).resolve()

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Document directory not found: {source_dir}")

    files = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    store = VectorStore(path=store_path)
    lexical_index = LexicalIndex(Path(store_path) / "lexical.sqlite3")
    indexed_lexical_documents = lexical_index.list_document_ids()
    manifest_path = Path(store_path) / "ingestion_manifest.json"
    manifest_exists = manifest_path.exists()
    manifest = CorpusManifest.load(manifest_path)
    pipeline_version = f"parent-child-v1:p{parent_tokens}:c{child_tokens}"
    current_documents: dict[str, str] = {}
    changed_document_ids: list[str] = []
    changed_parents = []
    changed_chunks = []
    lexical_document_ids_to_update: list[str] = []
    lexical_parents = []
    lexical_chunks = []
    unchanged_documents = 0

    for file_path in files:
        text = parse_document(file_path.read_text(encoding="utf-8"), file_path.suffix)
        doc_id = document_id(file_path, source_dir)
        current_documents[doc_id] = content_hash(text)
        vector_changed = (
            manifest.pipeline_version != pipeline_version
            or manifest.documents.get(doc_id) != current_documents[doc_id]
        )
        lexical_missing = bool(text) and doc_id not in indexed_lexical_documents

        if not vector_changed:
            unchanged_documents += 1
        else:
            changed_document_ids.append(doc_id)

        if not vector_changed and not lexical_missing:
            continue

        parents, chunks = parent_child_chunks(
            text,
            doc_id,
            parent_tokens=parent_tokens,
            child_tokens=child_tokens,
        )
        if vector_changed:
            changed_parents.extend(parents)
            changed_chunks.extend(chunks)
            print(
                f"Prepared {doc_id}: {len(parents)} parent(s), "
                f"{len(chunks)} child chunk(s)"
            )
        if vector_changed or lexical_missing:
            lexical_parents.extend(parents)
            lexical_chunks.extend(chunks)
            lexical_document_ids_to_update.append(doc_id)

    deleted_document_ids = set(manifest.documents) - set(current_documents)
    if not manifest_exists:
        deleted_document_ids |= store.list_document_ids() - set(current_documents)

    embeddings = _embed_in_batches([chunk.text for chunk in changed_chunks])
    documents_to_delete = set(changed_document_ids) | deleted_document_ids
    store.delete_documents(sorted(documents_to_delete))
    store.add_chunks(changed_chunks, embeddings)
    lexical_documents_to_replace = (
        set(lexical_document_ids_to_update)
        | deleted_document_ids
        | (indexed_lexical_documents - set(current_documents))
    )
    lexical_index.replace_documents(
        sorted(lexical_documents_to_replace),
        lexical_chunks,
        parents=lexical_parents,
    )
    committed_manifest = manifest.commit(
        manifest_path,
        current_documents,
        pipeline_version=pipeline_version,
    )

    result = {
        "documents": len(current_documents),
        "changed": len(changed_document_ids),
        "deleted": len(deleted_document_ids),
        "unchanged": unchanged_documents,
        "parents": len(changed_parents),
        "chunks": len(changed_chunks),
        "lexical_chunks": len(lexical_chunks),
        "total_chunks": store.count(),
        "corpus_version": committed_manifest.corpus_version,
    }

    print("\nIngestion complete.")
    print(f"Documents processed: {result['documents']}")
    print(f"Documents changed:   {result['changed']}")
    print(f"Documents deleted:   {result['deleted']}")
    print(f"Documents unchanged: {result['unchanged']}")
    print(f"Parents indexed:     {result['parents']}")
    print(f"Child chunks indexed:{result['chunks']:>4}")
    print(f"Lexical chunks:      {result['lexical_chunks']}")
    print(f"Chunks in store:     {result['total_chunks']}")
    print(f"Corpus version:      {result['corpus_version']}")
    print(f"Vector store:        {Path(store_path).resolve()}")

    return result


def main() -> None:
    """Run ingestion from the command line."""
    parser = argparse.ArgumentParser(
        description="Ingest local documents into the AegisFlow vector store."
    )
    parser.add_argument(
        "--docs",
        type=Path,
        default=DEFAULT_DOCS_DIR,
        help="Directory containing Markdown or text documents.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Directory for persistent ChromaDB storage.",
    )
    args = parser.parse_args()

    ingest_directory(docs_dir=args.docs, store_path=args.store)


if __name__ == "__main__":
    main()
