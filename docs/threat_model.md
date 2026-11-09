# AegisFlow threat model (Week 6)

## Scope and assumptions

This is a single-machine, local-first prototype. The model, retrieved corpus, request
body, and tool proposals are untrusted. The registry exposes bounded read-only
lookups and simulated metrics; a simulated write exists only to exercise approval
policy and never changes a system. There is no arbitrary shell, network, SQL, or
filesystem tool. API authentication uses `AEGISFLOW_API_KEY` for non-health routes;
without it, non-loopback clients are rejected. Reverse proxies must not be treated as
trusted loopback clients unless the key is configured.

The mapping follows the [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/).
Controls reduce risk; they do not make prompt injection impossible.

| OWASP risk | Relevance and implemented control | Status / boundary |
|---|---|---|
| ASI01 Agent Goal Hijack | Retrieved passages are delimited as untrusted data; common instruction-like patterns are flagged. Tool permissions are enforced outside model prompts. | Mitigated at executor boundary; prompt flagging is bypassable. |
| ASI02 Tool Misuse & Exploitation | Allowlisted typed registry; Pydantic validation; central timeout, risk and approval policy; no arbitrary commands. | Implemented for registered tools. |
| ASI03 Identity & Privilege Abuse | Optional API key required for remote clients; tools run with the local process identity and have no separate credentials. | Partial. Do not run with a privileged OS identity. |
| ASI04 Agentic Supply Chain Vulnerabilities | Dependencies are pinned by `uv.lock`; tool implementations are in-repo, with no dynamic MCP/plugin loading. | Partial; dependency review and artifact provenance are manual. |
| ASI05 Unexpected Code Execution | No model-generated code or shell tool is available; every action resolves to a registry handler. | Implemented for the tool surface. Python process and dependency vulnerabilities remain in scope. |
| ASI06 Memory & Context Poisoning | Retrieved content is treated as data and flagged; checkpoints preserve workflow state only. | Partial; corpus ingestion trust and checkpoint integrity are not independently attested. |
| ASI07 Insecure Inter-Agent Communication | The current workflow has no agent-to-agent messaging or delegation. | Out of scope. |
| ASI08 Cascading Failures | Step, token, deadline, per-request, retrieval-count, and tool-timeout bounds limit individual work. | Partial; no distributed queue, global rate limiter, or multi-worker circuit breaker. |
| ASI09 Human-Agent Trust Exploitation | Reports carry evidence citations and unknowns; risky simulated writes require an approval boolean from the host caller. | Partial; there is no human approval UI or verified approval identity. |
| ASI10 Rogue Agents | Tool proposals are initiated by a user request, executor policy is deterministic, and workflow routing is bounded with persisted events. | Unbounded autonomous planning and tool chains are out of scope. |

## Audit and data handling

Every executor attempt records run ID, tool name, a SHA-256 digest of canonicalized
arguments, risk, allow/deny decision, outcome, and time. Raw arguments and tool results
are not stored in the audit table. JSON workflow log messages redact common API-key,
bearer-token, AWS access-key, and email patterns. This is pattern-based redaction and
does not detect every secret or all forms of personal data; never log raw prompts,
retrieved content, credentials, or unredacted tool arguments.

The red-team runner exercises 20 injection strings, 10 malformed or malicious argument
cases, and 5 oversized resource inputs, repeated five times. It measures executor
policy bypasses. In addition, an optional model-loop mode (`--model-loop`) sends
adversarial goals to the model to measure text-level compliance separately from
executor policy bypasses. Declarative execution budgets and per-tool rules in
`policy.yaml` provide defense-in-depth against DoS and unauthorized tool execution.

Run `uv run python evals/run_red_team.py --runs 5` for deterministic evaluation, or
add `--model-loop` to test model text compliance with Ollama. Both report zero
executor policy bypasses.
