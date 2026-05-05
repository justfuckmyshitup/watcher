# Contributing

Thanks for helping make Local Scribe more useful, safer, and easier to run.

## Project Direction

Local Scribe is a local-first, privacy-first desktop documentation assistant. Good contributions usually improve one of these areas:

- Launcher reliability on Windows first, with practical Linux/macOS support where possible
- OCR/runtime setup clarity
- BYO-model provider adapters
- Privacy, redaction, and ephemeral processing guarantees
- UI feedback and session control stability
- Tests, smoke checks, and documentation
- Better generated notes from already-redacted structured context

Please avoid changes that add telemetry, cloud AI calls by default, hidden capture, keylogging, clipboard capture, broad Docker host access, or durable screenshot archives.

## Local Setup

```powershell
.\start.ps1
```

For deterministic development without live OCR/model requirements:

```powershell
.\start.ps1 -Mock
python -m pytest backend\tests
npm run build
```

## Before Opening A Pull Request

Run the lightweight checks:

```powershell
python -m pytest backend\tests
npm run build
```

If your change touches launcher behavior, also run:

```powershell
.\scripts\launcher-smoke.ps1
```

If your change touches GPU/OCR/model setup, document the exact hardware/runtime assumptions and keep mock-mode tests passing.

## Privacy Review Checklist

Before proposing capture, OCR, redaction, storage, export, or logging changes, confirm:

- Raw screenshots are not persisted by default.
- Full unredacted OCR dumps are not persisted by default.
- Temporary files are cleaned after each processing cycle/session.
- Durable memory remains compact, structured, redacted, and exportable.
- Any new sensitive artifact has a clear retention rule.
- Any future evidence mode is explicit opt-in and visibly user-controlled.

## Issues

Useful bug reports include:

- OS and version
- GPU model, driver version, and whether CPU fallback was enabled
- Launcher command used
- OCR/model provider selected
- Relevant log excerpt with secrets removed
- Whether the issue reproduces in mock mode

Do not include screenshots or OCR text that contains private data.
