# Local Scribe POC Action Plan

This plan turns the MVP shell into a working privacy-first proof of concept. It is intentionally phased so the next implementation step can begin when the user replies:

```text
Proceed
```

Default target machine: Windows with NVIDIA RTX 3060 12GB, local-only runtime, no cloud AI calls during normal operation.

## Implementation Status

- Phase 0: completed.
- Phase 1: completed.
- Phase 2: completed.
- Phase 3: completed.
- Phase 4: completed.
- Phase 5: completed.
- Phase 6: completed.

## Hardware-First Rule

The POC should prefer specialized hardware before doing useful work. If the NVIDIA GPU stack is expected but not available, the app should fail early with a clear setup message instead of silently falling back to slow CPU/system RAM execution.

Default runtime stance:

- `RequireGpu=true` for live OCR and local LLM POC profiles.
- CPU fallback is allowed only when explicitly requested with a future `-AllowCpuFallback` flag or a visible advanced setting.
- Model loading must prove the selected provider is running on GPU before capture/OCR/LLM processing begins.
- Runtime must record GPU proof metadata for each model run:
  - provider name
  - selected device
  - CUDA/DirectML/CPU execution provider
  - NVIDIA driver version
  - CUDA runtime status
  - VRAM total/free before model load
  - estimated/model-reported VRAM after load
  - tokens/sec or OCR milliseconds/frame
- Avoid context/model settings that spill into system RAM by default. Large context windows are useful, but the POC should clamp context to a measured 3060-safe budget unless the user explicitly changes it.

## Guiding Principles

1. Privacy gates come before durable memory.
2. Raw screenshots remain ephemeral processing material.
3. OCR output is treated as sensitive until proven otherwise.
4. Redaction happens before storage and before LLM ingestion.
5. High-sensitivity windows or frames should be skipped or metadata-only by default.
6. Local models are downloaded once from Hugging Face into a local model cache.
7. Runtime startup must not pull models from the internet.
8. The default LLM should be from an American organization.
9. GPU acceleration is a launch requirement for live POC profiles unless explicitly overridden.
10. No telemetry, no cloud AI, no hidden capture, no keylogging, no clipboard capture.

## Recommended POC Model Choices

### OCR

Primary POC OCR engine:

- PaddleOCR PP-OCRv5, benchmarked locally in two profiles:
  - `screen-fast`: PP-OCRv5 mobile, max side 960 or 640.
  - `screen-accurate`: PP-OCRv5 server, max side 960.

Why:

- It includes text detection plus recognition, which is better for desktop screenshots than line-only OCR.
- Published PP-OCRv5 GPU reference numbers fit comfortably in 3060-class VRAM for several configurations.
- The plan will run our own 3060 benchmark before making it the default.
- The POC should use the PaddlePaddle GPU package first and verify GPU execution before processing frames.

American-vendor OCR note:

- If we later decide the OCR model also must be American-vendor, evaluate Microsoft TrOCR as a secondary recognizer for cropped text lines. It is not a full screen OCR pipeline by itself, so it is not the first POC default.

### Local LLM

Primary American reasoning LLM for POC:

- `microsoft/Phi-4-mini-reasoning-onnx`
- MIT license.
- ONNX Runtime optimized INT4 GPU package.
- 128K context support in the model family, but the POC should use a measured 3060-safe context budget by default.
- Best fit for the user's requirement that the model reason well enough to summarize, infer tasks, produce proper notes, and avoid treating OCR as mere character extraction.

Preferred runtime path for POC:

- Download from Hugging Face once into `models/llm/microsoft--Phi-4-mini-reasoning-onnx`.
- Include only the GPU ONNX files for the first hardware-first profile.
- Run with ONNX Runtime GenAI CUDA first.
- Use DirectML only as an explicit Windows fallback profile if CUDA is unavailable or unreliable.
- Refuse CPU execution in the default live POC profile.

Secondary fast American LLM:

- `microsoft/Phi-4-mini-instruct`
- MIT license.
- About 7.69 GB on Hugging Face in safetensors form.
- Good fallback if the reasoning model is too verbose or slower than needed for routine note cleanup.
- Prefer `microsoft/Phi-4-mini-instruct-onnx` when using ONNX Runtime GenAI.

Stronger American reasoning candidate:

- `microsoft/Phi-4-reasoning`
- MIT license.
- 14B parameters, strong reasoning benchmarks, and supported by common local runtimes.
- Not the first POC default because the 3060 must prove it can run a quantized build entirely in VRAM at an acceptable context size.

Secondary stronger American general LLM:

- `ibm-granite/granite-3.3-8b-instruct`
- Apache 2.0 license.
- 8B parameters, 128K context.
- Full BF16 repo is about 16.3 GB, so it likely needs quantization or a smaller runtime profile for comfortable 3060 usage.

Optional gated American model:

- `meta-llama/Meta-Llama-3.1-8B-Instruct`
- Strong 8B option, but gated/custom-license handling makes it a secondary path for this project.

Optional Google American model:

- `google/gemma-3-12b-it`
- Strong reasoning, summarization, and long-context candidate.
- Gated license acceptance and 12B size make it a later evaluation path, not the default POC.

### LLM Note Quality Requirements

The LLM must be evaluated as a note-taking and reasoning system, not merely as a text generator.

POC quality checks:

- Extract tasks, decisions, open questions, and timeline from redacted context events.
- Produce Markdown notes that are grounded in event IDs or timestamps.
- Preserve redaction tokens exactly and never infer hidden values behind `[REDACTED_*]`.
- Avoid storing or displaying chain-of-thought or scratch reasoning.
- Use concise final notes, not verbose reasoning transcripts.
- Handle noisy OCR text without inventing facts.
- Identify uncertainty when context is incomplete.
- Support note modes:
  - activity log
  - meeting/task summary
  - SOP/runbook draft
  - ticket update
  - decision record

Privacy rule for reasoning models:

- The app may allow a reasoning-capable model to reason over redacted structured events, but durable storage should keep only the final note, model metadata, and safety findings. Do not persist model scratch text, hidden reasoning traces, or prompt intermediates by default.

## Local Model Download Policy

Add a model manager that downloads models only when explicitly requested:

```powershell
.\scripts\download-models.ps1 -Profile poc
```

The model manager should:

- Use the Hugging Face `hf` CLI when available.
- Fall back to `huggingface_hub.snapshot_download` inside `.venv` if `hf` is missing.
- Store model files under `models/`.
- Write `models/manifest.json` with repo id, revision, license, download time, selected files, and local path.
- Prefer targeted includes for the POC profile, such as the Phi ONNX GPU directory, instead of downloading every variant.
- Support `-Offline` checks that validate local files without network access.
- Never download during normal app startup unless the user explicitly runs the download command or passes a future explicit install flag.

Runtime should set or respect:

```powershell
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

after models are installed and the user chooses offline mode.

## Inferred Privacy Design

The POC needs a privacy decision engine before writing `ContextEvent`.

### Default Actions

Each frame gets one of these actions:

- `store_redacted`: safe enough to store redacted text snippets and metadata.
- `metadata_only`: store app/window/hash/timing/topic hints but no OCR text.
- `drop_event`: store no event; optionally log user action summary only.
- `needs_user_review`: hold only ephemeral preview until the user confirms.

### Signals

Use layered signals:

- App/window title rules:
  - Password managers
  - Banking/financial portals
  - HR/payroll systems
  - Medical/patient portals
  - MFA/authenticator windows
  - User-defined exclusions

- OCR text rules:
  - Password labels and password assignments
  - Masked password fields near labels
  - API keys, bearer tokens, private keys, OAuth tokens, JWTs
  - MFA/OTP codes
  - SSNs
  - Credit cards with Luhn validation
  - Bank routing/account-like numbers
  - IBANs
  - Account numbers near labels such as `account`, `acct`, `member id`, `policy number`
  - Secrets in `.env`, config, cloud console, CI/CD, password reset screens

- Visual/UI heuristics:
  - Input boxes adjacent to sensitive labels
  - Bullet or dot masks such as `••••••`, `******`, or black circles
  - Browser password reveal icons near fields
  - Credential form layouts
  - High-density number strings in finance-like windows

### Default Retention

High-risk default:

- Do not persist raw screenshot.
- Do not persist unredacted OCR.
- Do not send unredacted OCR to LLM.
- If sensitivity is high, store metadata only or drop the event.

Future explicit override:

- A user-visible evidence mode may allow screenshot retention, but that is out of scope for this POC unless separately approved.

## Phase 0: GPU Runtime Gate

Goal: prove the app can use the RTX 3060-class GPU before OCR or LLM work depends on it.

Implementation tasks:

- Add `scripts/check-gpu.ps1`.
- Add backend GPU diagnostics module, such as `backend/app/runtime/gpu.py`.
- Detect:
  - `nvidia-smi`
  - NVIDIA driver version
  - GPU name
  - compute capability if available
  - total/free VRAM
  - CUDA runtime availability
  - ONNX Runtime GenAI CUDA package availability
  - ONNX Runtime CUDA execution provider availability
  - PaddlePaddle GPU availability
- Add a tiny GPU probe:
  - ONNX Runtime CUDA provider import/load check.
  - Paddle GPU import and device check.
  - optional one-token Phi ONNX smoke test after the model is downloaded.
  - optional tiny OCR inference after OCR models are installed.
- Add launcher integration:
  - `.\start.ps1` warns or fails clearly when GPU is required but unavailable.
  - `.\scripts\start-localscribe.ps1 -AllowCpuFallback` may be added later for explicit CPU fallback.
- Add UI/backend diagnostics:
  - `gpu_ready`
  - `gpu_required`
  - `gpu_provider`
  - `gpu_name`
  - `driver_version`
  - `vram_total_mb`
  - `vram_free_mb`
  - `cuda_provider_available`
  - `paddle_gpu_available`
- Add failure guidance:
  - install/update NVIDIA driver
  - install CUDA Toolkit only if the selected runtime requires it
  - install compatible cuDNN only if required
  - use DirectML fallback only by explicit profile

Acceptance criteria:

- `.\scripts\check-gpu.ps1` reports RTX 3060-class GPU details when available.
- The backend exposes GPU diagnostics without starting screen capture.
- Default live POC mode refuses CPU-only OCR/LLM execution.
- Failure output explains exactly what is missing and what to install manually.
- No system-level GPU dependencies are silently installed.

After this phase, reply `Proceed` to start Phase 1.

## Phase 1: Privacy Engine Foundation

Goal: make the backend privacy decision explicit, testable, and conservative before integrating real OCR.

Implementation tasks:

- Add `privacy/decision_engine.py`.
- Add `PrivacyDecision` object with action, sensitivity score, reasons, redaction findings, and retention policy.
- Expand redaction patterns:
  - Luhn-checked cards
  - SSN
  - routing/account numbers
  - IBAN
  - JWT
  - bearer/API tokens
  - private keys
  - MFA/OTP
  - password fields and masked values
  - user-defined terms and regexes
- Add metadata-only/drop-event path to event ingestion.
- Persist privacy decision metadata without storing sensitive text.
- Add fixtures for sensitive screenshots using synthetic text only.
- Add tests confirming sensitive samples are redacted, metadata-only, or dropped.
- Add UI status labels for `stored`, `metadata-only`, `dropped`, and `redacted`.

Acceptance criteria:

- Synthetic password/API key/account number samples are not stored in clear text.
- High-sensitivity windows can produce `metadata_only` or `drop_event`.
- Existing session/note flows still work with safe synthetic text.
- Tests prove no raw screenshot artifacts are created.

After this phase, reply `Proceed` to start Phase 2.

## Phase 2: Local OCR POC

Goal: convert live in-memory frames into redacted text snippets locally.

Implementation tasks:

- Add OCR provider abstraction:
  - `MockOcrProvider`
  - `PaddleOcrProvider`
  - future `WindowsOcrProvider`
  - future `TrOcrLineProvider`
- Add OCR diagnostics:
  - available provider
  - GPU/CPU mode with CPU marked as explicit fallback only
  - CUDA/Paddle device proof
  - average frame OCR time
  - VRAM before/after OCR model load
  - last OCR error
- Add image preprocessing:
  - downsample profiles
  - grayscale/contrast option
  - crop region support for future active-window ROI
  - duplicate-frame skip before OCR
- Keep frame bytes in memory.
- Do not write temp frame files unless an OCR library forces it.
- If temp files are forced, write under `app-data/tmp/ocr-cycle-*` and delete after each cycle.
- Benchmark `screen-fast` and `screen-accurate` on 3060.
- Fail live OCR startup if PaddleOCR cannot use GPU and `RequireGpu=true`.
- Add throttling:
  - OCR every N frames
  - OCR only after frame hash changes
  - pause OCR under high sensitivity or excluded window

Acceptance criteria:

- A screen frame can produce OCR text locally.
- OCR text passes through Phase 1 privacy engine before persistence.
- OCR temp directory is empty after each processing cycle.
- UI shows OCR provider, GPU state, and explicit fallback state.
- Default OCR profile does not run on CPU silently.
- Tests cover temp cleanup and redaction-before-storage.

After this phase, reply `Proceed` to start Phase 3.

## Phase 3: Hugging Face Local LLM Download And Provider

Goal: download an American LLM once from Hugging Face and use it offline for note generation.

Implementation tasks:

- Add `scripts/download-models.ps1`.
- Add `scripts/check-models.ps1`.
- Add `models/manifest.json` generation.
- Add local model directory structure:

```text
models/
  llm/
    microsoft--Phi-4-mini-reasoning-onnx/
    microsoft--Phi-4-mini-instruct-onnx/
    microsoft--Phi-4-reasoning/
    ibm--granite-3.3-8b-instruct/
  ocr/
  manifest.json
```

- Implement an `OnnxPhiReasoningProvider`.
- Prefer `microsoft/Phi-4-mini-reasoning-onnx` as the default American reasoning LLM.
- Add optional `OnnxPhiInstructProvider` for faster summary cleanup.
- Add a future llama.cpp CUDA provider only if ONNX Runtime GenAI is not reliable enough on the target Windows GPU stack.
- Add provider config to runtime settings.
- Add offline mode checks:
  - app starts without internet
  - provider refuses to download during normal startup
  - clear error if model is missing
- Add note-generation prompt that receives only redacted structured context.
- Add context budget controls:
  - default max input tokens chosen from 3060 benchmark
  - max output tokens by note mode
  - reject settings that would spill into system RAM unless explicitly overridden
- Add reasoning output handling:
  - strip or reject `<think>`/scratch sections before persistence
  - store final Markdown note only
  - store model/provider/run metadata separately
- Add note-quality eval fixtures with redacted synthetic sessions.

Acceptance criteria:

- `download-models.ps1 -Profile poc` downloads the selected reasoning LLM once.
- Runtime can generate a note from redacted events without contacting Hugging Face.
- Missing model produces a friendly setup message.
- Runtime proves ONNX Runtime GenAI CUDA execution before note generation in the default profile.
- UI clearly shows live local LLM vs mock mode, model id, provider, and GPU state.
- Generated notes preserve redaction placeholders and do not include hidden reasoning traces.

After this phase, reply `Proceed` to start Phase 4.

## Phase 4: End-To-End POC Workflow

Goal: make the user workflow actually useful.

Implementation tasks:

- Wire capture to OCR to privacy decision to context event.
- Add session-level settings:
  - capture interval
  - OCR profile
  - privacy strictness
  - app/window exclusions
  - local LLM provider
- Add live context preview showing:
  - redacted snippets only
  - privacy action
  - redaction count
  - OCR confidence if available
- Add note generation modes:
  - activity log
  - clean summary
  - SOP/runbook
  - ticket update
  - decision record
  - audit evidence narrative without screenshots
- Add export path and delete-session verification.

Acceptance criteria:

- Start session, switch windows, generate redacted context events, generate Markdown.
- Closing/deleting session leaves no raw frame files.
- Mock mode and live local LLM mode are visually distinct.
- High-sensitivity frames do not leak into notes.
- Notes are grounded in redacted events and flag uncertainty instead of inventing missing context.

After this phase, reply `Proceed` to start Phase 5.

## Phase 5: POC Hardening And 3060 Benchmark

Goal: prove the POC is safe enough to demo and honest about limitations.

Implementation tasks:

- Add benchmark command:

```powershell
.\scripts\benchmark-poc.ps1
```

- Measure:
  - OCR latency by profile
  - LLM tokens/sec
  - VRAM usage
  - GPU utilization during OCR
  - GPU utilization during LLM generation
  - memory usage
  - whether any workload spills to CPU/system RAM
  - duplicate-frame skip rate
  - redaction latency
- Add note-quality benchmark:
  - task extraction accuracy on synthetic sessions
  - decision/action item recall
  - redaction placeholder preservation
  - hallucination checks against source event IDs
- Add privacy regression corpus.
- Add offline runtime test.
- Add launcher integration:
  - detect missing OCR model
  - detect missing LLM model
  - offer download command but do not run silently
- Update docs with exact hardware findings.

Acceptance criteria:

- POC benchmark report exists. Latest live report: `app-data/benchmarks/poc-benchmark-20260503-032852.json`.
- A fresh run can be performed offline after model download.
- Privacy regression tests pass.
- GPU proof is included in the benchmark report.
- Notes meet the POC note-quality checklist on synthetic sessions.
- Demo checklist is documented.

Phase 5 live result on the target Windows machine:

- GPU: NVIDIA GeForce RTX 3060, 12GB VRAM, driver `591.86`, compute capability `8.6`.
- OCR: PaddleOCR `screen-fast` on `gpu:0`, status `ok`, synthetic frame latency about `4.99s` after model cache warm-up.
- LLM: `microsoft/Phi-4-mini-reasoning-onnx` through ONNX Runtime GenAI CUDA, status `ok`, about `4.62` approximate output tokens/sec for the synthetic note prompt.
- Offline mode: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, local model files ready.
- Privacy regression: passed.
- Raw frame/temp artifacts remaining: `0`.
- Note quality: the synthetic redacted note prompt executes on the live local LLM; broader task/decision recall scoring remains a pre-demo hardening item.

Implementation note: ONNX Runtime GenAI CUDA on Windows needs the repo-local NVIDIA DLL paths from `.venv\Lib\site-packages\nvidia\*\bin` exposed before provider load. The backend now prepares those DLL paths and preloads the GenAI CUDA bridge so the POC does not require a global CUDA Toolkit install when the Python GPU wheels provide the needed runtime DLLs.

## Phase 6: Real POC Demo Loop

Goal: turn the proven OCR/LLM pieces into a repeatable demo workflow.

Implemented:

- Desktop defaults now adopt backend live runtime settings, so launching with `-OcrProvider paddle -ModelProvider onnx-phi -RequireGpu` no longer leaves the dashboard on mock defaults.
- Plain `.\start.ps1` now presents an interactive menu for environment, hardware policy, local model provider, and OCR profile.
- `.\start.ps1 -NoPrompt` uses the live POC defaults without prompting for scripted checks.
- Runtime diagnostics preserve proven CUDA status instead of incorrectly marking live local providers as CPU fallback.
- Added `scripts/poc-live-smoke.ps1` and `scripts/poc_live_smoke.py`.
- Added `docs/REAL_POC_RUNBOOK.md`.

Acceptance result:

- `.\scripts\poc-live-smoke.ps1 -RequireGpu` passed.
- GPU provider gate passed.
- PaddleOCR reported ready on `gpu:0`.
- Local Phi model files were present.
- Synthetic in-memory OCR event stored redacted context.
- Synthetic API key event became `metadata_only` and did not leak the secret.
- ONNX Phi generated a note with model run status `ok`.
- Raw frame/OCR temp files after smoke: `[]`.

Next phase candidates:

- Improve active app/window metadata beyond the Electron capture source label.
- Add a note-quality eval corpus for action items, decisions, and hallucination checks.
- Add a visible “Run POC readiness check” action in the UI.
- Package the Windows app path.

## Explicit Non-Goals For POC

- No cloud inference.
- No automatic system dependency installation.
- No screenshot evidence archive.
- No hidden capture.
- No keylogging.
- No clipboard capture.
- No backend binding to `0.0.0.0`.
- No Docker desktop-capture access.
- No employee surveillance positioning.
- No silent CPU fallback for live OCR or LLM POC profiles.
- No durable storage of model scratch reasoning or prompt intermediates.

## Sources Checked

- Microsoft Phi-4-mini-reasoning ONNX repository with CUDA/DirectML/CPU ONNX Runtime GenAI examples and MIT license: https://huggingface.co/microsoft/Phi-4-mini-reasoning-onnx
- Microsoft Phi-4-reasoning Hugging Face model card, MIT license, 14B reasoning model details, and benchmark summary: https://huggingface.co/microsoft/Phi-4-reasoning
- Microsoft Phi-4-mini-instruct Hugging Face model files and MIT license: https://huggingface.co/microsoft/Phi-4-mini-instruct
- Microsoft Phi-4-mini-instruct ONNX repository: https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx
- IBM Granite 3.3 8B Instruct Hugging Face model card: https://huggingface.co/ibm-granite/granite-3.3-8b-instruct
- Meta Llama 3.1 8B Instruct Hugging Face model card: https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct
- Google Gemma 3 12B IT Hugging Face model card: https://huggingface.co/google/gemma-3-12b-it
- ONNX Runtime GenAI install docs for CUDA/DirectML package choices: https://onnxruntime.ai/docs/genai/howto/install.html
- ONNX Runtime CUDA Execution Provider docs for CUDA/cuDNN compatibility and CUDA provider checks: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
- Ollama hardware support docs confirming RTX 3060 compute capability support if used as a future fallback runtime: https://docs.ollama.com/gpu
- PaddleOCR PaddlePaddle GPU installation docs for CUDA package and driver requirements: https://www.paddleocr.ai/latest/en/version3.x/paddlepaddle_installation.html
- PaddleOCR PP-OCRv5 documentation and GPU performance reference: https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- PaddleOCR release notes mentioning PP-OCRv5 English recognition and CUDA 12 support: https://github.com/PaddlePaddle/PaddleOCR/releases
- Hugging Face Transformers TrOCR documentation: https://huggingface.co/docs/transformers/model_doc/trocr
