# Real POC Runbook

This runbook is the fastest path from a configured checkout to a real Local Scribe POC on the Windows RTX 3060 target machine.

## One-Time Setup

Install repo-local runtime packages and download local model files:

```powershell
.\scripts\setup-live-poc.ps1 -ForceRecreateVenv -InstallRuntimePackages -DownloadModels
```

This does not silently install system-level dependencies. Python, Node.js, NVIDIA drivers, Docker Desktop, CUDA Toolkit, Ollama, LM Studio, and other system tools remain manual installs.

## Prove The Stack

Run the live POC smoke:

```powershell
.\scripts\poc-live-smoke.ps1 -RequireGpu
```

The smoke command verifies:

- NVIDIA GPU provider readiness.
- Isolated smoke storage under `app-data/poc-smoke`, so a test run does not modify normal app sessions.
- PaddleOCR readiness on `gpu:0`.
- Local Hugging Face model files for `microsoft/Phi-4-mini-reasoning-onnx`.
- Live OCR from an in-memory synthetic screen.
- Pause/resume/stop lifecycle behavior, including skipped ingest while paused/stopped.
- Strict inferred privacy for a synthetic API key.
- Local ONNX Phi note generation.
- No hidden reasoning or synthetic secret leakage in the generated note.
- No raw frame or OCR temp files remaining after cleanup.

Latest target-machine result:

- Status: `ok`
- Model run provider: `onnx-phi-reasoning`
- Model run status: `ok`
- Session cleanup: deleted after smoke
- Temp frame artifacts after smoke: `[]`

## Start The App For A Real Demo

```powershell
.\start.ps1 -OcrProvider paddle -OcrProfile screen-fast -ModelProvider onnx-phi -RequireGpu
```

Or use the guided launcher:

```powershell
.\start.ps1
```

Recommended menu selections:

- Environment: `1` Native Windows runtime
- Hardware policy: `1` Require NVIDIA GPU acceleration
- Local model provider: `1` Microsoft Phi-4 mini reasoning ONNX
- OCR provider: `1` PaddleOCR screen-fast

For scripted startup without the menu:

```powershell
.\start.ps1 -NoPrompt
```

In the desktop app:

1. Confirm the Runtime panel shows live local AI and GPU readiness.
2. Confirm the dashboard OCR setting is `PaddleOCR`.
3. Confirm the dashboard LLM setting is `ONNX Phi`.
4. Keep privacy strictness on `Strict` for the POC.
5. Enter a plain-language session goal, for example: `I'm working on marketing material and school work. Track how I split my time and what I do for each task.`
6. Start a session and approve the Electron screen picker.
7. Let unchanged-frame skips accumulate when the screen is static; changed frames should be OCR'd and stored as redacted events.
8. Click Pause during capture and confirm status changes immediately, even if OCR is processing.
9. Click Resume and confirm event capture continues.
10. Generate an activity log or clean summary.
11. Export Markdown if needed.
12. Stop the session and confirm capture is idle.

## Fast Capture Defaults

The app is tuned for a fast local loop by default:

- The session interval defaults to `0.5s`.
- The renderer performs in-memory visual change detection before encoding a frame.
- Significant text-scale changes are processed immediately; tiny repeated changes are probed instead of being discarded as duplicates.
- Truly idle screens are still probed periodically, and the backend exact hash check skips exact duplicates before OCR.
- The backend performs an exact screenshot hash duplicate check before OCR as a second guard.
- Frame ingestion uses OCR, redaction, hashes, cleaned compact summaries, and a lightweight local topic/task labeler.
- ONNX Phi is reserved for stop/manual note generation.

## Privacy Expectations

The real POC should retain only compact, redacted local memory:

- Session metadata
- Context event hashes
- Redacted snippets
- Privacy decisions
- Redaction finding hashes
- OCR provider metadata
- Model run metadata
- Generated Markdown notes
- User action logs

It should not retain:

- Raw screenshots
- Full unredacted OCR dumps
- Temporary frame files
- Model scratch reasoning
- Evidence screenshots

Evidence screenshot retention remains out of scope unless a future explicit evidence mode is added with clear consent.

## Known Rough Edges

- Paddle may print cuDNN compatibility warnings on the current target machine even when the smoke passes.
- Active app/window metadata is still mostly the Electron capture source label.
- The real POC smoke is synthetic; it proves the backend loop, while a human desktop demo still needs the Electron screen picker.
- The live labeler is currently an inline local classifier. A benchmarked 1B-3B Hugging Face model queue is the next step before loading additional GPU model instances by default.
