"""Bounded workflow contracts and routing behavior."""

import json
import logging
from typing import Any

import pytest

from aegisflow.workflow.graph import _next_node
from aegisflow.workflow.logging_setup import (
    JsonRunFormatter,
    bind_run_id,
    configure_json_logging,
)
from aegisflow.workflow.models import StructuredCall
from aegisflow.workflow.nodes import WorkflowLimits, WorkflowServices, build_nodes
from aegisflow.workflow.planning import normalize_plan
from aegisflow.workflow.runner import run_workflow
from aegisflow.workflow.schemas import (
    AnalystOutput,
    Hypothesis,
    PlannerOutput,
    RemediationStep,
    ReporterOutput,
    VerifierOutput,
    WorkflowReport,
)


def test_plan_is_direct_or_capped_and_validated() -> None:
    assert normalize_plan(PlannerOutput(direct=True), "original") == ["original"]
    plan = PlannerOutput(
        direct=False,
        subquestions=[" first ", "second", "third"],
    )
    assert normalize_plan(plan, "original") == ["first", "second", "third"]


def test_budget_stops_workflow_cleanly_and_logs_run_id(caplog: Any) -> None:
    configure_json_logging()
    with (
        caplog.at_level(logging.INFO, logger="aegisflow.workflow"),
        bind_run_id("test-run"),
    ):
        final = run_workflow(
            {"question": "unanswerable?", "run_id": "test-run"},
            limits=WorkflowLimits(max_steps=1, max_tokens=1000, max_seconds=5),
        )
    assert final["abstained"] is True
    assert final["report"]["missing"]
    events = final["telemetry"]
    assert [event["node"] for event in events] == [
        "guard",
        "planner",
        "guard",
        "abstain",
    ]
    assert all(event["duration_ms"] >= 0 for event in events)
    formatter = JsonRunFormatter()
    parsed = [json.loads(formatter.format(record)) for record in caplog.records]
    assert all(entry["run_id"] == "test-run" for entry in parsed)


def test_fake_services_produce_a_valid_cited_report() -> None:
    def fake_model(**kwargs: Any) -> StructuredCall:
        schema = kwargs["schema"]
        if schema is PlannerOutput:
            value = PlannerOutput(direct=True)
        elif schema is AnalystOutput:
            value = AnalystOutput(
                relevant_evidence=True,
                hypotheses=[
                    Hypothesis(
                        text="The pool reached its configured limit.",
                        evidence_ids=["1"],
                    )
                ],
                unknowns=[],
            )
        elif schema is ReporterOutput:
            value = ReporterOutput(
                diagnosis="The pool reached its configured limit.",
                remediation_steps=[
                    RemediationStep(
                        action="Inspect active and idle connections.",
                        risk="low",
                        evidence_ids=["1"],
                    )
                ],
                evidence_ids=["1"],
            )
        else:
            value = VerifierOutput(supported=True)
        return StructuredCall(
            value=value,
            prompt_tokens=5,
            completion_tokens=5,
            tokens_estimated=False,
        )

    services = WorkflowServices(
        retrieve=lambda *_: [
            {
                "chunk_id": "runbooks/RB-1.md::parent-1",
                "source": "runbooks/RB-1.md",
                "heading": "Triage",
                "text": "Inspect active and idle connections.",
            }
        ],
        structured_call=fake_model,
    )
    final = run_workflow(
        {"question": "What should responders inspect?"}, services=services
    )
    report = WorkflowReport.model_validate(final["report"])
    assert report.abstained is False
    assert report.citations[0].source == "runbooks/RB-1.md"


def test_routing_rejects_unknown_node() -> None:
    assert _next_node({"next_node": "not-a-node"}) == "abstain"  # type: ignore[typeddict-item]


def test_loop_detection_abstains_on_same_question_and_evidence() -> None:
    chunk = {"evidence_id": "1", "chunk_id": "chunk-a", "source": "doc.md"}
    from aegisflow.workflow.nodes import _attempt_signature

    signature = _attempt_signature(["same question"], [chunk])

    def unused_model(**_: Any) -> Any:
        raise AssertionError("verifier must reject a repeated evidence attempt")

    verifier = build_nodes(
        WorkflowServices(structured_call=unused_model), WorkflowLimits()
    )["verifier"]
    result = verifier(
        {
            "question": "same question",
            "subquestions": ["same question"],
            "chunks": [chunk],
            "reporter_output": ReporterOutput(
                diagnosis="Diagnosis", evidence_ids=["1"]
            ).model_dump(),
            "seen_attempt_keys": [signature],
        }
    )
    assert result["next_node"] == "abstain"
    assert result["loop_detected"] is True


def test_verifier_output_schema_is_bounded() -> None:
    output = VerifierOutput(supported=False, missing=["current metrics"])
    assert output.missing == ["current metrics"]


def test_analyst_must_state_relevance_and_cannot_return_empty_findings() -> None:
    with pytest.raises(ValueError, match="requires at least one hypothesis"):
        AnalystOutput(relevant_evidence=True, hypotheses=[], unknowns=[])
    unknown = AnalystOutput(
        relevant_evidence=False,
        hypotheses=[],
        unknowns=["The incident timestamp is not in the retrieved passages."],
    )
    assert unknown.relevant_evidence is False
