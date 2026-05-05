# Context Lattice Design

The MVP borrows the local-first context orchestration idea from ContextLattice without copying it directly.

## Durable Objects

- `Session`
- `ContextEvent`
- `Observation`
- `TopicRollup`
- `TaskRollup`
- `Entity`
- `Artifact`
- `RedactionFinding`
- `Note`
- `ExportRecord`
- `ModelRun`
- `RuntimeProfile`
- `AppExclusion`
- `UserActionLog`

## Event Shape

Context events include timestamp, session ID, app/window metadata, source, screenshot hash, perceptual hash, OCR hash, redacted snippet, event type, detected topic/task, sensitivity score, redaction findings, summary snippet, related prior event IDs, confidence score, and user-selected mode.

The event explicitly tracks that raw artifacts were not persisted.

## MVP Retrieval

Retrieval uses session/event queries and keyword-like classification. Future retrieval can add SQLite FTS5, local embeddings, and local vector stores. Cloud vector databases are out of scope.

## Rollups

Rollups group events by simple topic/task classification. They are intentionally compact so the local memory remains exportable and easy to inspect.

