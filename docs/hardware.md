# Development Hardware

- OS and version: Windows 11 Home Single Language, 10.0.26200
- Python version: 3.12.4
- CPU model: Intel Core i7-1360P
- CPU cores / logical processors: 12 / 16
- System RAM: 13.73 GB
- GPU model and vendor: Intel Iris Xe Graphics
- Dedicated VRAM: Not verified; integrated graphics
- Free disk space: C: 123.68 GB; D: 312.47 GB (at last check)
- Ollama version: 0.40.5
- Model tested and tag: qwen3.5:4b-q4_K_M
- Model quantization (if known): Q4_K_M, based on the model tag
- Test date: 2026-10-19

## Observations
- Did the model load and answer? Yes; generated a response to the tool-use test prompt.
- Was GPU acceleration visible / available? Not verified.
- Approximate response latency and test prompt: Latency not measured. Prompt asked how to select a tool, validate arguments, execute it, and handle errors.
- Any memory, disk, or driver constraints: No disk-space blocker identified. Runtime memory usage not measured.
- Follow-up needed: Measure latency and memory; inspect GPU utilization; test tool calling through the Ollama API.
