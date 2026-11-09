"""OpenTelemetry distributed tracing for AegisFlow runs, nodes, models and tools.

Provides:
- In-memory and console span export.
- Asynchronous context propagation linking root workflow runs to node, LLM,
  retrieval, and tool spans.
- GenAI semantic conventions for LLM inference (model, token usage).
- Trace tree generation for inspection via API and UI.
"""

from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Span, Status, StatusCode

logger = logging.getLogger("aegisflow.tracing")

CURRENT_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aegisflow_current_run_id", default=""
)

# Global in-memory exporter for inspecting recent traces
_IN_MEMORY_EXPORTER = InMemorySpanExporter()
_TRACER_PROVIDER: TracerProvider | None = None


def setup_tracing(service_name: str = "aegisflow") -> TracerProvider:
    """Initialize OpenTelemetry tracer provider with in-memory exporter."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER

    resource = Resource.create(
        {"service.name": service_name, "service.version": "0.1.0"}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_IN_MEMORY_EXPORTER))

    if os.environ.get("AEGISFLOW_OTEL_CONSOLE", "").strip() in {"1", "true", "yes"}:
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        except Exception:
            logger.warning("Could not initialize ConsoleSpanExporter")

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    return provider


def get_tracer(name: str = "aegisflow") -> trace.Tracer:
    """Return an OpenTelemetry tracer, initializing the provider if needed."""
    if _TRACER_PROVIDER is None:
        setup_tracing()
    return trace.get_tracer(name)


def get_span_exporter() -> InMemorySpanExporter:
    """Return the in-memory span exporter used for tests and inspections."""
    if _TRACER_PROVIDER is None:
        setup_tracing()
    return _IN_MEMORY_EXPORTER


def clear_spans() -> None:
    """Clear recorded spans from the in-memory exporter."""
    _IN_MEMORY_EXPORTER.clear()


# ---------------------------------------------------------------------------
# Context Managers for Instrumentation
# ---------------------------------------------------------------------------


@contextmanager
def trace_workflow_run(
    run_id: str,
    question: str,
    top_k: int = 3,
) -> Iterator[Span]:
    """Create root span for a managed workflow run."""
    tracer = get_tracer()
    token = CURRENT_RUN_ID.set(run_id)
    with tracer.start_as_current_span(
        name="workflow_run",
        attributes={
            "aegisflow.run_id": run_id,
            "aegisflow.question": question[:200],
            "aegisflow.top_k": top_k,
        },
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            CURRENT_RUN_ID.reset(token)


@contextmanager
def trace_node(
    node_name: str,
    run_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Create a child span for a workflow node."""
    tracer = get_tracer()
    active_run_id = run_id or CURRENT_RUN_ID.get()
    attrs: dict[str, Any] = {
        "workflow.node": node_name,
        "aegisflow.run_id": active_run_id,
    }
    if attributes:
        attrs.update(attributes)

    with tracer.start_as_current_span(
        name=f"node:{node_name}",
        attributes=attrs,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def trace_llm_call(
    model: str,
    schema_name: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Create a span conforming to GenAI semantic conventions."""
    tracer = get_tracer()
    run_id = CURRENT_RUN_ID.get()
    attrs: dict[str, Any] = {
        "gen_ai.system": "ollama",
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": model,
        "gen_ai.response.format": schema_name,
        "aegisflow.run_id": run_id,
    }
    if attributes:
        attrs.update(attributes)

    with tracer.start_as_current_span(
        name=f"gen_ai.chat:{model}",
        attributes=attrs,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def trace_retrieval(
    query: str,
    k: int,
    store_path: str = "",
) -> Iterator[Span]:
    """Create a span for semantic and lexical document retrieval."""
    tracer = get_tracer()
    run_id = CURRENT_RUN_ID.get()
    attrs: dict[str, Any] = {
        "retrieval.query": query[:200],
        "retrieval.k": k,
        "retrieval.store_path": str(store_path),
        "aegisflow.run_id": run_id,
    }
    with tracer.start_as_current_span(
        name="rag.retrieve",
        attributes=attrs,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def trace_tool_execution(
    tool_name: str,
    risk: str,
    args_hash: str,
    run_id: str = "",
) -> Iterator[Span]:
    """Create a span for security tool execution."""
    tracer = get_tracer()
    active_run_id = run_id or CURRENT_RUN_ID.get()
    attrs: dict[str, Any] = {
        "tool.name": tool_name,
        "tool.risk": risk,
        "tool.args_hash": args_hash,
        "aegisflow.run_id": active_run_id,
    }
    with tracer.start_as_current_span(
        name=f"tool:{tool_name}",
        attributes=attrs,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


# ---------------------------------------------------------------------------
# Trace Tree Representation
# ---------------------------------------------------------------------------


@dataclass
class SpanNode:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    start_time_ns: int
    end_time_ns: int
    duration_ms: float
    status: str
    attributes: dict[str, Any]
    children: list[SpanNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "children": [c.to_dict() for c in self.children],
        }


def get_spans_for_run(run_id: str) -> list[ReadableSpan]:
    """Filter all recorded in-memory spans matching a specific run_id."""
    spans = _IN_MEMORY_EXPORTER.get_finished_spans()
    matched: list[ReadableSpan] = []
    for s in spans:
        attrs = dict(s.attributes or {})
        if attrs.get("aegisflow.run_id") == run_id:
            matched.append(s)
    return matched


def build_trace_tree(run_id: str) -> dict[str, Any] | None:
    """Build a hierarchical span tree for the given run_id.

    Returns the root SpanNode dictionary with nested children, or None.
    """
    raw_spans = get_spans_for_run(run_id)
    if not raw_spans:
        return None

    nodes: dict[str, SpanNode] = {}
    for s in raw_spans:
        ctx = s.get_span_context()
        if ctx is None:
            continue
        span_id = f"{ctx.span_id:016x}"
        trace_id = f"{ctx.trace_id:032x}"
        parent_id = f"{s.parent.span_id:016x}" if s.parent is not None else None

        duration_ms = (
            (s.end_time - s.start_time) / 1_000_000.0
            if (s.end_time and s.start_time)
            else 0.0
        )
        status_name = s.status.status_code.name.lower() if s.status else "unset"

        attrs = {
            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
            for k, v in (s.attributes or {}).items()
        }

        nodes[span_id] = SpanNode(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_id,
            name=s.name,
            start_time_ns=s.start_time or 0,
            end_time_ns=s.end_time or 0,
            duration_ms=duration_ms,
            status=status_name,
            attributes=attrs,
            children=[],
        )

    # Link children to parents
    roots: list[SpanNode] = []
    for node in nodes.values():
        if node.parent_span_id and node.parent_span_id in nodes:
            nodes[node.parent_span_id].children.append(node)
        else:
            roots.append(node)

    # Sort children by start time
    for node in nodes.values():
        node.children.sort(key=lambda c: c.start_time_ns)
    roots.sort(key=lambda r: r.start_time_ns)

    if not roots:
        return None

    # If single root (ideal case), return it; if multiple, return a synthetic container
    if len(roots) == 1:
        return roots[0].to_dict()

    return {
        "span_id": "root-container",
        "trace_id": roots[0].trace_id if roots else "",
        "parent_span_id": None,
        "name": f"workflow_trace:{run_id}",
        "duration_ms": round(sum(r.duration_ms for r in roots), 2),
        "status": "ok",
        "attributes": {"aegisflow.run_id": run_id, "root_count": len(roots)},
        "children": [r.to_dict() for r in roots],
    }
