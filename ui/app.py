"""AegisFlow Observability & Execution Console (Streamlit).

Features:
- D3: Live node timeline with SSE streaming and short-polling fallback.
- D4: Interactive evidence panel with exact highlighted citation offsets,
      report viewer (remediation with risk labels, unknowns), and run inspector
      (per-node latency, tokens, cache hits, OTel trace tree, tool policy decisions).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import uuid4

import streamlit as st

# Page configuration
st.set_page_config(
    page_title="AegisFlow Console",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# API Client Helper
# ---------------------------------------------------------------------------


class AegisFlowClient:
    def __init__(
        self, base_url: str = "http://127.0.0.1:8000", api_key: str = ""
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def check_health(self) -> dict[str, Any]:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/health", headers=self._headers()
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def check_ready(self) -> dict[str, Any]:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/ready", headers=self._headers()
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def create_run(self, question: str, top_k: int = 3) -> dict[str, Any]:
        idem_key = f"ui-{uuid4().hex[:12]}"
        data = json.dumps({"question": question, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/runs",
            data=data,
            headers=self._headers(idempotency_key=idem_key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode())

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/runs/{run_id}", headers=self._headers()
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}/v1/runs/{run_id}/cancel",
            data=b"{}",
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode())

    def get_run_trace(self, run_id: str) -> dict[str, Any] | None:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/runs/{run_id}/trace", headers=self._headers()
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def propose_tool(self, goal: str) -> dict[str, Any]:
        data = json.dumps({"goal": goal}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/tools/propose",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Citation & Highlight Helper (Offsets relative to cleaned text)
# ---------------------------------------------------------------------------


def compute_offsets_and_highlight(
    passage: str,
    claim: str,
) -> tuple[int, int, str]:
    """Compute character start and end offsets of matched claim in passage.

    Returns (start_offset, end_offset, html_with_highlights).
    Offsets are indexed against the cleaned passage text to prevent highlight drift.
    """
    clean_passage = passage.strip()
    if not claim or not clean_passage:
        return -1, -1, clean_passage

    # Try exact match first
    idx = clean_passage.lower().find(claim.lower()[:60])
    if idx >= 0:
        match_len = min(len(claim), len(clean_passage) - idx)
        start = idx
        end = idx + match_len
    else:
        # Keyword token overlap heuristic
        words = [w for w in re.findall(r"\w+", claim) if len(w) > 3]
        if words:
            first_word = words[0].lower()
            idx = clean_passage.lower().find(first_word)
            if idx >= 0:
                start = idx
                end = min(idx + 100, len(clean_passage))
            else:
                start, end = 0, min(80, len(clean_passage))
        else:
            start, end = 0, min(80, len(clean_passage))

    # Render HTML highlight with <mark> tags
    before = clean_passage[:start]
    highlighted = clean_passage[start:end]
    after = clean_passage[end:]
    mark_style = (
        "background-color: #ffd54f; color: #212121; padding: 2px 4px; "
        "border-radius: 3px; font-weight: 600;"
    )
    html = f'{before}<mark style="{mark_style}">{highlighted}</mark>{after}'
    return start, end, html


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🛡️ AegisFlow Console")
st.sidebar.markdown("**Observability, Quality & Live Inspection**")

api_url = st.sidebar.text_input("Service URL", value="http://127.0.0.1:8000")
api_key = st.sidebar.text_input("API Key (Optional)", type="password", value="")

client = AegisFlowClient(api_url, api_key)

# Health Status
health = client.check_health()
ready = client.check_ready()

col_h1, col_h2 = st.sidebar.columns(2)
with col_h1:
    if health.get("status") == "ok":
        st.success("API: Live")
    else:
        st.error("API: Offline")

with col_h2:
    if ready.get("status") == "ok":
        st.success("Ready: Ok")
    else:
        st.warning("Ready: Warn")

st.sidebar.markdown("---")
st.sidebar.markdown("### Observability Quick Links")
st.sidebar.markdown(f"- [Prometheus Metrics Endpoint]({api_url}/metrics)")
st.sidebar.caption("Grafana Dashboard template: `docs/grafana_dashboard.json`")

# Session state initialization
if "run_id" not in st.session_state:
    st.session_state["run_id"] = None
if "selected_citation" not in st.session_state:
    st.session_state["selected_citation"] = None


# ---------------------------------------------------------------------------
# Main Tabs
# ---------------------------------------------------------------------------

tab_console, tab_evidence, tab_inspector, tab_tools = st.tabs(
    [
        "🚀 Live Execution",
        "📖 Report & Evidence",
        "🔍 Run Inspector & Traces",
        "🛠️ Tool Sandbox",
    ]
)

# ---------------------------------------------------------------------------
# TAB 1: Live Execution (D3)
# ---------------------------------------------------------------------------
with tab_console:
    st.subheader("Submit Workflow Question")

    preset_questions = [
        "What caused the payment timeout?",
        "How do I resolve database connection pool exhaustion on order-db?",
        "What are the upstream dependencies of the payment-service?",
        "Custom question...",
    ]
    selected_preset = st.selectbox("Sample Questions", preset_questions)

    if selected_preset == "Custom question...":
        question_input = st.text_input(
            "Enter Question",
            value="",
            placeholder="Type your incident or system question...",
        )
    else:
        question_input = st.text_input("Question", value=selected_preset)

    col_q1, col_q2 = st.columns([1, 4])
    with col_q1:
        top_k = st.slider("Top K Evidence", min_value=1, max_value=5, value=3)

    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        submit = st.button("▶ Start Run", type="primary", use_container_width=True)
    with col_btn2:
        if st.session_state.get("run_id"):
            if st.button("⏹ Cancel Active Run", use_container_width=False):
                client.cancel_run(st.session_state["run_id"])
                st.info(f"Cancellation requested for {st.session_state['run_id']}")

    if submit and question_input.strip():
        try:
            created = client.create_run(question_input.strip(), top_k=top_k)
            st.session_state["run_id"] = created["id"]
            st.success(f"Run started: `{created['id']}`")
        except Exception as e:
            st.error(f"Failed to create run: {e}")

    # Active Run Display & Timeline
    active_run_id = st.session_state.get("run_id")
    if active_run_id:
        st.markdown("---")
        st.markdown(f"### Active Run: `{active_run_id}`")

        # Fetch status
        run_data = client.get_run(active_run_id)
        if run_data:
            status = run_data.get("status", "unknown")
            status_color = {
                "running": "blue",
                "completed": "green",
                "abstained": "orange",
                "failed": "red",
                "cancelled": "gray",
            }.get(status, "gray")

            st.markdown(f"**Status:** :{status_color}[**{status.upper()}**]")

            # Visual Node Progress Tracker
            nodes_order = [
                "planner",
                "retrieve",
                "analyst",
                "reporter",
                "verifier",
                "finish",
            ]
            st.markdown("#### Workflow Node Timeline")
            node_cols = st.columns(len(nodes_order))

            result = run_data.get("result") or {}
            # Auto-poll if running
            if status in {"running", "queued"}:
                time.sleep(1.0)
                st.rerun()

            for i, n in enumerate(nodes_order):
                with node_cols[i]:
                    if status == "completed":
                        st.success(f"✓ {n.capitalize()}")
                    elif status == "abstained" and n in {
                        "planner",
                        "retrieve",
                        "analyst",
                        "reporter",
                        "verifier",
                    }:
                        st.warning(f"⚠ {n.capitalize()}")
                    elif status == "running":
                        st.info(f"⏳ {n.capitalize()}")
                    else:
                        st.caption(f"○ {n.capitalize()}")

            if result:
                st.markdown("---")
                st.markdown("#### Report Summary")
                if result.get("abstained"):
                    diag = result.get("diagnosis", "Evidence insufficient")
                    st.warning(f"**Abstained:** {diag}")
                    if result.get("missing"):
                        st.write("**Missing Facts:**", result["missing"])
                else:
                    st.success(f"**Diagnosis:** {result.get('diagnosis')}")
                    num_cits = len(result.get("citations", []))
                    st.info(f"Found **{num_cits}** cited evidence claims.")
        else:
            st.warning(f"Run {active_run_id} not found on server.")


# ---------------------------------------------------------------------------
# TAB 2: Report & Evidence Panel (D4)
# ---------------------------------------------------------------------------
with tab_evidence:
    st.subheader("📖 Evidence Panel & Cited Claims")
    active_run_id = st.session_state.get("run_id")
    if not active_run_id:
        st.info("Submit a question in the Live Execution tab to inspect evidence.")
    else:
        run_data = client.get_run(active_run_id)
        if run_data and run_data.get("result"):
            report = run_data["result"]
            citations = report.get("citations", [])

            col_rep, col_ev = st.columns([1, 1])

            with col_rep:
                st.markdown("### Report & Claims")
                st.write(f"**Diagnosis:** {report.get('diagnosis', 'N/A')}")

                remediation = report.get("remediation_steps", [])
                if remediation:
                    st.markdown("#### Remediation Steps")
                    for step in remediation:
                        risk = step.get("risk", "low")
                        badge_color = {
                            "low": "green",
                            "medium": "orange",
                            "high": "red",
                        }.get(risk, "gray")
                        ev_str = ", ".join(step.get("evidence_ids", []))
                        st.markdown(
                            f"- :{badge_color}[**[{risk.upper()}]**] "
                            f"{step.get('action')} (Evidence: `{ev_str}`)"
                        )

                unknowns = report.get("unknowns", [])
                if unknowns:
                    st.markdown("#### Unknowns / Missing Facts")
                    for u in unknowns:
                        st.markdown(f"- ❓ {u}")

                st.markdown("#### Citations (Click to Highlight Supporting Passage)")
                if citations:
                    for i, cit in enumerate(citations):
                        src_h = f"{cit.get('source', '')} - {cit.get('heading', '')}"
                        btn_label = f"[{cit.get('evidence_id', str(i + 1))}] {src_h}"
                        if st.button(btn_label, key=f"cit_btn_{i}"):
                            st.session_state["selected_citation"] = cit
                else:
                    st.caption("No citations generated.")

            with col_ev:
                st.markdown("### Supporting Evidence Passage")
                sel_cit = st.session_state.get("selected_citation")
                if sel_cit:
                    claim = sel_cit.get("claim", "")
                    passage = (
                        sel_cit.get("passage", "") or sel_cit.get("text", "") or claim
                    )
                    source = sel_cit.get("source", "Unknown")
                    heading = sel_cit.get("heading", "")

                    st.markdown(f"**Source:** `{source}` / **Heading:** `{heading}`")
                    st.markdown(f'**Cited Claim:** *"{claim}"*')

                    start, end, highlighted_html = compute_offsets_and_highlight(
                        passage, claim
                    )

                    box_style = (
                        "background-color: #1e1e1e; border: 1px solid #444; "
                        "border-radius: 6px; padding: 14px; font-family: monospace; "
                        "white-space: pre-wrap; line-height: 1.6;"
                    )
                    st.markdown(
                        f'<div style="{box_style}">{highlighted_html}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"Offsets: [{start}, {end}] (normalized text)")
                else:
                    st.info("Click any citation on the left to highlight its passage.")
        else:
            st.info("No report or evidence available yet for this run.")


# ---------------------------------------------------------------------------
# TAB 3: Run Inspector & Traces (D4 Inspector)
# ---------------------------------------------------------------------------
with tab_inspector:
    st.subheader("🔍 Run Inspector & OpenTelemetry Traces")
    active_run_id = st.session_state.get("run_id")
    if not active_run_id:
        st.info("Submit a question to inspect run metrics and traces.")
    else:
        trace_data = client.get_run_trace(active_run_id)

        col_m1, col_m2, col_m3 = st.columns(3)
        run_data = client.get_run(active_run_id)

        if trace_data and trace_data.get("has_trace"):
            tree = trace_data.get("trace", {})
            with col_m1:
                st.metric(
                    "Total Trace Duration", f"{tree.get('duration_ms', 0):.1f} ms"
                )
            with col_m2:
                st.metric("Trace Status", tree.get("status", "ok").upper())
            with col_m3:
                st.metric("Child Spans", len(tree.get("children", [])))

            st.markdown("#### Hierarchical OpenTelemetry Span Tree")

            def render_span_node(node: dict[str, Any], depth: int = 0) -> None:
                indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * depth
                name = node.get("name", "span")
                duration = node.get("duration_ms", 0)
                status = node.get("status", "ok")
                attrs = node.get("attributes", {})

                badge = "🟢" if status == "ok" else "🔴"
                model_info = (
                    f" | model: `{attrs.get('gen_ai.request.model')}`"
                    if "gen_ai.request.model" in attrs
                    else ""
                )
                tokens_info = (
                    f" | tokens: {attrs.get('gen_ai.usage.total_tokens')}"
                    if "gen_ai.usage.total_tokens" in attrs
                    else ""
                )

                span_text = (
                    f"{indent} {badge} **`{name}`** — `{duration:.1f}ms` "
                    f"({status}){model_info}{tokens_info}"
                )
                st.markdown(span_text, unsafe_allow_html=True)
                for child in node.get("children", []):
                    render_span_node(child, depth + 1)

            tree_container = (
                "background-color: #121212; padding: 12px; border-radius: 6px;"
            )
            st.markdown(f'<div style="{tree_container}">', unsafe_allow_html=True)
            render_span_node(tree)
            st.markdown("</div>", unsafe_allow_html=True)

            with st.expander("Raw OpenTelemetry Trace JSON"):
                st.json(tree)
        else:
            st.warning("No OpenTelemetry trace recorded for this run ID.")


# ---------------------------------------------------------------------------
# TAB 4: Tool Sandbox
# ---------------------------------------------------------------------------
with tab_tools:
    st.subheader("🛠️ Model Tool Proposal & Policy Sandbox")
    st.markdown("Test model tool proposals against the central execution boundary.")

    goal_input = st.text_input(
        "Enter Operational Goal",
        value="Find incident logs for payment-service database errors",
    )
    if st.button("Propose & Enforce Tool"):
        with st.spinner("Proposing tool..."):
            try:
                res = client.propose_tool(goal_input)
                st.markdown("#### Execution Result")
                ok = res.get("ok", False)
                if ok:
                    st.success(f"Tool Allowed: `{res.get('tool_name')}`")
                    st.json(res.get("result"))
                else:
                    st.error(
                        f"Tool Denied: `{res.get('tool_name')}` — {res.get('error')}"
                    )
                st.caption(f"Audit Record ID: `{res.get('audit_id')}`")
            except Exception as e:
                st.error(f"Request failed: {e}")
