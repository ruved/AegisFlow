"""Bounded structured Ollama calls used by planner, analyst, reporter and verifier."""

import json
from dataclasses import dataclass
from typing import TypeVar
from urllib.request import Request

from pydantic import BaseModel

from aegisflow.concurrency import get_inference_limiter
from aegisflow.config import MODEL_CONTEXT_SIZE, OLLAMA_CHAT_TIMEOUT_SECONDS
from aegisflow.rag.errors import OllamaResponseError
from aegisflow.rag.ollama import ollama_url, request_json
from aegisflow.tracing import trace_llm_call

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
    limiter = get_inference_limiter()
    with limiter.acquire_sync(timeout=OLLAMA_CHAT_TIMEOUT_SECONDS) as wait_info:
        with trace_llm_call(model=model, schema_name=schema.__name__) as span:
            span.set_attribute(
                "inference.queue_wait_ms", wait_info["queue_wait_ms"]
            )
            response = request_json(
                request, OLLAMA_CHAT_TIMEOUT_SECONDS, "workflow inference"
            )
            message = response.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise OllamaResponseError("Ollama returned no workflow output")
            try:
                value = schema.model_validate_json(content)
            except Exception as exc:
                raise OllamaResponseError(
                    "Ollama returned invalid workflow output"
                ) from exc

            prompt_count = response.get("prompt_eval_count")
            completion_count = response.get("eval_count")
            prompt_tokens = _validated_count(prompt_count)
            completion_tokens = _validated_count(completion_count)
            actual_counts = prompt_tokens is not None and completion_tokens is not None
            resolved_prompt = (
                prompt_tokens if prompt_tokens is not None else prompt_estimate
            )
            resolved_completion = (
                completion_tokens
                if completion_tokens is not None
                else approximate_tokens(content)
            )
            span.set_attribute("gen_ai.usage.prompt_tokens", resolved_prompt)
            span.set_attribute(
                "gen_ai.usage.completion_tokens", resolved_completion
            )
            span.set_attribute(
                "gen_ai.usage.total_tokens", resolved_prompt + resolved_completion
            )

            return StructuredCall(
                value=value,
                prompt_tokens=resolved_prompt,
                completion_tokens=resolved_completion,
                tokens_estimated=not actual_counts,
            )


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validated_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
