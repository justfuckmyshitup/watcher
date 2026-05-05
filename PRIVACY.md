# Privacy

Local Scribe is designed around explicit local capture and compact redacted memory.

## Core Rule

Capture raw context only long enough to process it, then discard it.

By default:

- Raw screenshots are not stored.
- Temporary frame files are avoided where possible.
- Full unredacted OCR dumps are not stored.
- Sensitive intermediate artifacts are not retained.
- Evidence screenshots are not implemented.
- Clipboard capture and keylogging are not implemented.
- Durable data is local SQLite metadata, hashes, redacted snippets, summaries, notes, model run metadata, redaction findings, and user action logs.

## Community Sharing Warning

Before opening an issue, pull request, discussion, or demo recording, review any logs, notes, screenshots, OCR snippets, database files, and exports. Do not share private screen content, secrets, account numbers, personal data, or proprietary information.

## More Detail

See `docs/PRIVACY.md` for the full privacy architecture and retention notes.
