"""Prometheus metrics registry and collectors for AegisFlow observability.

Adheres strictly to low-cardinality label rules (no run IDs or question text).
Exposes /metrics endpoint for Prometheus scraping.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

__all__ = ["CONTENT_TYPE_LATEST", "REGISTRY", "get_latest_metrics"]

# Custom isolated registry to prevent duplicate registration in tests
REGISTRY = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# Metric Definitions
# ---------------------------------------------------------------------------

# 1. Per-node latency histogram (calibrated from W5-W6 latency observations)
NODE_LATENCY_SECONDS = Histogram(
    "aegisflow_node_duration_seconds",
    "Execution duration of individual workflow nodes in seconds",
    labelnames=["node"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=REGISTRY,
)

# 2. Queue depth and active runs gauges
ACTIVE_RUNS = Gauge(
    "aegisflow_active_runs",
    "Current number of workflow runs actively executing",
    registry=REGISTRY,
)

QUEUE_DEPTH = Gauge(
    "aegisflow_queue_depth",
    "Current number of workflow runs waiting or queued for execution",
    registry=REGISTRY,
)

# 3. Token usage counter by type ('prompt' or 'completion') and model name
TOKENS_TOTAL = Counter(
    "aegisflow_tokens_total",
    "Cumulative count of tokens processed by LLM calls",
    labelnames=["type", "model"],
    registry=REGISTRY,
)

# 4. Workflow retries / rewrites counter
WORKFLOW_RETRIES_TOTAL = Counter(
    "aegisflow_workflow_retries_total",
    "Cumulative count of workflow loop retries or subquestion rewrites",
    labelnames=["reason"],
    registry=REGISTRY,
)

# 5. Errors counter
ERRORS_TOTAL = Counter(
    "aegisflow_errors_total",
    "Cumulative count of unexpected errors across components",
    labelnames=["component", "error_type"],
    registry=REGISTRY,
)

# 6. Cache hits counter
CACHE_HITS_TOTAL = Counter(
    "aegisflow_cache_hits_total",
    "Cumulative count of cache hits",
    labelnames=["component"],
    registry=REGISTRY,
)

# 7. Tool execution metrics
TOOL_CALLS_TOTAL = Counter(
    "aegisflow_tool_calls_total",
    "Cumulative count of tool execution requests, decisions and outcomes",
    labelnames=["tool", "decision", "outcome"],
    registry=REGISTRY,
)

TOOL_DURATION_SECONDS = Histogram(
    "aegisflow_tool_duration_seconds",
    "Tool execution duration in seconds",
    labelnames=["tool"],
    buckets=[0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Convenience Recorders
# ---------------------------------------------------------------------------


def record_node_execution(
    node: str,
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit: bool = False,
    model: str = "unknown",
) -> None:
    """Record node latency, tokens, and cache events."""
    NODE_LATENCY_SECONDS.labels(node=node).observe(duration_seconds)
    if prompt_tokens > 0:
        TOKENS_TOTAL.labels(type="prompt", model=model).inc(prompt_tokens)
    if completion_tokens > 0:
        TOKENS_TOTAL.labels(type="completion", model=model).inc(completion_tokens)
    if cache_hit:
        CACHE_HITS_TOTAL.labels(component="workflow").inc()


def record_tool_call(
    tool: str,
    decision: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record tool invocation, policy decision, and duration."""
    TOOL_CALLS_TOTAL.labels(tool=tool, decision=decision, outcome=outcome).inc()
    TOOL_DURATION_SECONDS.labels(tool=tool).observe(duration_seconds)


def record_error(component: str, error_type: str) -> None:
    """Record an error occurrence."""
    ERRORS_TOTAL.labels(component=component, error_type=error_type).inc()


def record_retry(reason: str) -> None:
    """Record a workflow rewrite or retry."""
    WORKFLOW_RETRIES_TOTAL.labels(reason=reason).inc()


def get_latest_metrics() -> bytes:
    """Serialize all metrics in standard Prometheus text format."""
    return generate_latest(REGISTRY)
