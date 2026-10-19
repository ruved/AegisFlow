# Local Model Evaluation — AegisFlow

**Evaluation date:** 2026-10-19  
**Ollama version:** 0.40.6  
**Hardware:** Intel Core i7-1360P, 12 cores / 16 logical processors, 13.73 GB RAM, Intel Iris Xe integrated graphics  
**Execution:** Local Ollama; models ran on CPU according to `ollama ps`

## Chat model comparison

Results below use three measured trials per model. Latency and generation speed are medians.

| Model | Median wall latency | Median generation speed | Correct structured outputs |
|---|---:|---:|---:|
| Gemma 3 4B | 4.97 s | 13.76 tokens/s | 3/3 |
| Qwen 3.5 4B Q4_K_M | 6.57 s | 11.75 tokens/s | 3/3 |
| Llama 3.1 8B | 6.47 s | 8.15 tokens/s | 3/3 |

Qwen was benchmarked with thinking disabled. Its settings differ from the other models, so results are not a perfectly controlled comparison.

The benchmark measures a small tool-selection task, not general reasoning quality or production workflow success. Three trials are useful for an initial decision but insufficient for strong statistical conclusions.

## Embedding model

- Model: `nomic-embed-text:latest`
- Measured wall time: 3.81 seconds
- Vector dimensions: 768
- Successful response: Yes
- Sample count: One; timing may include model initialization.

## Concurrency test

Two simultaneous requests were sent to `llama3.1:8b`.

- Schema-valid responses: 2/2
- Correct tool selections: 2/2
- Combined wall time: 26.038 seconds
- Individual request times: 25.931 seconds and 20.868 seconds

Both requests completed correctly, but latency was high. This does not establish production concurrency capacity.

## Gemma context test

| Context setting | Wall time | Output tokens | Completion | Sampled peak Ollama working set |
|---|---:|---:|---|---:|
| 4096 | 10.68 s | 35 | stop | 26 MB |
| 8192 | 14.22 s | 35 | stop | 29 MB |

Both requests succeeded. The 8192 run took about 33% longer in this test.

The prompt did not necessarily fill either context window, so this test does not establish effective long-context retrieval or reasoning quality.

**Memory measurement caveat:** working-set values are approximate process samples and appear too low to represent the full model runtime. They must not be treated as total model memory consumption.

## Initial decision

Use `gemma3:4b` as the initial local orchestration model because it had the lowest median latency and highest median generation speed in this small test, while producing correct structured outputs in all three measured trials.

Use `num_ctx=4096` as the initial context setting. Re-evaluate when representative workflows, longer prompts, and a larger evaluation dataset are available.

Use `nomic-embed-text:latest` for the initial embedding experiments, subject to retrieval-quality evaluation.

## Next evaluation work

1. Evaluate a fixed set of representative workflows, not just one tool-selection prompt.
2. Measure task success, invalid outputs, latency, and failure recovery across repeated trials.
3. Test retrieval quality with labeled queries before selecting chunking and retrieval defaults.
4. Improve memory measurement by monitoring the relevant Ollama/model-server process and comparing system memory before, during, and after inference.
5. Test context use with prompts containing known information near the beginning and end of the input.
6. Re-run the benchmark after changing model versions or inference settings.
