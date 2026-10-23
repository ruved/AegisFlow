import json
from urllib.error import HTTPError

import pytest

from aegisflow.config import OLLAMA_CHAT_TIMEOUT_SECONDS
from aegisflow.rag import generation, ollama
from aegisflow.rag.errors import OllamaTimeoutError, OllamaUnavailableError


class FakeResponse:
    """Simulate a successful Ollama HTTP response."""

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_generate_answer_returns_answer_and_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation,
        "retrieve_chunks",
        lambda *args, **kwargs: [
            {
                "chunk_id": "architecture.md::chunk-0",
                "source": "architecture.md",
                "text": "AegisFlow coordinates agent workflows.",
                "distance": 0.2,
            },
            {
                "chunk_id": "ingestion.md::chunk-0",
                "source": "ingestion.md",
                "text": "Documents are embedded and stored.",
                "distance": 0.3,
            },
        ],
    )

    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda request, timeout: FakeResponse(
            {
                "message": {
                    "content": (
                        "AegisFlow coordinates agent workflows [architecture.md]."
                    )
                }
            }
        ),
    )

    result = generation.generate_answer(
        "How does AegisFlow work?",
        store_path=tmp_path / "test_db",
    )

    assert "coordinates agent workflows" in result["answer"]
    assert result["sources"] == ["architecture.md", "ingestion.md"]
    assert set(result) == {"answer", "sources"}
    assert isinstance(result["answer"], str)
    assert isinstance(result["sources"], list)


def test_generate_answer_with_details_exposes_evidence_and_actual_usage(
    monkeypatch, tmp_path
):
    chunks = [
        {
            "chunk_id": "runbook.md::chunk-0",
            "source": "runbook.md",
            "text": "Connections reached the configured maximum.",
            "distance": 0.1,
        }
    ]
    monkeypatch.setattr(generation, "retrieve_chunks", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda request, timeout: FakeResponse(
            {
                "message": {"content": "The pool reached its configured maximum."},
                "prompt_eval_count": 42,
                "eval_count": 11,
            }
        ),
    )

    result = generation.generate_answer_with_details(
        "What happened?", store_path=tmp_path / "test_db"
    )

    assert result["retrieved_chunks"] == chunks
    assert result["sources"] == ["runbook.md"]
    assert result["prompt_tokens"] == 42
    assert result["completion_tokens"] == 11


def test_generate_answer_sends_grounded_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation,
        "retrieve_chunks",
        lambda *args, **kwargs: [
            {
                "chunk_id": "architecture.md::chunk-0",
                "source": "architecture.md",
                "text": "AegisFlow coordinates agent workflows.",
                "distance": 0.2,
            }
        ],
    )

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {"message": {"content": "AegisFlow coordinates workflows."}}
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    generation.generate_answer(
        "Explain the architecture",
        store_path=tmp_path / "test_db",
    )

    payload = captured["payload"]
    assert payload["model"] == generation.CHAT_MODEL
    assert payload["stream"] is False
    assert len(payload["messages"]) == 2
    assert "untrusted reference material" in payload["messages"][0]["content"]
    assert "AegisFlow coordinates agent workflows." in payload["messages"][1]["content"]


def test_generate_answer_handles_empty_retrieval(monkeypatch, tmp_path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Ollama should not be called without retrieved context")

    monkeypatch.setattr(generation, "retrieve_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(ollama, "urlopen", fail_if_called)

    result = generation.generate_answer(
        "Unknown question",
        store_path=tmp_path / "test_db",
    )

    assert result["sources"] == []
    assert "don't have enough information" in result["answer"]


def test_generate_answer_rejects_empty_query():
    with pytest.raises(ValueError, match="Query must not be empty"):
        generation.generate_answer("   ")


def test_generate_answer_handles_ollama_http_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation,
        "retrieve_chunks",
        lambda *args, **kwargs: [
            {
                "chunk_id": "architecture.md::chunk-0",
                "source": "architecture.md",
                "text": "AegisFlow coordinates agent workflows.",
                "distance": 0.2,
            }
        ],
    )

    def fail_request(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(ollama, "urlopen", fail_request)

    with pytest.raises(OllamaUnavailableError, match="server error"):
        generation.generate_answer(
            "Explain the architecture",
            store_path=tmp_path / "test_db",
        )


def test_generate_answer_timeout_uses_configured_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation,
        "retrieve_chunks",
        lambda *args, **kwargs: [
            {
                "chunk_id": "architecture.md::chunk-0",
                "source": "architecture.md",
                "text": "AegisFlow coordinates agent workflows.",
                "distance": 0.2,
            }
        ],
    )
    captured = {}

    def timeout(request, timeout):
        captured["timeout"] = timeout
        raise TimeoutError("private transport detail")

    monkeypatch.setattr(ollama, "urlopen", timeout)

    with pytest.raises(OllamaTimeoutError):
        generation.generate_answer(
            "Explain the architecture", store_path=tmp_path / "test_db"
        )

    assert captured["timeout"] == OLLAMA_CHAT_TIMEOUT_SECONDS
