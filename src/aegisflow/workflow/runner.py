"""Public adapter that keeps LangGraph out of callers and evaluation code."""

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from aegisflow.config import CHAT_MODEL
from aegisflow.rag.retrieval import DEFAULT_STORE_PATH
from aegisflow.workflow.graph import build_graph, sqlite_saver_context
from aegisflow.workflow.logging_setup import bind_run_id, configure_json_logging
from aegisflow.workflow.nodes import WorkflowLimits, WorkflowServices
from aegisflow.workflow.state import RunState, deduplicate_events

__all__ = ["run_workflow", "run_workflow_async", "sqlite_saver_context"]


def run_workflow(
    state: RunState | dict[str, Any],
    *,
    services: WorkflowServices | None = None,
    limits: WorkflowLimits | None = None,
) -> RunState:
    """Execute a bounded workflow and return its typed final state."""
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Workflow question must not be empty")

    configured_limits = limits or WorkflowLimits()
    run_id_value = state.get("run_id") or uuid4().hex
    run_id = str(run_id_value)
    initial: dict[str, Any] = dict(state)
    initial.update(
        {
            "run_id": run_id,
            "question": question.strip(),
            "store_path": str(state.get("store_path", DEFAULT_STORE_PATH)),
            "top_k": int(state.get("top_k", 3)),
            "planner_model": str(state.get("planner_model", CHAT_MODEL)),
            "model": str(state.get("model", CHAT_MODEL)),
            "max_steps": int(state.get("max_steps", configured_limits.max_steps)),
            "max_tokens": int(state.get("max_tokens", configured_limits.max_tokens)),
            "max_retries": int(state.get("max_retries", configured_limits.max_retries)),
            "deadline_at": time.monotonic() + configured_limits.max_seconds,
            "next_node": "planner",
            "steps": 0,
            "tokens_used": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "retry_count": 0,
            "telemetry": [],
            "seen_attempt_keys": [],
            "errors": [],
            "chunks": [],
        }
    )
    configure_json_logging()
    compiled = build_graph(services, configured_limits)
    recursion_limit = max(20, configured_limits.max_steps * 4)
    with bind_run_id(run_id):
        result = compiled.invoke(initial, config={"recursion_limit": recursion_limit})
    final_state = dict(result)
    events = final_state.get("telemetry", [])
    final_state["telemetry"] = deduplicate_events(events)
    final_state["seen_attempt_keys"] = list(
        dict.fromkeys(final_state.get("seen_attempt_keys", []))
    )
    final_state["errors"] = list(dict.fromkeys(final_state.get("errors", [])))
    return final_state  # type: ignore[return-value]


async def run_workflow_async(
    state: RunState | dict[str, Any],
    *,
    checkpointer: Any,
    services: WorkflowServices | None = None,
    limits: WorkflowLimits | None = None,
    on_update: Callable[[RunState], Awaitable[None]] | None = None,
    resume: bool = False,
) -> RunState:
    """Run or resume a checkpointed workflow, publishing each committed state."""
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Workflow question must not be empty")
    configured_limits = limits or WorkflowLimits()
    run_id = str(state.get("run_id") or uuid4().hex)
    initial: dict[str, Any] = dict(state)
    initial.update(
        {
            "run_id": run_id,
            "question": question.strip(),
            "store_path": str(state.get("store_path", DEFAULT_STORE_PATH)),
            "top_k": int(state.get("top_k", 3)),
            "planner_model": str(state.get("planner_model", CHAT_MODEL)),
            "model": str(state.get("model", CHAT_MODEL)),
            "max_steps": int(state.get("max_steps", configured_limits.max_steps)),
            "max_tokens": int(state.get("max_tokens", configured_limits.max_tokens)),
            "max_retries": int(state.get("max_retries", configured_limits.max_retries)),
            "deadline_at": time.monotonic() + configured_limits.max_seconds,
            "next_node": "planner",
            "steps": 0,
            "tokens_used": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "retry_count": 0,
            "telemetry": [],
            "seen_attempt_keys": [],
            "errors": [],
            "chunks": [],
        }
    )
    configure_json_logging()
    compiled = build_graph(services, configured_limits, checkpointer=checkpointer)
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": max(20, configured_limits.max_steps * 4),
    }
    latest: dict[str, Any] = {}
    with bind_run_id(run_id):
        async for value in compiled.astream(
            None if resume else initial, config=config, stream_mode="values"
        ):
            latest = dict(value)
            if on_update is not None:
                await on_update(latest)  # type: ignore[arg-type]
    latest["telemetry"] = deduplicate_events(latest.get("telemetry", []))
    latest["seen_attempt_keys"] = list(
        dict.fromkeys(latest.get("seen_attempt_keys", []))
    )
    latest["errors"] = list(dict.fromkeys(latest.get("errors", [])))
    return latest  # type: ignore[return-value]
