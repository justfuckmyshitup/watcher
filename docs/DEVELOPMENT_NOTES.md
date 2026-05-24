# Development Notes

## Design Snapshot

The latest offscreen Electron render is stored at:

`docs/assets/watcher-dashboard-render.png`

It informed the implemented layout: left navigation, explicit capture status, session controls, live context preview, notes editor, and right-side runtime/privacy diagnostics.

## Implementation Notes

- Backend code is under `backend/app`.
- Desktop UI is under `apps/desktop`.
- The backend creates SQLite tables on startup.
- Tests use FastAPI `TestClient`.
- Raw screenshots are not persisted; tests assert `raw_artifact_persisted` is false.
- Windows launcher entry point is `start.ps1`, which delegates to `scripts/start-watcher.ps1`.
- Plain `start.ps1` now opens an interactive launcher menu. Use `-NoPrompt` for scripted live defaults.
- Launcher logs are written under `app-data/logs/launcher`.
- Launcher process state is written under `app-data/launcher` and is ignored by git.
- Sessions now persist capture interval, OCR provider/profile, model provider, privacy strictness, and session-specific exclusion patterns.
- Context events expose privacy action, redaction count, OCR confidence, and OCR timing for the live preview while keeping raw frames ephemeral.
- Phase 5 benchmark entry point is `scripts/benchmark-poc.ps1`; reports go to `app-data/benchmarks/`.
- Live GPU setup helper is `scripts/setup-live-poc.ps1`; it requires Python 3.12/3.13 and will not install system-level dependencies.
- The target Windows RTX 3060 live benchmark passed with PaddleOCR on GPU and ONNX Phi reasoning on CUDA; latest report is `app-data/benchmarks/poc-benchmark-20260503-032852.json`.
- ONNX Runtime GenAI CUDA uses repo-local CUDA DLL discovery from `.venv\Lib\site-packages\nvidia\*\bin` to avoid requiring a global CUDA Toolkit for the current POC profile.
- Real POC smoke entry point is `scripts/poc-live-smoke.ps1`; it verifies GPU OCR, inferred privacy, local ONNX Phi note generation, and temp cleanup without persisting raw frames.

## Known MVP Limits

- Live PaddleOCR and ONNX Phi CUDA work on the target machine after running `scripts/setup-live-poc.ps1 -ForceRecreateVenv -InstallRuntimePackages -DownloadModels`, but the setup is still developer-grade rather than packaged.
- The current note-quality benchmark is a synthetic smoke path; broader task/decision recall scoring is still needed before a polished demo.
- Active app/window metadata is currently the desktop capture source label plus placeholder app name.
- Mock AI is the default.
- API authentication is not implemented yet.

## Launcher Manual QA

1. Clone or copy the repo fresh.
2. Run `.\start.ps1`.
3. Confirm `.venv` is created.
4. Confirm backend dependencies install into `.venv`.
5. Confirm npm dependencies install.
6. Confirm backend starts on `127.0.0.1:8765`.
7. Confirm Vite starts on `127.0.0.1:5173`.
8. Confirm Electron launches.
9. Close Electron.
10. Confirm backend and Vite stop cleanly.
11. Run `.\start.ps1` again and confirm it reuses installed dependencies.
12. Run `.\scripts\stop-watcher.ps1` and confirm it does not affect unrelated processes.
13. Run `.\start.ps1 -VitePort 5174` and confirm port overrides work.
14. Run `.\start.ps1 -DockerBackend` with Docker Desktop running and confirm backend health succeeds.
15. Run `.\scripts\launcher-smoke.ps1` to verify dependency checks, backend startup, Vite startup, Electron command formation, and cleanup.
16. Run `.\scripts\benchmark-poc.ps1 -RequireGpu -AllowIncomplete` and confirm it writes JSON/Markdown reports.
17. After live runtime packages are installed, rerun the benchmark with `-OcrProvider paddle -ModelProvider onnx-phi -RequireGpu -Offline`.
18. Run `.\scripts\poc-live-smoke.ps1 -RequireGpu` and confirm it returns `"ok": true`.
