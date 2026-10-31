"""Checkpoint and cooperative cancellation behavior with deterministic services."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from aegisflow.workflow.models import StructuredCall
from aegisflow.workflow.nodes import WorkflowServices
from aegisflow.workflow.runner import run_workflow_async
from aegisflow.workflow.schemas import (
    AnalystOutput,
    Hypothesis,
    PlannerOutput,
    RemediationStep,
    ReporterOutput,
    VerifierOutput,
)


def _fake_model(**kwargs: Any) -> StructuredCall:
    schema = kwargs["schema"]
    if schema is PlannerOutput:
        value = PlannerOutput(direct=True)
    elif schema is AnalystOutput:
        value = AnalystOutput(
            relevant_evidence=True,
            hypotheses=[Hypothesis(text="Supported fact", evidence_ids=["1"])],
            unknowns=[],
        )
    elif schema is ReporterOutput:
        value = ReporterOutput(
            diagnosis="Supported fact",
            remediation_steps=[
                RemediationStep(
                    action="Check the source", risk="low", evidence_ids=["1"]
                )
            ],
            evidence_ids=["1"],
        )
    else:
        value = VerifierOutput(supported=True)
    return StructuredCall(value, 1, 1, False)


def test_checkpoint_resumes_after_transient_retrieval_failure(tmp_path: Path) -> None:
    async def exercise() -> None:
        saver_path = tmp_path / "checkpoints.sqlite3"
        async with AsyncSqliteSaver.from_conn_string(str(saver_path)) as saver:
            planner_calls = 0
            retrieval_calls = 0

            def model(**kwargs: Any) -> StructuredCall:
                nonlocal planner_calls
                if kwargs["schema"] is PlannerOutput:
                    planner_calls += 1
                return _fake_model(**kwargs)

            def transient_retrieve(*_: Any) -> list[dict[str, Any]]:
                nonlocal retrieval_calls
                retrieval_calls += 1
                if retrieval_calls == 1:
                    raise TimeoutError("injected retrieval timeout")
                return [
                    {
                        "chunk_id": "runbook::section-1",
                        "source": "runbook.md",
                        "heading": "Checks",
                        "text": "Check the source.",
                    }
                ]

            state = {"run_id": "resume-test", "question": "What is supported?"}
            with pytest.raises(TimeoutError, match="injected"):
                await run_workflow_async(
                    state,
                    checkpointer=saver,
                    services=WorkflowServices(
                        retrieve=transient_retrieve, structured_call=model
                    ),
                )
            result = await run_workflow_async(
                state,
                checkpointer=saver,
                services=WorkflowServices(
                    retrieve=transient_retrieve, structured_call=model
                ),
                resume=True,
            )
            assert planner_calls == 1
            assert retrieval_calls == 2
            assert result["terminal"] is True
            assert result["abstained"] is False

    asyncio.run(exercise())


def test_cancel_flag_stops_before_retrieval(tmp_path: Path) -> None:
    async def exercise() -> None:
        cancelled = False
        retrieval_calls = 0

        def model(**kwargs: Any) -> StructuredCall:
            nonlocal cancelled
            if kwargs["schema"] is PlannerOutput:
                cancelled = True
            return _fake_model(**kwargs)

        def retrieve(*_: Any) -> list[dict[str, Any]]:
            nonlocal retrieval_calls
            retrieval_calls += 1
            return []

        async with AsyncSqliteSaver.from_conn_string(
            str(tmp_path / "cancel.sqlite3")
        ) as saver:
            result = await run_workflow_async(
                {"run_id": "cancel-test", "question": "Cancel after planning"},
                checkpointer=saver,
                services=WorkflowServices(
                    retrieve=retrieve,
                    structured_call=model,
                    is_cancelled=lambda _run_id: cancelled,
                ),
            )
        assert result["cancelled"] is True
        assert retrieval_calls == 0

    asyncio.run(exercise())
