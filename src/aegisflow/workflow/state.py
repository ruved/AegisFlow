"""Typed LangGraph state and reducer-backed append-only telemetry."""

import operator
from typing import Annotated, Literal, TypedDict

NextNode = Literal[
    "planner",
    "retrieve",
    "analyst",
    "reporter",
    "verifier",
    "rewriter",
    "finish",
    "abstain",
    "cancelled",
]


class TelemetryEvent(TypedDict):
    event_id: str
    run_id: str
    node: str
    duration_ms: float
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool
    tokens_estimated: bool
    status: str


class RunState(TypedDict, total=False):
    """Raw workflow inputs, validated node outputs, and bounded-run metadata."""

    run_id: str
    question: str
    store_path: str
    top_k: int
    planner_model: str
    model: str
    max_steps: int
    max_tokens: int
    max_retries: int
    deadline_at: float
    retry_count: int
    next_node: NextNode
    terminal: bool
    abstained: bool
    cancelled: bool
    abstention_reason: str
    loop_detected: bool
    steps: Annotated[int, operator.add]
    tokens_used: Annotated[int, operator.add]
    prompt_tokens: Annotated[int, operator.add]
    completion_tokens: Annotated[int, operator.add]
    telemetry: Annotated[list[TelemetryEvent], operator.add]
    seen_attempt_keys: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    subquestions: list[str]
    chunks: list[dict[str, object]]
    planner_output: dict[str, object]
    analyst_output: dict[str, object]
    reporter_output: dict[str, object]
    verifier_output: dict[str, object]
    report: dict[str, object]
    missing: list[str]


def deduplicate_events(events: list[TelemetryEvent]) -> list[TelemetryEvent]:
    """Make telemetry replay-safe by retaining one event per stable event ID."""
    unique: dict[str, TelemetryEvent] = {}
    for event in events:
        unique.setdefault(event["event_id"], event)
    return list(unique.values())
