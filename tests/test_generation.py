import json
from urllib.error import HTTPError

import pytest

from aegisflow.config import OLLAMA_CHAT_TIMEOUT_SECONDS
from aegisflow.rag import generation, ollama
from aegisflow.rag.errors import (
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


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
        generation, "_judge_evidence_sufficiency", lambda *_: (True, [])
    )
    monkeypatch.setattr(
        generation,
        "retrieve_sync",
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
                    "content": json.dumps(
                        {
                            "claims": [
                                {
                                    "text": "AegisFlow coordinates agent workflows.",
                                    "evidence_ids": ["1"],
                                }
                            ]
                        }
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
    assert result["answer"].endswith("[1]")
    assert result["sources"] == ["architecture.md"]
    assert result["citations"] == [
        {
            "evidence_id": "1",
            "chunk_id": "architecture.md::chunk-0",
            "source": "architecture.md",
            "heading": None,
        }
    ]
    assert set(result) == {
        "answer",
        "sources",
        "citations",
        "abstained",
        "missing",
        "verifier_sufficient",
    }
    assert isinstance(result["answer"], str)
    assert isinstance(result["sources"], list)


def test_generate_answer_with_details_exposes_evidence_and_actual_usage(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        generation, "_judge_evidence_sufficiency", lambda *_: (True, [])
    )
    chunks = [
        {
            "chunk_id": "runbook.md::chunk-0",
            "source": "runbook.md",
            "text": "Connections reached the configured maximum.",
            "distance": 0.1,
        }
    ]
    monkeypatch.setattr(generation, "retrieve_sync", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda request, timeout: FakeResponse(
            {
                "message": {
                    "content": json.dumps(
                        {
                            "claims": [
                                {
                                    "text": "The pool reached its configured maximum.",
                                    "evidence_ids": ["1"],
                                }
                            ]
                        }
                    )
                },
                "prompt_eval_count": 42,
                "eval_count": 11,
            }
        ),
    )

    result = generation.generate_answer_with_details(
        "What happened?", store_path=tmp_path / "test_db"
    )

    assert result["retrieved_chunks"] == [{**chunks[0], "evidence_id": "1"}]
    assert result["sources"] == ["runbook.md"]
    assert result["claims"] == [
        {
            "text": "The pool reached its configured maximum.",
            "evidence_ids": ["1"],
        }
    ]
    assert result["citations"][0]["chunk_id"] == "runbook.md::chunk-0"
    assert result["prompt_tokens"] == 42
    assert result["completion_tokens"] == 11


def test_generate_answer_sends_grounded_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation, "_judge_evidence_sufficiency", lambda *_: (True, [])
    )
    monkeypatch.setattr(
        generation,
        "retrieve_sync",
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
            {
                "message": {
                    "content": json.dumps(
                        {
                            "claims": [
                                {
                                    "text": "AegisFlow coordinates workflows.",
                                    "evidence_ids": ["1"],
                                }
                            ]
                        }
                    )
                }
            }
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    generation.generate_answer(
        "Explain the architecture",
        store_path=tmp_path / "test_db",
    )

    payload = captured["payload"]
    assert payload["model"] == generation.CHAT_MODEL
    assert payload["stream"] is False
    assert payload["format"] == generation.CLAIMS_JSON_SCHEMA
    assert len(payload["messages"]) == 2
    assert "untrusted reference material" in payload["messages"][0]["content"]
    assert "[1] Source: architecture.md" in payload["messages"][1]["content"]
    assert "AegisFlow coordinates agent workflows." in payload["messages"][1]["content"]
    assert "architecture.md::chunk-0" not in payload["messages"][1]["content"]


def test_generate_answer_handles_empty_retrieval(monkeypatch, tmp_path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Ollama should not be called without retrieved context")

    monkeypatch.setattr(generation, "retrieve_sync", lambda *args, **kwargs: [])
    monkeypatch.setattr(ollama, "urlopen", fail_if_called)

    result = generation.generate_answer(
        "Unknown question",
        store_path=tmp_path / "test_db",
    )

    assert result["sources"] == []
    assert result["citations"] == []
    assert "don't have enough information" in result["answer"]


def test_evidence_judge_can_abstain_with_missing_context(monkeypatch):
    monkeypatch.setattr(
        generation,
        "request_json",
        lambda request, timeout, label: {
            "message": {
                "content": json.dumps(
                    {"sufficient": False, "missing": ["current live metrics"]}
                )
            }
        },
    )
    sufficient, missing = generation._judge_evidence_sufficiency(
        "What is the current lag?",
        [{"source": "guide.md", "heading": "Metrics", "text": "Historical lag."}],
    )
    assert sufficient is False
    assert missing == ["current live metrics"]


def test_retrieval_score_gate_abstains_without_calling_judge(monkeypatch):
    monkeypatch.setattr(
        generation,
        "request_json",
        lambda *args, **kwargs: pytest.fail("weak evidence should fail the score gate"),
    )
    assert generation._judge_evidence_sufficiency(
        "Question?", [{"distance": 0.9, "text": "weak", "source": "x"}]
    ) == (False, ["a directly relevant source passage"])


def test_invalid_citation_id_is_rejected_by_validator():
    with pytest.raises(OllamaResponseError, match="outside the provided context"):
        generation.parse_and_validate_claims(
            json.dumps({"claims": [{"text": "Unsupported.", "evidence_ids": ["9"]}]}),
            {"1": {"chunk_id": "guide::parent-0", "source": "guide.md"}},
        )


def test_inline_citation_text_is_rejected_so_only_validated_refs_render():
    with pytest.raises(OllamaResponseError, match="invalid structured answer"):
        generation.parse_and_validate_claims(
            json.dumps(
                {
                    "claims": [
                        {
                            "text": "The pool failed [fake.md].",
                            "evidence_ids": ["1"],
                        }
                    ]
                }
            ),
            {"1": {"chunk_id": "guide::parent-0", "source": "guide.md"}},
        )


def test_invalid_citation_is_retried_once_then_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation, "_judge_evidence_sufficiency", lambda *_: (True, [])
    )
    chunks = [
        {
            "chunk_id": "guide.md::parent-0",
            "source": "guide.md",
            "heading": "Guide",
            "text": "The service uses a bounded connection pool.",
        }
    ]
    monkeypatch.setattr(generation, "retrieve_sync", lambda *args, **kwargs: chunks)
    requests = []
    responses = [
        {"claims": [{"text": "The pool is bounded.", "evidence_ids": ["99"]}]},
        {"claims": [{"text": "The pool is bounded.", "evidence_ids": ["1"]}]},
    ]

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"message": {"content": json.dumps(responses.pop(0))}})

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    result = generation.generate_answer_with_details(
        "How is the pool configured?", store_path=tmp_path / "test_db"
    )

    assert len(requests) == 2
    assert "failed validation" in requests[1]["messages"][1]["content"]
    assert result["answer"] == "The pool is bounded. [1]"
    assert result["citations"] == [
        {
            "evidence_id": "1",
            "chunk_id": "guide.md::parent-0",
            "source": "guide.md",
            "heading": "Guide",
        }
    ]


def test_generate_answer_rejects_empty_query():
    with pytest.raises(ValueError, match="Query must not be empty"):
        generation.generate_answer("   ")


def test_generate_answer_handles_ollama_http_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        generation,
        "retrieve_sync",
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
        "retrieve_sync",
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
