# Architecture

Watcher uses a hybrid architecture:

```text
Electron desktop shell
  - user consent and capture controls
  - OS screen capture permission boundary
  - in-memory frame downsampling
  - visible capture indicator
        |
        | localhost-only API
        v
FastAPI backend
  - session orchestration
  - ephemeral frame processing
  - optional local OCR provider
  - SQLite structured memory
  - redaction and exclusion enforcement
  - context lattice rollups
  - Markdown generation
        |
        | local host endpoints only
        v
Local AI runtime
  - Mock provider
  - ONNX Runtime GenAI Phi provider
  - Ollama provider
  - LM Studio provider
```

## Ephemeral Raw Context Invariant

Raw screenshots, frame captures, OCR intermediates, and high-risk context artifacts are processing inputs, not records. The desktop shell captures a frame into a canvas, posts a compressed payload to localhost, and the backend computes hashes and redacted snippets in memory. The durable database stores `raw_artifact_persisted = false` on context events.

Durable memory contains:

- Session metadata
- Context event metadata
- Screenshot hashes and coarse perceptual hashes
- OCR text hashes
- Redacted OCR snippets
- App/window metadata
- Topic/task classifications
- Rollups and generated Markdown
- Redaction findings by hash and type
- Model run metadata
- User action logs

Durable memory does not contain raw screenshots, long-term frame files, full unredacted OCR dumps, clipboard contents, or keystrokes.

## Capture Flow

```text
User starts session
  -> session settings are stored (interval, OCR profile, model provider, privacy strictness, exclusions)
  -> desktop shell shows capture active state
  -> getDisplayMedia asks for OS/user permission
  -> video frame is drawn to an in-memory canvas
  -> frame is downsampled and sent to localhost
  -> backend checks exclusion rules
  -> optional OCR provider extracts text from in-memory frame bytes
  -> backend computes hash/perceptual hash
  -> backend redacts provided OCR/manual text
  -> backend applies session privacy strictness
  -> backend chooses store_redacted, metadata_only, or drop_event
  -> backend stores normalized ContextEvent only when policy allows
  -> raw bytes go out of scope
  -> stale temp cleanup runs on processing/session stop/delete
```

OCR is pluggable per session. The default provider is mock/no-op. The PaddleOCR provider uses PP-OCRv5 profiles and attempts in-memory image processing first. Temporary frame files are disabled by default; if explicitly enabled for a library compatibility issue, they are written to `app-data/tmp/ocr-cycle-*` and removed in the same processing cycle. OCR text always flows through redaction and the privacy decision engine before persistence.

Events expose compact processing metadata for the UI: privacy action, redaction count, OCR provider/profile, OCR elapsed time, and average OCR confidence. They do not expose or persist raw frames or full unredacted OCR dumps.

## Backend Modules

- `api`: FastAPI routes and schemas.
- `capture`: ephemeral frame processing and cleanup.
- `context_lattice`: simple classification, related events, and rollups.
- `ocr`: mock and PaddleOCR provider abstraction plus OCR diagnostics.
- `redaction`: secret/sensitivity detection.
- `privacy`: app/window exclusion rules and privacy decision engine.
- `runtime`: mock, ONNX Phi, Ollama, and LM Studio provider abstraction.
- `notes`: Markdown note generation.
- `storage`: SQLAlchemy models and SQLite initialization.

## Ports And Network

The backend listens on `127.0.0.1:8765` by default. Docker maps the container port to `127.0.0.1` on the host. Model providers target host-local endpoints such as `127.0.0.1:11434` for Ollama and `127.0.0.1:1234` for LM Studio.

No cloud AI, telemetry, analytics, or browser access is part of the core runtime.
