"""Runtime-validated inputs and outputs for workflow nodes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerOutput(StrictModel):
    """A bounded plan; direct questions can omit subquestions."""

    direct: bool
    subquestions: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("subquestions")
    @classmethod
    def normalize_subquestions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Subquestions must not be blank")
        return list(dict.fromkeys(normalized))


class Hypothesis(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class AnalystOutput(StrictModel):
    """Evidence-backed hypotheses and an explicit list of unknowns."""

    relevant_evidence: bool
    hypotheses: list[Hypothesis] = Field(max_length=8)
    unknowns: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_findings(self) -> "AnalystOutput":
        if self.relevant_evidence and not self.hypotheses:
            raise ValueError("Relevant evidence requires at least one hypothesis")
        if not self.relevant_evidence and not self.unknowns:
            raise ValueError("An evidence gap must identify at least one unknown")
        return self


class RemediationStep(StrictModel):
    action: str = Field(min_length=1, max_length=500)
    risk: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)


class ReporterOutput(StrictModel):
    """User-facing diagnosis, risk-labelled remediation, and remaining unknowns."""

    diagnosis: str = Field(min_length=1, max_length=1500)
    remediation_steps: list[RemediationStep] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class VerifierOutput(StrictModel):
    """Verifier decision with an explicit bounded-retry signal."""

    supported: bool
    retry_with_rewrite: bool = False
    issues: list[str] = Field(default_factory=list, max_length=8)
    missing: list[str] = Field(default_factory=list, max_length=8)


class RewriteOutput(StrictModel):
    """A retry plan capped at three rewritten questions."""

    direct: bool
    subquestions: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("subquestions")
    @classmethod
    def normalize_subquestions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Subquestions must not be blank")
        return list(dict.fromkeys(normalized))


class Citation(StrictModel):
    evidence_id: str
    chunk_id: str
    source: str
    heading: str | None = None


class WorkflowReport(StrictModel):
    """Validated public result shared by successful and abstained runs."""

    diagnosis: str
    remediation_steps: list[RemediationStep] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    missing: list[str] = Field(default_factory=list)
