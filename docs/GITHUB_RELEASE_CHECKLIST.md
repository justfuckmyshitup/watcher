# GitHub Release Checklist

Use this before making the repository public.

## Repository Hygiene

- [ ] Confirm `.gitignore` excludes `.env`, `.venv`, `node_modules`, `app-data`, `models`, logs, exports, caches, and temp files.
- [ ] Confirm no screenshots, OCR dumps, SQLite databases, model weights, or local logs are staged.
- [ ] Confirm `models/` contains only `.gitkeep` in git.
- [ ] Confirm `app-data/` contains only intentional placeholders in git.
- [ ] Confirm `.env.example` has safe localhost/mock defaults.

## Privacy/Security

- [ ] Re-read `SECURITY.md`, `PRIVACY.md`, and `docs/ARCHITECTURE.md`.
- [ ] Confirm raw screenshots are still ephemeral by default.
- [ ] Confirm evidence mode is not enabled or implied.
- [ ] Confirm no telemetry or cloud AI defaults were added.
- [ ] Confirm Docker mode has no broad host mounts and no Docker socket mount.

## BYO Model

- [ ] README describes Watcher as bring-your-own-model.
- [ ] Reference model is documented, not bundled.
- [ ] Download commands are explicit.
- [ ] Startup does not silently download models.
- [ ] Mock mode works without GPU or model files.

## Verification

```powershell
python -m pytest backend\tests
npm run build
.\scripts\launcher-smoke.ps1
```

Optional live POC checks:

```powershell
.\scripts\check-gpu.ps1 -RequireGpu
.\scripts\check-ocr.ps1 -Provider paddle -RequireGpu
.\scripts\check-models.ps1 -Profile poc
.\scripts\poc-live-smoke.ps1 -RequireGpu
```

## Suggested GitHub Topics

- local-first
- privacy
- desktop
- ocr
- notes
- electron
- fastapi
- bring-your-own-model
- local-ai
