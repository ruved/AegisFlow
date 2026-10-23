import pytest
from fastapi.testclient import TestClient

from aegisflow import api
from aegisflow.rag.errors import (
    OllamaConfigurationError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    VectorStoreUnavailableError,
)

client = TestClient(api.app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_healthy_dependencies(monkeypatch):
    monkeypatch.setattr(api, "check_ollama", lambda: None)
    monkeypatch.setattr(api, "check_vector_store", lambda path: None)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"ollama": "ok", "vector_store": "ok"},
    }


def test_readiness_reports_unavailable_dependency(monkeypatch):
    def unavailable():
        raise OllamaUnavailableError("internal connection details")

    monkeypatch.setattr(api, "check_ollama", unavailable)
    monkeypatch.setattr(api, "check_vector_store", lambda path: None)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"ollama": "unavailable", "vector_store": "ok"},
    }
    assert "internal connection details" not in response.text


def test_readiness_reports_unavailable_vector_store(monkeypatch):
    def unavailable(path):
        raise VectorStoreUnavailableError("private disk path")

    monkeypatch.setattr(api, "check_ollama", lambda: None)
    monkeypatch.setattr(api, "check_vector_store", unavailable)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["vector_store"] == "unavailable"
    assert "private disk path" not in response.text


def test_ask_endpoint_returns_answer_and_sources(monkeypatch):
    def fake_generate_answer(query, k):
        assert query == "How does AegisFlow work?"
        assert k == 3
        return {
            "answer": "AegisFlow coordinates agent workflows [architecture.md].",
            "sources": ["architecture.md"],
        }

    monkeypatch.setattr(api, "generate_answer", fake_generate_answer)

    response = client.post(
        "/ask",
        json={"question": "How does AegisFlow work?", "top_k": 3},
    )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("AegisFlow coordinates")
    assert response.json()["sources"] == ["architecture.md"]


def test_ask_endpoint_rejects_blank_question():
    response = client.post(
        "/ask",
        json={"question": "   ", "top_k": 3},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}


def test_ask_endpoint_rejects_question_over_limit():
    response = client.post(
        "/ask", json={"question": "x" * (api.MAX_QUESTION_LENGTH + 1)}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert "xxxx" not in response.text


def test_ask_endpoint_rejects_invalid_top_k():
    response = client.post(
        "/ask",
        json={"question": "Explain the architecture", "top_k": 0},
    )

    assert response.status_code == 422

    response = client.post(
        "/ask",
        json={"question": "Explain the architecture", "top_k": api.MAX_TOP_K + 1},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("failure", "status_code", "detail"),
    [
        (
            OllamaUnavailableError("secret endpoint"),
            503,
            "A required local dependency is unavailable.",
        ),
        (
            VectorStoreUnavailableError("private path"),
            503,
            "A required local dependency is unavailable.",
        ),
        (
            OllamaTimeoutError("full timeout diagnostic"),
            504,
            "Local inference timed out.",
        ),
        (
            OllamaConfigurationError("bad private URL"),
            500,
            "Service configuration error.",
        ),
        (
            OllamaResponseError("raw response body"),
            502,
            "A local dependency returned an invalid response.",
        ),
        (RuntimeError("internal file path and secret"), 500, "Internal server error."),
    ],
)
def test_ask_endpoint_maps_failures_safely(monkeypatch, failure, status_code, detail):
    def fail_generation(query, k):
        raise failure

    monkeypatch.setattr(api, "generate_answer", fail_generation)

    response = client.post(
        "/ask",
        json={"question": "Explain the architecture"},
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert str(failure) not in response.text
