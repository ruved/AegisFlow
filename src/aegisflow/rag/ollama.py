"""Shared, bounded HTTP requests to the local Ollama service."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from aegisflow.config import OLLAMA_BASE_URL, OLLAMA_HEALTH_TIMEOUT_SECONDS
from aegisflow.rag.errors import (
    OllamaConfigurationError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


def ollama_url(endpoint: str) -> str:
    """Build an Ollama URL after validating its non-secret configuration."""
    parsed = urlsplit(OLLAMA_BASE_URL)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OllamaConfigurationError("OLLAMA_BASE_URL must be an HTTP(S) URL")
    return f"{OLLAMA_BASE_URL.rstrip('/')}{endpoint}"


def request_json(
    request: Request,
    timeout: float,
    operation: str,
) -> dict[str, object]:
    """Send one bounded request and require a JSON object response."""
    if timeout <= 0:
        raise OllamaConfigurationError("Ollama request timeout must be positive")

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {408, 504}:
            raise OllamaTimeoutError(f"Ollama {operation} request timed out") from exc
        if exc.code >= 500:
            raise OllamaUnavailableError(
                f"Ollama returned a server error during {operation}"
            ) from exc
        if exc.code == 404:
            raise OllamaConfigurationError(
                f"Ollama could not find the configured model during {operation}"
            ) from exc
        raise OllamaResponseError(f"Ollama rejected the {operation} request") from exc
    except TimeoutError as exc:
        raise OllamaTimeoutError(f"Ollama {operation} request timed out") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise OllamaTimeoutError(f"Ollama {operation} request timed out") from exc
        raise OllamaUnavailableError(
            "Cannot connect to the local Ollama service"
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OllamaResponseError("Ollama returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise OllamaResponseError("Ollama returned an invalid JSON object")
    result: dict[str, object] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise OllamaResponseError("Ollama returned an invalid JSON object")
        result[key] = value
    return result


def check_ollama() -> None:
    """Make a lightweight bounded availability check without model inference."""
    request = Request(ollama_url("/api/tags"), method="GET")
    request_json(request, OLLAMA_HEALTH_TIMEOUT_SECONDS, "health check")
