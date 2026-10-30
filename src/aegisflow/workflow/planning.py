"""Planner prompts and standalone validation helpers for the planner experiment."""

from aegisflow.workflow.schemas import PlannerOutput

PLANNER_SYSTEM = """You are a question planner for a technical incident knowledge base.
Return JSON matching the supplied schema. For a simple lookup set direct=true and
return no subquestions. For a multi-part question, split it into one to three
independent, answerable questions. Do not answer the question. Never create more
than three subquestions."""


def planner_prompt(question: str) -> str:
    return (
        "Examples:\n"
        'Question: "Which service owns payment reconciliation?"\n'
        'Plan: {"direct":true,"subquestions":[]}\n'
        'Question: "Why did the payment time out and what should responders do?"\n'
        'Plan: {"direct":false,"subquestions":["What caused the timeout?",'
        '"What should responders do for an uncertain payment?"]}\n\n'
        f"Question: {question}"
    )


def normalize_plan(plan: PlannerOutput, question: str) -> list[str]:
    """Use the original question for a direct plan and enforce the 1-3 bound."""
    if plan.direct:
        return [question]
    if not plan.subquestions:
        raise ValueError("A decomposed plan must contain at least one subquestion")
    return plan.subquestions[:3]
