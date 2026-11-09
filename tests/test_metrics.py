"""Tests for Prometheus metrics collection and HTTP scraping."""

from pathlib import Path

from fastapi.testclient import TestClient

from aegisflow import api
from aegisflow.metrics import (
    get_latest_metrics,
    record_error,
    record_node_execution,
    record_retry,
    record_tool_call,
)


def test_metrics_collection_and_no_high_cardinality_labels() -> None:
    # Record representative events
    record_node_execution(
        "planner", 0.35, prompt_tokens=100, completion_tokens=50, model="gemma3:4b"
    )
    record_node_execution("retrieve", 0.08, cache_hit=True)
    record_tool_call("search_logs", "allow", "ok", 0.05)
    record_error("workflow", "timeout")
    record_retry("verifier_rewrite")

    output = get_latest_metrics().decode("utf-8")

    # Confirm required metric families exist
    assert "aegisflow_node_duration_seconds" in output
    assert "aegisflow_tokens_total" in output
    assert "aegisflow_cache_hits_total" in output
    assert "aegisflow_tool_calls_total" in output
    assert "aegisflow_errors_total" in output
    assert "aegisflow_workflow_retries_total" in output
    assert "aegisflow_active_runs" in output
    assert "aegisflow_queue_depth" in output

    # Check safe low-cardinality labels
    assert 'node="planner"' in output
    assert 'type="prompt"' in output
    assert 'model="gemma3:4b"' in output
    assert 'tool="search_logs"' in output
    assert 'decision="allow"' in output

    # Ensure NO high-cardinality labels exist (no run_id or raw questions)
    for line in output.splitlines():
        if line.startswith("#"):
            continue
        assert "run_id=" not in line, (
            f"Found high-cardinality label run_id in metric: {line}"
        )
        assert "question=" not in line, (
            f"Found high-cardinality label question in metric: {line}"
        )


def test_metrics_endpoint_public_and_trace_endpoint(tmp_path: Path) -> None:
    api.app.state.run_db_path = tmp_path / "runs.sqlite3"
    api.app.state.checkpoint_path = tmp_path / "checkpoints.sqlite3"
    api.app.state.tool_audit_path = tmp_path / "audit.sqlite3"

    with TestClient(api.app) as client:
        # /metrics is publicly scrapable without API key
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "aegisflow_" in response.text
        assert response.headers["content-type"].startswith("text/plain")

        # /v1/runs/{run_id}/trace returns 404 for unknown run
        trace_resp = client.get("/v1/runs/non-existent-run/trace")
        assert trace_resp.status_code == 404
