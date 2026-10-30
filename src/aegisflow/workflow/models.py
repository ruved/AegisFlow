"""Bounded structured Ollama calls used by planner, analyst, reporter and verifier."""

import json
from dataclasses import dataclass
from typing import TypeVar
from urllib.request import Request

from pydantic import BaseModel

from aegisflow.config import MODEL_CONTEXT_SIZE, OLLAMA_CHAT_TIMEOUT_SECONDS
from aegisflow.rag.errors import OllamaResponseError
from aegisflow.rag.ollama import ollama_url, request_json

PydanticOutput = TypeVar("PydanticOutput", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    """Raised before inference when the remaining run budget is insufficient."""


@dataclass(frozen=True)
class StructuredCall:
    value: BaseModel
    prompt_tokens: int
    completion_tokens: int
    tokens_estimated: bool


def approximate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def call_structured[PydanticOutput: BaseModel](
    *,
    model: str,
    system: str,
    user: str,
    schema: type[PydanticOutput],
    remaining_tokens: int,
) -> StructuredCall:
    prompt_estimate = approximate_tokens(system + user)
    if remaining_tokens <= prompt_estimate + 16:
        raise BudgetExceeded("token budget would be exceeded before inference")
    max_output = min(512, remaining_tokens - prompt_estimate)
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {
                "num_ctx": MODEL_CONTEXT_SIZE,
                "num_predict": max_output,
                "temperature": 0,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")
    request = Request(
        ollama_url("/api/chat"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = request_json(request, OLLAMA_CHAT_TIMEOUT_SECONDS, "workflow inference")
    message = response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise OllamaResponseError("Ollama returned no workflow output")
    try:
        value = schema.model_validate_json(content)
    except Exception as exc:
        raise OllamaResponseError("Ollama returned invalid workflow output") from exc

    prompt_count = response.get("prompt_eval_count")
    completion_count = response.get("eval_count")
    prompt_tokens = _validated_count(prompt_count)
    completion_tokens = _validated_count(completion_count)
    actual_counts = prompt_tokens is not None and completion_tokens is not None
    return StructuredCall(
        value=value,
        prompt_tokens=prompt_tokens if prompt_tokens is not None else prompt_estimate,
        completion_tokens=(
            completion_tokens
            if completion_tokens is not None
            else approximate_tokens(content)
        ),
        tokens_estimated=not actual_counts,
    )


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validated_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
