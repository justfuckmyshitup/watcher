# POC Benchmarking

Phase 5 proves whether Local Scribe is ready for a real RTX 3060-class demo.

Run the benchmark:

```powershell
.\scripts\benchmark-poc.ps1 -RequireGpu -AllowIncomplete
```

Live target run, after runtime packages and models are installed:

```powershell
.\scripts\benchmark-poc.ps1 `
  -OcrProvider paddle `
  -OcrProfile screen-fast `
  -ModelProvider onnx-phi `
  -RequireGpu `
  -Offline
```

Reports are written under `app-data/benchmarks/` as JSON and Markdown. They are ignored by git.

## What The Benchmark Measures

- NVIDIA GPU hardware and VRAM proof.
- Python GPU provider readiness.
- OCR provider readiness, latency, line count, and temp cleanup.
- LLM provider readiness, generation latency, and approximate output tokens/sec.
- Offline model-file readiness.
- Privacy regression corpus.
- Whether raw frame or OCR-cycle temp files remain after cleanup.

The benchmark does not persist raw screenshots. Synthetic OCR images are generated in memory and discarded. Reports store timings, provider metadata, hashes, and pass/fail status.

## Current Live Runtime Gate

The POC requires:

- Python 3.12 or 3.13 for the live GPU OCR/LLM environment.
- `paddlepaddle-gpu` plus `paddleocr` for PaddleOCR.
- `onnxruntime-genai-cuda` for the ONNX Phi provider.
- The local Hugging Face model files downloaded with `scripts/download-models.ps1`.

Check/setup helper:

```powershell
.\scripts\setup-live-poc.ps1
```

If Python 3.12 is not installed, install it manually:

```powershell
winget install -e --id Python.Python.3.12
```

Then recreate the repo-local environment and install runtime packages:

```powershell
.\scripts\setup-live-poc.ps1 -ForceRecreateVenv -InstallRuntimePackages -DownloadModels
```

This script installs only repo-local Python packages and model files. It does not install system-level dependencies such as Python, Node.js, NVIDIA drivers, CUDA Toolkit, Docker Desktop, Ollama, LM Studio, or Tesseract.

## Acceptance

For a real POC demo, the benchmark should show:

- GPU hardware detected.
- GPU inference provider ready.
- OCR benchmark status `ok` on `paddle`.
- LLM benchmark status `ok` on `onnx-phi`.
- Privacy regression passed.
- No raw frame temp files remaining.
- Offline model files ready.

## Latest Target-Machine Result

Latest live run:

```powershell
.\scripts\benchmark-poc.ps1 `
  -OcrProvider paddle `
  -OcrProfile screen-fast `
  -ModelProvider onnx-phi `
  -RequireGpu `
  -Offline `
  -AllowIncomplete `
  -Iterations 1
```

Report:

- JSON: `app-data/benchmarks/poc-benchmark-20260503-032852.json`
- Markdown: `app-data/benchmarks/poc-benchmark-20260503-032852.md`

Result summary:

- Acceptance passed: `true`
- GPU: NVIDIA GeForce RTX 3060, 12GB VRAM, driver `591.86`, compute capability `8.6`
- OCR: PaddleOCR on `gpu:0`, status `ok`, latency about `4.99s` for the synthetic frame
- LLM: ONNX Phi reasoning provider, status `ok`, about `4.62` approximate output tokens/sec
- Offline mode: Hugging Face and Transformers offline flags active, local model files ready
- Privacy regression: passed
- Raw frame or OCR-cycle temp files remaining: `0`

The first PaddleOCR run can be much slower because it downloads and initializes OCR weights. Subsequent benchmark runs use the repo-local cache under `models/ocr/paddlex/`.
