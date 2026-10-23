import json
from io import BytesIO

import pytest

from aegisflow.rag import embeddings, ollama
from aegisflow.rag.errors import (
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}).encode(
            "utf-8"
        )


def test_embed_texts_returns_vectors(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    result = embeddings.embed_texts(["hello", "world"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["timeout"] == 30
    assert captured["request"].full_url.endswith("/api/embed")

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assert payload["model"] == embeddings.EMBEDDING_MODEL
    assert payload["input"] == ["hello", "world"]


def test_empty_input_returns_empty_list(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("Ollama should not be called for empty input")

    monkeypatch.setattr(ollama, "urlopen", unexpected_call)

    assert embeddings.embed_texts([]) == []


def test_whitespace_input_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        embeddings.embed_texts(["hello", "   "])


def test_invalid_response_is_rejected(monkeypatch):
    class InvalidResponse(FakeResponse):
        def read(self):
            return BytesIO(b'{"embeddings": []}').read()

    monkeypatch.setattr(ollama, "urlopen", lambda *args, **kwargs: InvalidResponse())

    with pytest.raises(OllamaResponseError, match="invalid embedding"):
        embeddings.embed_texts(["hello"])


def test_embedding_timeout_is_typed_and_uses_configured_limit(monkeypatch):
    captured = {}

    def timeout(request, timeout):
        captured["timeout"] = timeout
        raise TimeoutError("private detail")

    monkeypatch.setattr(ollama, "urlopen", timeout)

    with pytest.raises(OllamaTimeoutError):
        embeddings.embed_texts(["hello"])

    assert captured["timeout"] == embeddings.OLLAMA_EMBED_TIMEOUT_SECONDS


def test_embedding_connection_failure_is_typed(monkeypatch):
    from urllib.error import URLError

    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("connection refused")),
    )

    with pytest.raises(OllamaUnavailableError):
        embeddings.embed_texts(["hello"])
