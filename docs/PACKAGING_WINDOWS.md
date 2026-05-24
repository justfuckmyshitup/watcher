# Windows Packaging Path

The current Windows experience is a one-command launcher:

```powershell
.\start.ps1
```

This is intentionally short of a full installer. It is easier to debug while the MVP backend, local runtime selection, OCR, and capture pipeline are still changing.

## Target Packaged Experience

Long term, Watcher should ship as either:

- A Windows installer.
- A portable app bundle / EXE-like directory.

The packaged app should:

- Bundle the Electron desktop shell.
- Start or check the backend automatically.
- Avoid requiring terminal commands for normal use.
- Keep backend services bound to localhost.
- Avoid telemetry and cloud AI calls.
- Avoid silently installing system-level dependencies.
- Support external local model providers such as Ollama and LM Studio.
- Avoid bundling huge model files by default.

## Candidate Tooling

Recommended Electron packaging options:

- `electron-builder`
- `electron-forge`

Either can produce a portable app directory and Windows installer formats. `electron-builder` is a common first path for NSIS installers and portable executables.

## Backend Packaging Options

Option A: Bundle Python backend as an executable.

- Use PyInstaller or Nuitka to package `backend.app.main`.
- Electron starts the backend executable on launch.
- The backend continues to bind to `127.0.0.1`.
- App data remains outside the install directory.

Option B: Manage a local backend service.

- Installer creates a local user-level service or scheduled app startup entry.
- Electron checks service health and offers repair/restart.
- More enterprise-friendly, but more moving parts.

Option C: Keep developer launcher.

- Good for MVP and internal testing.
- Lowest packaging complexity.
- Requires Python and Node.js installed.

## First-Run Checks

The packaged version should clearly report missing optional system tools:

- Docker Desktop
- Ollama
- LM Studio
- Tesseract/OCR engines
- NVIDIA drivers / CUDA
- WSL2

It should not silently install them. If `winget` commands are offered, they should be shown to the user and run only after explicit confirmation.

## Security Requirements

Packaging must preserve the MVP security design:

- No Docker desktop capture.
- No privileged containers.
- No Docker socket mount.
- No broad host mounts.
- No telemetry.
- No cloud AI calls.
- No hidden capture on startup.
- No raw screenshot persistence by default.
- No keylogging or clipboard capture.
- Backend remains localhost-only unless the user explicitly changes it.

## Suggested Next Step

Add `electron-builder` with a portable Windows target first. Keep backend startup via the existing launcher logic until the backend executable path is proven.

