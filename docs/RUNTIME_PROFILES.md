# Runtime Profiles

## Fast Local POC

Default live POC behavior is optimized for frequent capture on the RTX 3060-class target:

- Capture interval defaults to `0.5s`.
- The renderer samples the frame in memory and only skips truly idle screens. Small pixel changes are treated as likely text edits: significant changes are processed immediately, tiny repeated changes are probed, and a true-idle probe runs about every 10 seconds.
- The backend performs an exact screenshot hash check before OCR as a second guard.
- PaddleOCR `screen-fast` runs only for changed frames.
- A lightweight local live labeler assigns topic/task labels inline without loading another GPU model instance.
- The ONNX Phi reasoning model is used for stop/manual note generation, not every frame.
- A future small live model slot should be `1B-3B` and queue-based; do not run multiple GPU model instances by default until benchmarks show a gain.

Recommended launcher:

```powershell
.\start.ps1
```

Recommended menu choices: native Windows runtime, NVIDIA GPU required, ONNX Phi reasoning model, PaddleOCR `screen-fast`.

## Mock

Default profile. It is safe for development and tests. The UI clearly shows `Mock AI mode active. No real local model analysis has occurred.`

Launcher:

```powershell
.\start.ps1 -Mock
```

## Host Ollama

Recommended first live path on Windows, macOS, and Linux because GPU acceleration is handled by the host runtime.

Launcher:

```powershell
.\start.ps1 -ModelProvider ollama
```

## Host LM Studio

Good for local OpenAI-compatible chat endpoints. The backend talks only to the configured local URL.

Launcher:

```powershell
.\start.ps1 -ModelProvider lmstudio
```

## Docker Backend Plus Host Model

The backend can run in Docker while model inference runs on the host. On Docker Desktop, host services may be reached with `host.docker.internal`.

Launcher:

```powershell
.\start.ps1 -DockerBackend
```

## Future Profiles

- llama.cpp CUDA or Metal
- MLX on Apple Silicon
- Local embeddings with LanceDB, Qdrant, Chroma, or SQLite-adjacent storage

GPU status is shown as available/unverified unless the selected runtime exposes proof that inference is actively using GPU.

## POC Benchmark

Run:

```powershell
.\scripts\benchmark-poc.ps1 -RequireGpu -AllowIncomplete
```

After live OCR/LLM packages and model files are installed:

```powershell
.\scripts\benchmark-poc.ps1 -OcrProvider paddle -ModelProvider onnx-phi -RequireGpu -Offline
```

The benchmark writes JSON and Markdown reports under `app-data/benchmarks/` and does not persist raw screenshot artifacts.

For the end-to-end real POC smoke:

```powershell
.\scripts\poc-live-smoke.ps1 -RequireGpu
```

This creates a temporary session, runs live OCR and local note generation, verifies strict privacy behavior, checks temp cleanup, then deletes the smoke session unless `-KeepSession` is passed.

## Hardware-First GPU Gate

Live OCR/LLM POC profiles should prove NVIDIA hardware is present before doing useful work.

Check the host:

```powershell
.\scripts\check-gpu.ps1
```

Require GPU at launch:

```powershell
.\start.ps1 -RequireGpu
```

Guided launcher:

```powershell
.\start.ps1
```

The recommended menu path selects native Windows runtime, NVIDIA GPU required, local ONNX Phi, and PaddleOCR `screen-fast`. Scripted runs can use `.\start.ps1 -NoPrompt` to skip the menu and use the same live POC defaults.

Allow CPU fallback only when intentionally testing degraded behavior:

```powershell
.\start.ps1 -AllowCpuFallback
```

After ONNX Runtime GenAI CUDA and PaddlePaddle GPU packages are installed, stricter checks can be used:

```powershell
.\scripts\check-gpu.ps1 -RequireGpu -RequireCudaProvider
.\scripts\check-gpu.ps1 -RequireGpu -RequirePaddleGpu
```

The backend exposes the same shape at:

```text
GET /api/diagnostics/gpu
```

## Local OCR Profiles

Default OCR provider is `mock`, which performs no image OCR. Live OCR is explicit:

```powershell
.\scripts\check-ocr.ps1 -Provider paddle -RequireGpu
.\start.ps1 -OcrProvider paddle -OcrProfile screen-fast -RequireGpu
```

Supported POC profiles:

- `screen-fast`: PP-OCRv5 mobile detection/recognition, intended for frequent desktop frames.
- `screen-accurate`: PP-OCRv5 server detection/recognition, intended for slower but stronger extraction.

The PaddleOCR provider requires in-memory image processing by default. Temporary frame files are disabled unless `LOCAL_SCRIBE_OCR_ALLOW_TEMP_FILES=true` is explicitly set; when enabled, files are written under `app-data/tmp/ocr-cycle-*` and deleted in the same processing cycle.

OCR diagnostics:

```text
GET /api/diagnostics/ocr
```

## Local ONNX Phi Reasoning

The POC local reasoning provider is explicit:

```powershell
.\scripts\download-models.ps1 -Profile poc
.\scripts\check-models.ps1 -Profile poc
.\start.ps1 -ModelProvider onnx-phi -RequireGpu
```

This provider uses `microsoft/Phi-4-mini-reasoning-onnx` from Hugging Face with the `gpu/*` files selected into `models/`. Runtime startup does not download from Hugging Face. Missing model files or missing ONNX Runtime GenAI CUDA packages are surfaced as diagnostics and actionable errors.

On Windows, the backend prepares repo-local CUDA DLL paths from `.venv\Lib\site-packages\nvidia\*\bin`, `.venv\Lib\site-packages\onnxruntime\capi`, and `.venv\Lib\site-packages\onnxruntime_genai` before loading the CUDA provider. This lets the current POC use CUDA DLLs supplied by installed Python GPU wheels instead of requiring a global CUDA Toolkit install.

Latest RTX 3060 target-machine benchmark:

- `microsoft/Phi-4-mini-reasoning-onnx` through ONNX Runtime GenAI CUDA
- GPU required: `true`
- Offline mode: `true`
- LLM status: `ok`
- Approximate output throughput: `4.62` tokens/sec on the synthetic note prompt

## Live Labeling Lane

The POC now separates fast live labeling from slower reasoning:

- Live frame ingest: hash/dedupe, OCR, strict redaction, compact summary, topic/task labeling.
- Live labeler: in-process `context_lattice` labeler that uses observed redacted text first and the session goal only as a fallback.
- Reasoning model: ONNX Phi is reserved for explicit note generation and stop-time summaries.

This avoids loading multiple concurrent GPU LLM instances on a 3060. The next model milestone is a benchmarked `1B-3B` Hugging Face model for the live labeler queue, selected only if it beats the inline labeler without starving PaddleOCR or the reasoning model.
