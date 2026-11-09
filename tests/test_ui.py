"""Tests for Streamlit UI helpers and citation offset highlighting."""

import sys
from pathlib import Path

# Add project root to sys.path so ui.app can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ui.app import AegisFlowClient, compute_offsets_and_highlight  # noqa: E402


def test_compute_offsets_and_highlight_exact_match() -> None:
    passage = (
        "The payment service timed out due to database connection pool exhaustion "
        "after failover."
    )
    claim = "database connection pool exhaustion"

    start, end, html = compute_offsets_and_highlight(passage, claim)

    assert start >= 0
    assert end > start
    assert passage[start:end].lower() == claim.lower()
    assert "<mark" in html
    assert claim in html
    # Ensure offsets match exact slice of passage
    assert passage[start:end] in passage


def test_compute_offsets_and_highlight_empty_claim_or_passage() -> None:
    start, end, html = compute_offsets_and_highlight("", "some claim")
    assert start == -1 and end == -1
    assert html == ""

    start, end, html = compute_offsets_and_highlight("passage text", "")
    assert start == -1 and end == -1
    assert html == "passage text"


def test_client_headers() -> None:
    client = AegisFlowClient("http://127.0.0.1:8000", api_key="secret-key")
    headers = client._headers(idempotency_key="test-key-1")
    assert headers["X-API-Key"] == "secret-key"
    assert headers["Idempotency-Key"] == "test-key-1"
    assert headers["Content-Type"] == "application/json"
