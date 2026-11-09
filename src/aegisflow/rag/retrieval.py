"""Retrieve and fuse semantic and lexical document matches."""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.lexical_index import LexicalIndex
from aegisflow.rag.vector_store import VectorStore
from aegisflow.tracing import trace_retrieval

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


def retrieve_lexical_chunks(
    query: str,
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
) -> list[dict[str, Any]]:
    """Find the top-k keyword matches in the persistent FTS5 index."""
    if not query.strip():
        raise ValueError("Query must not be empty")
    if k <= 0:
        raise ValueError("k must be positive")

    index = LexicalIndex(Path(store_path) / "lexical.sqlite3")
    return index.search(query, k=k)


def reciprocal_rank_fusion(
    dense_results: Sequence[dict[str, Any]],
    lexical_results: Sequence[dict[str, Any]],
    limit: int = 3,
    rrf_constant: int = 60,
) -> list[dict[str, Any]]:
    """Merge ranked lists by chunk ID using reciprocal rank contributions."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if rrf_constant <= 0:
        raise ValueError("rrf_constant must be positive")

    fused: dict[str, tuple[dict[str, Any], float, int]] = {}
    first_seen = 0
    for result_list in (dense_results, lexical_results):
        for rank, result in enumerate(result_list, start=1):
            chunk_id = result.get("chunk_id")
            if not isinstance(chunk_id, str):
                raise ValueError("Each retrieval result must have a string chunk_id")

            prior = fused.get(chunk_id)
            contribution = 1.0 / (rrf_constant + rank)
            if prior is None:
                fused[chunk_id] = (dict(result), contribution, first_seen)
                first_seen += 1
            else:
                merged_result = dict(prior[0])
                for key, value in result.items():
                    merged_result.setdefault(key, value)
                fused[chunk_id] = (
                    merged_result,
                    prior[1] + contribution,
                    prior[2],
                )

    ranked = sorted(
        fused.items(),
        key=lambda item: (-item[1][1], item[1][2], item[0]),
    )
    return [{**result, "rrf_score": score} for _, (result, score, _) in ranked[:limit]]


def hydrate_parent_results(
    child_results: Sequence[dict[str, Any]],
    store_path: str | Path,
    k: int,
) -> list[dict[str, Any]]:
    """Replace matching child text with unique parent context and a marked excerpt."""
    index = LexicalIndex(Path(store_path) / "lexical.sqlite3")
    parent_ids = [
        str(result["parent_id"])
        for result in child_results
        if isinstance(result.get("parent_id"), str)
    ]
    parents = index.get_parent_chunks(parent_ids)
    results: list[dict[str, Any]] = []
    seen_parents: set[str] = set()

    for child in child_results:
        parent_id = child.get("parent_id")
        if not isinstance(parent_id, str) or parent_id not in parents:
            child_id = str(child.get("chunk_id", ""))
            if child_id not in seen_parents:
                results.append(dict(child))
                seen_parents.add(child_id)
            if len(results) == k:
                break
            continue
        if parent_id in seen_parents:
            continue

        parent = parents[parent_id]
        matched_child = str(child.get("text", ""))
        parent_text = str(parent["text"])
        start = child.get("parent_start")
        end = child.get("parent_end")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and parent_text[start:end] == matched_child
        ):
            highlighted = (
                parent_text[:start] + "**" + matched_child + "**" + parent_text[end:]
            )
        else:
            match_start = parent_text.find(matched_child)
            if matched_child and match_start >= 0:
                match_end = match_start + len(matched_child)
                highlighted = (
                    parent_text[:match_start]
                    + "**"
                    + matched_child
                    + "**"
                    + parent_text[match_end:]
                )
            else:
                highlighted = parent_text

        results.append(
            {
                **child,
                "chunk_id": parent_id,
                "parent_id": parent_id,
                "source": parent["source"],
                "heading": parent["heading"],
                "text": parent_text,
                "matched_child_id": child.get("chunk_id"),
                "matched_child": matched_child,
                "highlighted_text": highlighted,
            }
        )
        seen_parents.add(parent_id)
        if len(results) == k:
            break

    return results


async def retrieve(
    query: str,
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
    rrf_constant: int = 60,
) -> list[dict[str, Any]]:
    """Run dense and lexical retrieval concurrently, then return fused results."""
    if not query.strip():
        raise ValueError("Query must not be empty")
    if k <= 0:
        raise ValueError("k must be positive")

    candidate_limit = max(k * 3, k)
    with trace_retrieval(query, k, str(store_path)) as span:
        dense_results, lexical_results = await retrieve_ranked_lists(
            query, k=candidate_limit, store_path=store_path
        )
        fused_children = reciprocal_rank_fusion(
            dense_results,
            lexical_results,
            limit=candidate_limit,
            rrf_constant=rrf_constant,
        )
        results = await asyncio.to_thread(
            hydrate_parent_results, fused_children, store_path, k
        )
        span.set_attribute("retrieval.results_count", len(results))
        return results


async def retrieve_ranked_lists(
    query: str,
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return dense and lexical rankings, collected concurrently in worker threads."""
    if not query.strip():
        raise ValueError("Query must not be empty")
    if k <= 0:
        raise ValueError("k must be positive")

    return await asyncio.gather(
        asyncio.to_thread(retrieve_chunks, query, k, store_path),
        asyncio.to_thread(retrieve_lexical_chunks, query, k, store_path),
    )


def retrieve_sync(
    query: str,
    k: int = 3,
    store_path: str | Path = DEFAULT_STORE_PATH,
) -> list[dict[str, Any]]:
    """Synchronous bridge for CLI and the existing synchronous generation path."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(retrieve(query, k=k, store_path=store_path))
    raise RuntimeError("Use await retrieve() when an event loop is already running")


def main() -> None:
    """Run semantic retrieval from the command line."""
    parser = argparse.ArgumentParser(
        description="Search the AegisFlow local knowledge base."
    )
    parser.add_argument("query", help="Question or search query")
    parser.add_argument("--k", type=int, default=3, help="Maximum results")
    args = parser.parse_args()

    results = retrieve_sync(args.query, k=args.k)

    if not results:
        print("No matching documents found.")
        return

    for rank, result in enumerate(results, start=1):
        print(f"\n--- Result {rank} ---")
        print(f"Source:   {result['source']}")
        print(f"Chunk ID: {result['chunk_id']}")
        print(f"RRF score: {result['rrf_score']:.6f}")
        print(f"Content:\n{result['text']}")


if __name__ == "__main__":
    main()
