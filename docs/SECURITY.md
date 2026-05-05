# Security

## Threat Model

Local Scribe processes sensitive desktop context. The primary risks are accidental capture of secrets, durable storage of screenshots, over-broad container access, unintended network calls, and ambiguous user consent.

The MVP mitigates these by keeping capture explicit, storing compact redacted context instead of raw images, binding services to localhost, and avoiding privileged Docker patterns.

## What Data Is Captured

Only after the user starts a session:

- Desktop frame payloads for immediate processing
- Capture source/window metadata where available
- Optional OCR/manual observation text
- Hashes, redacted snippets, classifications, rollups, and notes

## What Data Is Not Captured

- Keystrokes
- Clipboard contents by default
- Password manager contents by design when exclusions/redaction match
- Raw screenshot archives
- Full unredacted OCR dumps
- Browser history
- Cloud telemetry

## Raw Screenshot Policy

Raw screenshots are ephemeral processing material. They are decoded in memory, hashed, optionally used for deduplication, and then discarded. Temporary frame files are avoided. If a future OCR or vision component needs temp files, it must use the short-lived app temp directory and delete files after each processing cycle.

Evidence screenshots are not retained in the MVP. A future evidence mode must require explicit user consent, a visible state, and separate retention/deletion controls.

## OCR Runtime Policy

OCR is disabled by default via the mock provider. The live PaddleOCR provider is explicit and should be run with GPU required for POC profiles. OCR input frames are processed in memory by default. Temporary OCR frame files require `LOCAL_SCRIBE_OCR_ALLOW_TEMP_FILES=true`, are scoped to `app-data/tmp/ocr-cycle-*`, and are deleted in the same processing cycle.

## Redaction

The redaction layer masks private keys, bearer tokens, API keys, password assignments, SSNs, credit-card-like numbers, MFA codes, sensitive window terms, custom terms, and user-defined exclusions. Redaction findings store the finding type and a stable hash, not the secret value.

## Privacy Decisions

Redaction is not the only gate. The backend now makes an explicit privacy decision before writing context events:

- `store_redacted` for ordinary redacted context.
- `metadata_only` for account, banking, payroll, medical, SSN/card/routing/IBAN, and similar high-risk context.
- `drop_event` for password manager, authenticator/MFA, private key, masked password, and OTP-style context.

Metadata-only rows contain no OCR text snippet. Dropped events create no `ContextEvent`; the durable record is limited to a user action log that the capture was dropped by policy.

The decision engine also supports session strictness. `strict` turns any redaction finding into metadata-only storage. `maximum` drops high-risk metadata-only signals and keeps redacted snippets only for low-risk context.

## Local-Only Boundaries

- Backend host: `127.0.0.1`
- Backend port: `8765`
- Ollama default: `127.0.0.1:11434`
- LM Studio default: `127.0.0.1:1234`

No outbound cloud calls are required for runtime operation once dependencies and local models are installed.

## Docker Boundary

Docker runs the backend only. It does not capture the desktop and does not receive broad host mounts. The Compose profile:

- Avoids privileged mode
- Avoids Docker socket mounts
- Maps port to `127.0.0.1`
- Drops Linux capabilities
- Uses `no-new-privileges`
- Uses a named app-data volume
- Uses tmpfs for `/tmp`

Screen capture stays in the native desktop shell because OS capture permissions belong at the user desktop boundary.

## Deletion

The API supports session deletion, all-data deletion, and cleanup. Session deletion removes session rows, events, notes, rollups, redaction findings, model metadata, and exported Markdown for that session. Cleanup removes abandoned temp files. `/api/data` deletes local database rows plus exports/tmp artifacts while leaving the database file itself in place for the running service.

## Known Risks

- Local OCR engines are not yet integrated, so future integrations must be reviewed for temp-file behavior.
- GPU usage cannot be proven by the mock provider.
- A malicious local process could still call localhost APIs while the user is logged in; authentication should be added before multi-user enterprise deployment.
- SQLite is not encrypted in the MVP.

## Future Hardening

- Local API token or OS keychain-backed auth.
- Optional encrypted SQLite.
- Signed desktop builds.
- Per-session retention policies.
- Auditable network-deny mode.
- OCR engine sandboxing and secure temp-file wiping where the OS supports it.
