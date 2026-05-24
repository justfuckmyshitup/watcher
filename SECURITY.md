# Security Policy

Watcher handles screen-derived context, so security reports are taken seriously.

## Supported Status

This project is an experimental local-first POC. It is not a production security monitoring, compliance, or incident-response product.

## Reporting A Vulnerability

If you find a vulnerability, please do not open a public issue with sensitive details. Contact the project maintainer privately, or use GitHub private vulnerability reporting if it is enabled for the repository.

Useful reports include:

- A concise description of the issue
- Local reproduction steps
- Impact and affected files/components
- Whether raw screenshots, OCR text, logs, exports, model prompts, or database records are exposed
- Suggested remediation if known

Do not include real secrets, private screenshots, or unredacted OCR dumps.

## Security Design

The security design is documented in `docs/SECURITY.md`. The short version:

- Backend binds to localhost by default.
- No telemetry is implemented.
- No cloud AI calls are made by default.
- Capture is user-controlled.
- Raw screenshots are ephemeral processing material.
- Full unredacted OCR is not persisted by default.
- Docker backend mode does not receive desktop capture access.
- Model files are bring-your-own and should not be committed.
