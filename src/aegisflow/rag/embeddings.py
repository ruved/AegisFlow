"""Generate text embeddings through the local Ollama API."""

import json
from math import isfinite
from urllib.request import Request

from aegisflow.config import EMBEDDING_MODEL, OLLAMA_EMBED_TIMEOUT_SECONDS
from aegisflow.rag.errors import OllamaResponseError
from aegisflow.rag.ollama import ollama_url, request_json


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector for each input text."""
    if not texts:
        return []

    if any(not text.strip() for text in texts):
        raise ValueError("Texts must not contain empty or whitespace-only strings")

    payload = json.dumps(
        {
            "model": EMBEDDING_MODEL,
            "input": texts,
        }
    ).encode("utf-8")

    request = Request(
        ollama_url("/api/embed"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = request_json(request, OLLAMA_EMBED_TIMEOUT_SECONDS, "embedding")
    embeddings = result.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise OllamaResponseError("Ollama returned an invalid embedding response")

    vectors: list[list[float]] = []
    for vector in embeddings:
        if (
            not isinstance(vector, list)
            or not vector
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                for value in vector
            )
        ):
            raise OllamaResponseError(
                "Ollama returned an empty or invalid embedding vector"
            )
        vectors.append([float(value) for value in vector])

    return vectors
