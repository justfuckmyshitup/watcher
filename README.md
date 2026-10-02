# Watcher

Privacy-first local desktop context-to-notes assistant.

Watcher is a local-first desktop documentation assistant. It starts an explicit user-controlled capture session, converts approved desktop context into compact structured memory, and generates editable Markdown notes such as summaries, SOPs, runbooks, ticket updates, and audit narratives.

The MVP is intentionally conservative: raw screenshots are ephemeral processing material. They are hashed and converted into redacted context events, then discarded. The durable store is SQLite metadata, hashes, redacted snippets, rollups, notes, model run metadata, redaction findings, and user action logs.

## Community Project Status

This repository is intended as a community helper project and show-and-tell POC for local-first AI-assisted documentation. It is useful for experimentation, demos, and practical local workflows, but it is not a production monitoring, compliance, surveillance, or incident-response product.

## Why This Exists

I am extremely forgetful and ADHD, and I wanted a local tool that could help me reconstruct what I worked on without turning my computer into a surveillance archive. Watcher is my attempt to improve my own note taking while exploring OCR, local AI runtimes, GPU acceleration, redaction, and privacy-preserving context memory.

The goal is not to record everything forever. The goal is to capture just enough context during a user-controlled session to produce useful notes, then throw away the raw screen material.

Design boundaries:

- User-controlled sessions only. No hidden capture.
- Localhost-only backend by default.
- No telemetry.
- No cloud AI calls by default.
- No bundled model weights.
- No durable raw screenshot archive.
- Bring your own local model provider, or use the documented reference profile.

## What Is Built

- Electron/React desktop shell with dashboard, current session, live context preview, notes, history, runtime, privacy, exports, and diagnostics views.
- FastAPI backend bound to localhost.
- SQLite persistence for structured context memory.
- Ephemeral frame processor with redaction, hashing, duplicate skipping, and cleanup.
- Session-scoped goal, fast capture interval, OCR profile, privacy strictness, local reasoning model provider, and exclusion settings.
- Fast capture path with small-change visual probes, backend exact-hash dedupe before OCR, and a lightweight local live labeler.
- Mock model provider, host-local Ollama and LM Studio adapters, and an explicit local ONNX Phi reasoning provider.
- Docker Compose backend profile with localhost port binding and restricted container settings.
- Smoke tests and docs for security, privacy, runtime profiles, and platform setup.

## Quick Start

Windows:

```powershell
.\start.ps1
```

The plain launcher opens a short interactive menu for environment, hardware policy, model provider, and OCR profile. The recommended local POC path is native Windows with NVIDIA GPU required, PaddleOCR `screen-fast`, and a local reasoning model provider. The documented reference profile uses `microsoft/Phi-4-mini-reasoning-onnx`, downloaded explicitly into `models/`; the repository does not include model weights. The app defaults to a fast `0.5s` capture interval, processes small text-scale changes, and skips exact/idle duplicates before OCR.

The launcher checks Python, Node.js/npm, creates or reuses `.venv`, installs repo-local Python/npm dependencies when needed, installs/downloads safe repo-local live POC runtime pieces when missing, starts the backend on `127.0.0.1:8765`, starts Vite on `127.0.0.1:5173` or the next safe alternate Vite port, launches Electron, writes logs under `app-data/logs/launcher`, and shuts down services it started when Electron exits.

Useful flags:

```powershell
.\start.ps1 -BackendPort 8765 -VitePort 5173
.\start.ps1 -NoPrompt
.\start.ps1 -NoInstall
.\start.ps1 -SkipPipInstall
.\start.ps1 -SkipNpmInstall
.\start.ps1 -Mock
.\start.ps1 -DockerBackend
.\start.ps1 -ForceStopStale
.\start.ps1 -NoLaunch
.\start.ps1 -RequireGpu
.\start.ps1 -AllowCpuFallback
.\start.ps1 -OcrProvider paddle -OcrProfile screen-fast -RequireGpu
.\start.ps1 -ModelProvider onnx-phi -RequireGpu
.\start.ps1 -Debug
```

Stop services started by the launcher:

```powershell
.\scripts\stop-watcher.ps1
```

Check dependencies without starting:

```powershell
.\scripts\check-deps.ps1
```

Check NVIDIA GPU readiness:

```powershell
.\scripts\check-gpu.ps1
.\scripts\check-gpu.ps1 -RequireGpu
```

Check OCR readiness:

```powershell
.\scripts\check-ocr.ps1 -Provider paddle -RequireGpu
```

Download/check the local POC LLM explicitly:

```powershell
.\scripts\download-models.ps1 -Profile poc
.\scripts\check-models.ps1 -Profile poc
.\start.ps1 -ModelProvider onnx-phi -RequireGpu
```

## Bring Your Own Model

Watcher is a BYO-model project. The code supports provider slots rather than assuming one hosted model:

- `onnx-phi`: local ONNX Runtime GenAI provider. The reference/tested POC profile is `microsoft/Phi-4-mini-reasoning-onnx`, downloaded only when explicitly requested.
- `ollama`: host-local Ollama endpoint.
- `lmstudio`: host-local LM Studio OpenAI-compatible endpoint.
- `mock`: deterministic test mode for CI, demos without AI, and development.

Model files live under `models/` and are ignored by git. Do not commit model weights, private prompts, app data, captures, logs, exports, or SQLite databases.

For GitHub/community use, prefer documenting your model profile instead of shipping it. See `docs/LOCAL_MODEL_SETUP.md` and `docs/BYOM_MODEL_GUIDE.md`.

Set up the live RTX 3060-class POC environment without installing system dependencies:

```powershell
.\scripts\setup-live-poc.ps1 -ForceRecreateVenv -InstallRuntimePackages -DownloadModels
.\scripts\poc-live-smoke.ps1 -RequireGpu
.\scripts\benchmark-poc.ps1 -OcrProvider paddle -OcrProfile screen-fast -ModelProvider onnx-phi -RequireGpu -Offline
```

macOS/Linux practical launcher:

```sh
./scripts/start-watcher.sh
```

## Manual Dev Start

Use this fallback if you need to run each service separately:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
npm install
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765
npm --workspace @watcher/desktop run dev -- --host 127.0.0.1 --port 5173
$env:VITE_DEV_SERVER_URL="http://127.0.0.1:5173"
$env:WATCHER_API_BASE="http://127.0.0.1:8765/api"
npm --workspace @watcher/desktop run electron:dev
```

## Docker Backend

```powershell
.\start.ps1 -DockerBackend
```

The container maps `127.0.0.1:8765:8765`, uses a named app-data volume, drops Linux capabilities, avoids privileged mode, avoids the Docker socket, and does not receive desktop capture access.


## Local capture and privacy flow

The local API processes captures in memory, then applies a privacy
decision before storing an event. Raw screenshots and unredacted OCR
text are not durable artifacts.

```text
User-controlled desktop session
              |
              v
Capture frame + OCR
              |
              v
Local FastAPI processor
  hash + redact |
              v
Privacy decision
  +--> redacted or metadata-only event --> SQLite
  `--> drop event
```


## Core Privacy Rule

Raw context is not a durable record:

- No raw screenshot archive is created.
- Screenshots are processed in memory by default.
- Temporary frame files are avoided.
- Abandoned temp files are cleaned by `/api/cleanup` and session stop/delete flows.
- Full unredacted OCR text is not persisted by default.
- Evidence screenshots are not implemented in the MVP.

## Verify

```powershell
.\scripts\check-deps.ps1 -NoPortCheck
.\scripts\launcher-smoke.ps1
.\scripts\benchmark-poc.ps1 -RequireGpu -AllowIncomplete
python -m pytest backend\tests
python scripts\smoke_test.py
npm --workspace @watcher/desktop run build
```

The live POC smoke uses isolated storage under `app-data/poc-smoke` and also exercises the backend session control lifecycle: pause, resume, idempotent stop, and skipped ingest after a session is paused or stopped.

## Contributing

Small, privacy-preserving improvements are welcome: launcher reliability, platform setup docs, OCR/runtime adapters, UI clarity, test coverage, and note quality. Please read `CONTRIBUTING.md`, `SECURITY.md`, `PRIVACY.md`, and `docs/ARCHITECTURE.md` before opening issues or pull requests.

## Documentation

See `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/PRIVACY.md`, `docs/REAL_POC_RUNBOOK.md`, `docs/POC_BENCHMARKING.md`, `docs/BYOM_MODEL_GUIDE.md`, and the platform setup guides for GPU/local runtime details.
