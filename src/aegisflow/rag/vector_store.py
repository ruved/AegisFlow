"""Persistent ChromaDB storage for AegisFlow RAG chunks."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import chromadb
from chromadb.errors import ChromaError

from aegisflow.config import EMBEDDING_MODEL
from aegisflow.rag.chunking import TextChunk
from aegisflow.rag.errors import VectorStoreUnavailableError


class VectorStore:
    """Store and retrieve document chunks using cosine similarity."""

    def __init__(
        self,
        path: str | Path = "chroma_db",
        collection_name: str = "aegisflow",
    ) -> None:
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "embedding_model": EMBEDDING_MODEL,
                "hnsw:space": "cosine",
            },
        )

        stored_model = (self.collection.metadata or {}).get("embedding_model")
        if stored_model != EMBEDDING_MODEL:
            raise ValueError(
                f"Collection uses embedding model {stored_model!r}, "
                f"but the configured model is {EMBEDDING_MODEL!r}. "
                "Use a fresh collection or rebuild the index."
            )

    def add_chunks(
        self,
        chunks: list[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Persist chunks and their precomputed embedding vectors."""
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding")

        if not chunks:
            return

        chromadb_embeddings: list[Sequence[float] | Sequence[int]] = []
        chromadb_embeddings.extend(embeddings)

        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[{"source": chunk.source} for chunk in chunks],
            embeddings=chromadb_embeddings,
        )

    def search(
        self,
        query_embedding: Sequence[float],
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the top-k most similar chunks."""
        if k <= 0:
            raise ValueError("k must be positive")

        count = self.collection.count()
        if count == 0:
            return []

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, count),
            include=["documents", "metadatas", "distances"],
        )

        ids_result = result["ids"]
        documents_result = result["documents"]
        metadatas_result = result["metadatas"]
        distances_result = result["distances"]
        if (
            documents_result is None
            or metadatas_result is None
            or distances_result is None
        ):
            raise RuntimeError("Chroma query omitted requested result fields")
        if not all(
            len(rows) == 1
            for rows in (
                ids_result,
                documents_result,
                metadatas_result,
                distances_result,
            )
        ):
            raise RuntimeError("Chroma query returned an unexpected result shape")

        ids = ids_result[0]
        documents = documents_result[0]
        metadatas = metadatas_result[0]
        distances = distances_result[0]
        lengths = {len(ids), len(documents), len(metadatas), len(distances)}
        if len(lengths) != 1:
            raise RuntimeError("Chroma query returned inconsistent result lengths")
        if any(not isinstance(document, str) for document in documents):
            raise RuntimeError("Chroma query returned a missing or invalid document")
        if any(not isinstance(metadata, dict) for metadata in metadatas):
            raise RuntimeError("Chroma query returned missing or invalid metadata")
        if any(not isinstance(distance, (int, float)) for distance in distances):
            raise RuntimeError("Chroma query returned a missing or invalid distance")

        matches: list[dict[str, Any]] = []

        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            matches.append(
                {
                    "chunk_id": chunk_id,
                    "text": document,
                    "source": metadata.get("source", "unknown"),
                    "distance": distance,
                }
            )

        return matches

    def count(self) -> int:
        """Return the number of stored chunks."""
        return self.collection.count()


def check_vector_store(path: str | Path) -> None:
    """Check local Chroma availability without creating a collection."""
    try:
        client = chromadb.PersistentClient(path=str(path))
        client.list_collections()
    except (ChromaError, OSError) as exc:
        raise VectorStoreUnavailableError(
            "The local vector store is unavailable"
        ) from exc
