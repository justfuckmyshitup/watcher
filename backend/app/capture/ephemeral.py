from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.context.focus_filter import clean_focus_text
from backend.app.redaction.service import redaction_service, stable_hash


class EphemeralFrameProcessor:
    """Process raw frame payloads without creating durable raw artifacts."""

    def __init__(self, tmp_dir: Path | None = None) -> None:
        self.tmp_dir = tmp_dir or settings.tmp_dir
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cleanup_abandoned_temp_files(max_age_seconds=300)

        screenshot_bytes = self._decode_data_url(payload.get("screenshot_base64") or "")
        screenshot_sha256 = stable_hash(screenshot_bytes) if screenshot_bytes else None
        perceptual_hash = self._cheap_perceptual_hash(screenshot_bytes) if screenshot_bytes else None

        raw_ocr_text = payload.get("ocr_text") or ""
        ocr_text_hash = stable_hash(raw_ocr_text) if raw_ocr_text else None
        redacted = redaction_service.redact_text(raw_ocr_text, payload.get("custom_redaction_terms") or [])
        window_score, window_findings = redaction_service.sensitive_window_score(
            payload.get("active_app") or "",
            payload.get("active_window_title") or "",
        )

        findings = [*redacted.findings, *window_findings]
        sensitivity_score = max(redacted.sensitivity_score, window_score)
        redacted_text = redacted.text[:4000]
        summary = self._summary_snippet(redacted_text)

        # Raw screenshots and unredacted OCR text go out of scope here. No file writes occur.
        del screenshot_bytes
        del raw_ocr_text

        return {
            "screenshot_sha256": screenshot_sha256,
            "perceptual_hash": perceptual_hash,
            "ocr_text_hash": ocr_text_hash,
            "redacted_text_snippet": redacted_text,
            "summary_snippet": summary,
            "sensitivity_score": sensitivity_score,
            "redaction_findings": findings,
            "raw_artifact_persisted": False,
        }

    def cleanup_abandoned_temp_files(self, max_age_seconds: int = 300) -> list[Path]:
        """Remove stale files from the short-lived processing directory."""

        removed: list[Path] = []
        now = time.time()
        if not self.tmp_dir.exists():
            return removed
        for path in self.tmp_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                if now - path.stat().st_mtime >= max_age_seconds:
                    path.unlink()
                    removed.append(path)
            except FileNotFoundError:
                continue
        return removed

    @staticmethod
    def _decode_data_url(value: str) -> bytes:
        if not value:
            return b""
        if "," in value and value.strip().lower().startswith("data:"):
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value, validate=False)
        except (binascii.Error, ValueError):
            return b""

    @staticmethod
    def _cheap_perceptual_hash(data: bytes) -> str:
        # MVP fallback: a stable coarse hash prefix. Future builds can replace this with imagehash.
        return stable_hash(data[:4096])[:16]

    @staticmethod
    def _summary_snippet(text: str) -> str:
        return clean_focus_text(text, strip_file_references=True, limit=280)


ephemeral_frame_processor = EphemeralFrameProcessor()
