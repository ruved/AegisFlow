# ADR-003: Add evidence sufficiency abstention

- **Status:** Provisional; E2 comparison is blocked by local inference stalls, and human calibration is pending
- **Date:** 2026-10-30
- **Decision owners:** AegisFlow project

## Context

Structured citations prove that a cited evidence ID was present in the prompt;
they do not prove that the evidence answers the question. AegisFlow needs a
separate sufficiency decision before generation. The verifier combines a
retrieval-score gate with a local judge and returns an abstention plus a short
list of missing information when the evidence is insufficient.

## Decision

Keep the verifier as the default API path, with a command-line `--no-verifier`
switch for matched evaluation. The initial score gates are maximum fused RRF
score >= 0.015 and best cosine distance <= 0.82. The judge is Qwen 3.5 4B, while
Gemma 3 4B generates answers. These values are starting points, not calibrated
production thresholds; the retrieval threshold curve and held-out results are
required before treating them as stable.

An abstained API response sets `abstained: true`, returns no citations, and
includes `missing` to describe the absent information. A refusal avoids making
an unsupported claim but reduces answer coverage, so both answerable coverage
and unanswerable refusal recall are reported.

## Evidence and remaining calibration

The model/index settings and exact command outcomes are recorded in
[`baseline_v2_config.json`](../results/baseline_v2_config.json). Full E1 answers
are saved in `results/baseline_E1_answer.csv`. E1 completed 41 questions: 30
successful generations and 11 structured-answer validation failures. Its
source Recall@3 was 0.500; citation precision was 0.200 and citation recall
0.111. The prompt-only system abstained on 8/10 unanswerable questions and on
0/31 answerable questions.

The retrieval-only threshold sweep shows why scores alone are insufficient.
At the initial RRF cutoff 0.015, all tuning-set unanswerables and 80% of held-
out unanswerables still passed the score gate. The held-out answerable evidence
hit rate was 0.500. These hit rates are retrieval proxies, not answer-correctness
grades. The sweep is plotted in [`abstention_tradeoff.svg`](../results/abstention_tradeoff.svg)
and recorded in `results/baseline_E1_answer_quality.json`.

The full E2 run and two 20-question stratified retries stalled without
producing an output CSV. The verifier prompt was shortened to the matched child
excerpt, but the retry still made no observable progress. A short standalone
structured judge request took about 90 seconds. Therefore E2
abstention/citation metrics and the 20-answer worksheet are not yet available;
do not interpret the E1 refusal rate as verifier performance.

**Calibration is not complete until the E2 run produces a review sheet, it has
20 binary human labels, and the resulting judge agreement (Cohen's kappa and raw
agreement) is recorded here.** The judge uses a different model family from the
answerer, but it can still be inconsistent or biased. Re-check thresholds on
held-out questions after tuning; do not select a threshold on the same questions
used to report final quality.

## Parent-child retrieval

Retain the 800/175 approximate-token parent/child configuration for this
iteration. The existing chunk-size comparison favored it as a context-size
tradeoff, while the new matched answer evaluation will supply the answer-level
evidence. Revisit this keep decision after the recorded E1/E2 outputs and
human-reviewed citation quality are available.
