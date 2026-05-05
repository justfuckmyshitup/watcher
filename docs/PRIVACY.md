# Privacy

Local Scribe is a user-controlled productivity tool, not surveillance software.

## Consent Model

Capture starts only when the user clicks Start and grants OS screen capture permission. The UI shows capture state continuously. Pause and Stop controls are always visible.

## Session Lifecycle

1. User starts a session.
2. Session privacy, OCR, model, interval, and exclusion settings are recorded.
3. The desktop shell captures frames under OS/user permission.
4. Frames are processed into structured events.
5. Raw frame bytes are discarded.
6. Notes are generated from redacted structured memory.
7. User can export Markdown or delete the session.

Deleting a session removes its structured context, generated notes, rollups, model metadata, and exported Markdown files for that session. The all-data delete endpoint removes all local database rows plus exports and temporary files.

## Data Retention

Stored by default:

- Session metadata
- Redacted snippets
- Hashes for deduplication
- App/window metadata
- Topic/task rollups
- Generated notes and exports
- Redaction findings with value hashes
- User action logs
- OCR provider/run metadata when OCR is used

Not stored by default:

- Raw screenshots
- Full unredacted OCR text
- OCR intermediate files
- Clipboard data
- Keystrokes
- Long-term image archives
- Evidence screenshots

## Redaction Behavior

OCR/manual text is redacted before persistence and before model ingestion. Findings store category, replacement label, confidence, and hash. Sensitive windows and user-defined exclusions can skip processing entirely.

Session privacy strictness controls how conservative the decision engine is:

- `standard`: store redacted snippets unless built-in high-risk signals require metadata-only or drop.
- `strict`: any redaction finding or elevated sensitivity moves the event to metadata-only.
- `maximum`: high-risk metadata-only signals are dropped, and any redaction finding becomes metadata-only.

## Privacy Decision Engine

After redaction, each frame receives an explicit privacy action before a `ContextEvent` is written:

- `store_redacted`: store hashes, metadata, redacted snippets, findings, and rollup inputs.
- `metadata_only`: store hashes, app/window metadata, sensitivity score, and privacy decision metadata, but no OCR text snippet.
- `drop_event`: store no `ContextEvent`; only a user action log records that capture was dropped by privacy policy.
- `needs_user_review`: reserved for a future consent workflow.

Password managers, authenticator/MFA windows, private keys, masked password fields, and MFA codes are dropped by default. Banking, payroll, medical, billing, account-number, SSN, credit-card, routing-number, and IBAN signals default to metadata-only unless a future explicit override is added.

The decision metadata records action, reasons, sensitivity score, and retention policy. It does not store raw screenshots or unredacted OCR.

## OCR Processing

Live OCR is opt-in by provider configuration. The default OCR provider is mock/no-op. The PaddleOCR provider processes frame bytes in memory by default and passes extracted text through redaction and privacy decisions before any storage.

Temporary OCR files are disabled unless explicitly configured with `LOCAL_SCRIBE_OCR_ALLOW_TEMP_FILES=true`. If enabled, files are scoped to `app-data/tmp/ocr-cycle-*` and deleted in the same processing cycle.

Stored OCR metadata is limited to provider/profile/device, elapsed time, line count, confidence aggregate, and whether temporary files were used. Raw OCR text is not stored outside redacted snippets, and metadata-only/drop decisions do not retain snippets.

## App And Window Exclusions

Exclusion rules can match app names, window titles, or both. If a rule matches, the backend skips event creation and discards any transient payload. Exclusions are separate from the built-in privacy decision engine; both can prevent text persistence.

Sessions may also carry lightweight comma/newline-separated exclusion patterns. These are checked before OCR/context event creation and are useful for one-off workflows.

## Evidence Mode

Evidence screenshot retention is not implemented in the MVP. If added later, it must be opt-in per session, visibly indicated, and include separate retention and deletion controls.
