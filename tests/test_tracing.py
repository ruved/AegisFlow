"""Tests for OpenTelemetry tracing and GenAI semantic conventions."""

from aegisflow.tracing import (
    build_trace_tree,
    clear_spans,
    trace_llm_call,
    trace_node,
    trace_retrieval,
    trace_tool_execution,
    trace_workflow_run,
)


def test_span_hierarchy_and_genai_semantic_attributes() -> None:
    clear_spans()
    run_id = "test-run-trace-1"

    # Simulate root workflow run with nested child spans
    with trace_workflow_run(run_id=run_id, question="What caused the outage?", top_k=3):
        with trace_node("planner", run_id=run_id):
            with trace_llm_call(
                model="gemma3:4b", schema_name="PlannerOutput"
            ) as llm_span:
                llm_span.set_attribute("gen_ai.usage.prompt_tokens", 42)
                llm_span.set_attribute("gen_ai.usage.completion_tokens", 18)
                llm_span.set_attribute("gen_ai.usage.total_tokens", 60)

        with trace_node("retrieve", run_id=run_id):
            with trace_retrieval(query="payment outage", k=3, store_path="chroma_db"):
                pass

        with trace_node("tool_node", run_id=run_id):
            with trace_tool_execution(
                tool_name="get_service_deps",
                risk="low",
                args_hash="abcdef123456",
                run_id=run_id,
            ) as tool_span:
                tool_span.set_attribute("tool.decision", "allow")
                tool_span.set_attribute("tool.outcome", "ok")

    tree = build_trace_tree(run_id)
    assert tree is not None
    assert tree["name"] == "workflow_run"
    assert tree["attributes"]["aegisflow.run_id"] == run_id
    assert tree["attributes"]["aegisflow.top_k"] == 3
    assert len(tree["children"]) == 3

    # Check child nodes
    planner_child = next(c for c in tree["children"] if c["name"] == "node:planner")
    assert len(planner_child["children"]) == 1
    llm_child = planner_child["children"][0]
    assert llm_child["name"] == "gen_ai.chat:gemma3:4b"
    assert llm_child["attributes"]["gen_ai.system"] == "ollama"
    assert llm_child["attributes"]["gen_ai.request.model"] == "gemma3:4b"
    assert llm_child["attributes"]["gen_ai.usage.prompt_tokens"] == 42
    assert llm_child["attributes"]["gen_ai.usage.completion_tokens"] == 18
    assert llm_child["attributes"]["gen_ai.usage.total_tokens"] == 60

    retrieve_child = next(c for c in tree["children"] if c["name"] == "node:retrieve")
    assert len(retrieve_child["children"]) == 1
    assert retrieve_child["children"][0]["name"] == "rag.retrieve"
    assert retrieve_child["children"][0]["attributes"]["retrieval.k"] == 3

    tool_child = next(c for c in tree["children"] if c["name"] == "node:tool_node")
    assert len(tool_child["children"]) == 1
    assert tool_child["children"][0]["name"] == "tool:get_service_deps"
    assert tool_child["children"][0]["attributes"]["tool.decision"] == "allow"


def test_trace_tree_returns_none_when_no_spans_found() -> None:
    clear_spans()
    assert build_trace_tree("non-existent-run") is None
