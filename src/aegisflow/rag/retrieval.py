"""Retrieve relevant document chunks using semantic similarity."""

import argparse
from pathlib import Path
from typing import Any

from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.vector_store import VectorStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE_PATH = PROJECT_ROOT / "chroma_db"


def retrieve_chunks(
    query: str,
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
) -> list[dict[str, Any]]:
    """Find the top-k document chunks most relevant to a query."""
    if not query.strip():
        raise ValueError("Query must not be empty")

    if k <= 0:
        raise ValueError("k must be positive")

    query_embedding = embed_texts([query])[0]

    store = VectorStore(path=store_path)
    return store.search(query_embedding=query_embedding, k=k)


def main() -> None:
    """Run semantic retrieval from the command line."""
    parser = argparse.ArgumentParser(
        description="Search the AegisFlow local knowledge base."
    )
    parser.add_argument("query", help="Question or search query")
    parser.add_argument("--k", type=int, default=3, help="Maximum results")
    args = parser.parse_args()

    results = retrieve_chunks(args.query, k=args.k)

    if not results:
        print("No matching documents found.")
        return

    for rank, result in enumerate(results, start=1):
        print(f"\n--- Result {rank} ---")
        print(f"Source:   {result['source']}")
        print(f"Chunk ID: {result['chunk_id']}")
        print(f"Distance: {result['distance']:.4f}")
        print(f"Content:\n{result['text']}")


if __name__ == "__main__":
    main()
