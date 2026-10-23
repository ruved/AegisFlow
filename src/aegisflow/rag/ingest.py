"""Ingest local Markdown and text files into the AegisFlow vector store."""

import argparse
from pathlib import Path

from aegisflow.rag.chunking import chunk_text
from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.vector_store import VectorStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs" / "rag_samples"
DEFAULT_STORE_PATH = PROJECT_ROOT / "chroma_db"
SUPPORTED_EXTENSIONS = {".md", ".txt"}


def ingest_directory(
    docs_dir: str | Path = DEFAULT_DOCS_DIR,
    store_path: str | Path = DEFAULT_STORE_PATH,
    chunk_size: int = 800,
    overlap: int = 100,
) -> dict[str, int]:
    """Read documents, chunk them, embed them, and persist their vectors."""
    source_dir = Path(docs_dir).resolve()

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Document directory not found: {source_dir}")

    files = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    all_chunks = []
    documents_read = 0

    for file_path in files:
        text = file_path.read_text(encoding="utf-8").strip()

        if not text:
            print(f"Skipping empty document: {file_path.name}")
            continue

        source = file_path.relative_to(source_dir).as_posix()
        chunks = chunk_text(
            text=text,
            source=source,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        all_chunks.extend(chunks)
        documents_read += 1

        print(f"Read {source}: {len(chunks)} chunk(s)")

    store = VectorStore(path=store_path)

    if not all_chunks:
        print("No non-empty documents to ingest.")
        return {
            "documents": documents_read,
            "chunks": 0,
            "total_chunks": store.count(),
        }

    embeddings = embed_texts([chunk.text for chunk in all_chunks])
    store.add_chunks(all_chunks, embeddings)

    result = {
        "documents": documents_read,
        "chunks": len(all_chunks),
        "total_chunks": store.count(),
    }

    print("\nIngestion complete.")
    print(f"Documents processed: {result['documents']}")
    print(f"Chunks ingested:     {result['chunks']}")
    print(f"Chunks in store:     {result['total_chunks']}")
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
