# ADR-001: Centralized Tool Execution Boundary & Untrusted Evidence Delimitation

- **Status:** Accepted (Implemented in v0.1 / Milestone 1)
- **Date:** 2026-10-18
- **Decision Owners:** AegisFlow Core Team

## Context

Autonomous agent workflows allow LLMs to invoke operational tools (such as log search, runbook retrieval, service dependency lookup, and simulated configuration writes). Directly granting models execution capabilities or trusting raw model outputs introduces severe operational risks:
1. **Prompt Injection & Agent Hijacking:** Adversarial strings in retrieved corpus documents or user prompts can instruct the model to invoke destructive tools or bypass security constraints (OWASP Agentic Top 10: ASI01, ASI02).
2. **Malformed Arguments & Resource Exhaustion:** Stochastic models frequently generate invalid parameter types, excessive bounds, or traversal sequences (`../../etc/passwd`).
3. **Privilege Creep & Untracked Mutations:** Without central policy mediation and immutable audit logs, operational mutations cannot be verified, rate-limited, or approved by human operators.

## Decision

We adopt a strict enforcement architectural boundary:
**"Model proposes; executor enforces; automated tests verify."**

1. **Typed Tool Registry (`aegisflow.tools.registry`):**
   - Every operational tool is registered with strict Pydantic schemas enforcing `extra="forbid"`.
   - Explicit operational risk classification: `low` (read-only queries) vs `high` (configuration writes).
   - Hard execution timeouts bounded between 1.0s and 2.0s per tool call.
   - Declarative `requires_approval` flag for write operations.

2. **Centralized Policy Enforcement (`aegisflow.tools.executor`):**
   - Single linear execution pipeline: `Validate (Schema) -> Policy (Perms/Budgets) -> Timeout (Asyncio) -> Execute (Handler) -> Audit (Hash)`.
   - Operator policy defined declaratively in `policy.yaml` with global call budgets, per-tool enablement, and human approval overrides.
   - Models are permitted at most 1 schema retry upon argument failure before terminating with a typed error.

3. **Untrusted Evidence Delimitation:**
   - All retrieved documents, service logs, and tool outputs are strictly enclosed within `<UNTRUSTED_EVIDENCE>` tags.
   - Prompts explicitly instruct models that untrusted blocks contain passive data only, preventing goal hijacking.
   - Security checks (permissions, traversal guards, argument validity) are executed deterministically in Python code outside the LLM context.

4. **Hashed Audit Logging (`aegisflow.tools.audit`):**
   - SQLite append-only audit store (`ToolAuditStore`).
   - Sensitive arguments are never stored in plain text; SHA-256 digest hashes are persisted alongside timestamps, decisions, and execution durations.

## Consequences & Evaluation

- **Positive:**
  - Automated adversarial red team evaluation (20 injection patterns, 10 malicious traversal payloads, 5 resource exhaustion prompts across 5 repetitions) confirmed **0 policy bypasses (0.0% bypass rate)**.
  - Zero arbitrary code or shell execution tools exposed in the application.
  - Sub-millisecond policy check overhead (~0.15ms), completely negligible compared to model generation.
- **Negative / Trade-offs:**
  - Tools must be pre-declared and registered in Python code with Pydantic models; dynamic ad-hoc tool creation at runtime is prohibited.
  - High-risk actions require operator confirmation or external approval injection.
