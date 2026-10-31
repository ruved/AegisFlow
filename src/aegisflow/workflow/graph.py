"""LangGraph assembly and the single budget-aware conditional router."""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from aegisflow.workflow.models import BudgetExceeded
from aegisflow.workflow.nodes import (
    WorkflowCancelled,
    WorkflowLimits,
    WorkflowServices,
    build_nodes,
)
from aegisflow.workflow.state import RunState, TelemetryEvent

logger = logging.getLogger("aegisflow.workflow")
_ACTION_NODES = {
    "planner",
    "retrieve",
    "analyst",
    "reporter",
    "verifier",
    "rewriter",
    "finish",
    "abstain",
    "cancelled",
}


def sqlite_saver_context(path: Path) -> Any:
    """Create the supported async SQLite checkpointer context manager."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(path))


def instrument_node(
    name: str,
    function: Callable[[RunState], dict[str, Any]],
    *,
    count_step: bool = True,
) -> Callable[[RunState], dict[str, Any]]:
    """Time one node, aggregate token usage, and append one structured event."""

    def wrapped(state: RunState) -> dict[str, Any]:
        started = time.perf_counter()
        status = "ok"
        prompt_tokens = 0
        completion_tokens = 0
        tokens_estimated = False
        try:
            update = function(state)
        except BudgetExceeded as exc:
            status = "budget_exceeded"
            update = {
                "next_node": "abstain",
                "abstention_reason": str(exc),
                "missing": ["More token budget for the workflow step."],
            }
        except WorkflowCancelled:
            status = "cancelled"
            update = {"next_node": "cancelled", "cancelled": True}
        except Exception:
            status = "error"
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "workflow node failed",
                extra={
                    "node": name,
                    "duration_ms": round(duration_ms, 3),
                    "status": status,
                    "run_id": state.get("run_id", "-"),
                },
            )
            raise

        prompt_tokens = _as_nonnegative_int(update.pop("_prompt_tokens", 0))
        completion_tokens = _as_nonnegative_int(update.pop("_completion_tokens", 0))
        tokens_estimated = bool(update.pop("_tokens_estimated", False))
        cache_hit = bool(update.pop("_cache_hit", False))
        duration_ms = (time.perf_counter() - started) * 1000
        run_id = state.get("run_id", "-")
        event: TelemetryEvent = {
            "event_id": f"{run_id}:{name}:{state.get('steps', 0) + 1}",
            "run_id": run_id,
            "node": name,
            "duration_ms": round(duration_ms, 3),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_hit": cache_hit,
            "tokens_estimated": tokens_estimated,
            "status": status,
        }
        logger.info(
            "workflow node completed",
            extra={
                "node": name,
                "duration_ms": event["duration_ms"],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_hit": cache_hit,
                "status": status,
                "run_id": run_id,
            },
        )
        update["telemetry"] = [event]
        update["prompt_tokens"] = prompt_tokens
        update["completion_tokens"] = completion_tokens
        update["tokens_used"] = prompt_tokens + completion_tokens
        if count_step:
            update["steps"] = 1
        return update

    return wrapped


def build_graph(
    services: WorkflowServices | None = None,
    limits: WorkflowLimits | None = None,
    *,
    checkpointer: Any = None,
) -> Any:
    """Compile the graph; this is the sole module that imports LangGraph."""
    configured_limits = limits or WorkflowLimits()
    handlers = build_nodes(services or WorkflowServices(), configured_limits)
    graph = StateGraph(RunState)
    for node_name, handler in handlers.items():
        graph.add_node(
            node_name,
            cast(
                Any,
                instrument_node(node_name, handler, count_step=node_name != "guard"),
            ),
        )

    graph.add_edge(START, "guard")
    for node_name in _ACTION_NODES:
        if node_name not in {"finish", "abstain", "cancelled"}:
            graph.add_edge(node_name, "guard")
    graph.add_conditional_edges(
        "guard",
        _next_node,
        {node_name: node_name for node_name in _ACTION_NODES},
    )
    graph.add_edge("finish", END)
    graph.add_edge("abstain", END)
    graph.add_edge("cancelled", END)
    return graph.compile(checkpointer=checkpointer)


def _next_node(state: RunState) -> str:
    candidate = state.get("next_node", "planner")
    return candidate if candidate in _ACTION_NODES else "abstain"


def _as_nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0
