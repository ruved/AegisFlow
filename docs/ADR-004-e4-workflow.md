# ADR-004: Typed workflow and E4 results

- **Status:** Accepted for experimentation; not promoted to the default answer path
- **Date:** 2026-10-31

## Context

Week 4 adds an optional LangGraph flow with a typed `RunState`, Pydantic node output
schemas, planner, retrieval worker, evidence-only analyst, reporter, verifier, one
rewrite attempt, and terminal abstention. The graph is bounded by step, token, retry,
and deadline guards. Node logs and returned telemetry carry `run_id`, duration, token
counts, and cache status. The public entry point is `run_workflow()`.

E1 is the existing direct-answer baseline. E4 was piloted on six matched golden-set
questions from `chroma_db_w3`: the first three `single_hop` cases (G001-G003) and the
first three `unanswerable` cases (G026-G028). Both paths used Gemma 3 4B. The workflow
used one planner call, then model-based analysis, reporting, and verification where
the evidence path reached those nodes. Its maximums were 14 steps, 6,000 reported
tokens, one rewrite, and 180 seconds per run. See the per-question events in
`results/E4_singlehop_pilot.csv` and `results/E4_unanswerable_pilot.csv`; each adjacent
JSON file records its run configuration and aggregates.

Task completion uses a strict rule: answerable cases count only when the workflow
returns a non-abstained report citing at least one gold source heading. An unanswerable
case counts as complete only when the workflow abstains. Citation precision and recall
use exact gold source-heading matches.
These are small pilot metrics, not human-graded answer correctness.

## Measurements

| Metric | E1 baseline | E4 workflow |
|---|---:|---:|
| Runs without execution failure | 6/6 | 6/6 |
| Answerable response / task completion | 3/3 non-abstained E1 responses | 0/3 gold-heading E4 completions |
| Unanswerable abstention | 3/3 | 2/3 |
| Answerable source-heading citation precision / recall | 0.250 / 0.333 (matched 3-question E1 sample) | 0.000 / 0.000 (same 3-question E4 sample) |
| Median latency on the six matched cases | 28,091.8 ms | 92,276.8 ms |
| Planner output schema validity | n/a | 15/15 (100%, dedicated planner sample) |

E4 median latency was 3.28 times E1 for this sample. Its mean per-node durations were
planner 9.0 s, retrieval 6.0 s, analyst 33.2 s, reporter 28.6 s, verifier 15.4 s,
rewriter 9.9 s (one retry), and under 1 ms per guard call. All model calls reported
actual Ollama token counts; no model call reported a cache hit. The workflow
retrieved an outdated runbook for G001 and returned a citation outside the gold source
set. It also answered G027, an unanswerable question, and the verifier accepted that
report. The rewrite path ran once on G026 and ended in abstention.

Planner schema validity was 15/15 (100%) on the deterministic sample of ten single-hop
and five multi-part questions, using Gemma 3 4B; mean planner latency was 9.06 s.
Per-question outputs and configuration are in `results/W4_planner_validity.csv` and
`results/W4_planner_validity.json`. This checks output shape and bounded normalization,
not whether each decomposition is semantically useful. The full 41-question E4
evaluation was not completed: at the measured pilot median it would require about
63 minutes of local inference, and the workflow already lost on completion and latency
in the sampled cases.

## Decision

Do not replace E1 or expose E4 as the default answer route. The pilot shows no answer
quality win: E4 had zero gold-source completions on answerable cases, refused only two
of three unanswerables, and took over three times longer by median latency. Keep the
workflow behind its adapter for focused engineering experiments; the typed state,
bounded routing, replay-safe telemetry, and forced-loop test are useful infrastructure,
but they are not evidence of better answers.

Before another quality comparison, simplify the path: bypass planning on straightforward
single-hop questions, avoid the reporter call when analysis has no supported findings,
and strengthen source-level verification so a retrieved outdated document cannot pass
as support. Then rerun a slice-balanced pilot and the full golden set only if the pilot
shows a credible quality improvement. Current result files are pilots only; no full-set
E4 quality claim is made.

## Consequences

- `run_workflow()` remains optional and the FastAPI `/ask` route continues to use E1.
- The evaluation runner saves per-question rows incrementally and supports `--limit`
  and `--slice` for explicitly labeled pilots.
- Current answerable citation failures and the unanswerable false acceptance are
  concrete targets for the next experiment.
- Full-set E4 completion, multi-part coverage, held-out results, and human grading
  remain unmeasured.
