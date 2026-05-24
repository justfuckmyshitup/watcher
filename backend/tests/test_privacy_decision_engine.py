from __future__ import annotations

import base64
import os

from fastapi.testclient import TestClient

os.environ.setdefault("WATCHER_PROVIDER", "mock")

from backend.app.main import app
from backend.app.privacy.decision_engine import privacy_decision_engine
from backend.app.redaction.service import redaction_service


client = TestClient(app)


def test_password_manager_window_drops_event() -> None:
    redacted = redaction_service.redact_text("password: synthetic-secret-value")
    decision = privacy_decision_engine.evaluate(
        active_app="Bitwarden",
        window_title="Password Manager",
        redacted_text=redacted.text,
        redaction_findings=redacted.findings,
        sensitivity_score=redacted.sensitivity_score,
    )

    assert decision.action == "drop_event"
    assert decision.retention_policy["persist_redacted_text"] is False
    assert decision.retention_policy["persist_metadata"] is False


def test_account_number_text_is_metadata_only() -> None:
    redacted = redaction_service.redact_text("Customer account number: 123456789012")
    decision = privacy_decision_engine.evaluate(
        active_app="Browser",
        window_title="Billing portal",
        redacted_text=redacted.text,
        redaction_findings=redacted.findings,
        sensitivity_score=redacted.sensitivity_score,
    )

    assert decision.action == "metadata_only"
    assert decision.retention_policy["persist_redacted_text"] is False
    assert decision.retention_policy["persist_metadata"] is True


def test_safe_text_is_stored_redacted() -> None:
    redacted = redaction_service.redact_text("Restarted the local backend and checked the health endpoint.")
    decision = privacy_decision_engine.evaluate(
        active_app="Terminal",
        window_title="Watcher",
        redacted_text=redacted.text,
        redaction_findings=redacted.findings,
        sensitivity_score=redacted.sensitivity_score,
    )

    assert decision.action == "store_redacted"
    assert decision.retention_policy["persist_redacted_text"] is True


def test_ingest_metadata_only_does_not_store_ocr_text() -> None:
    session = client.post("/api/sessions", json={"objective": "metadata-only privacy test"}).json()
    payload = {
        "active_app": "Browser",
        "active_window_title": "Banking account details",
        "capture_source": "desktop",
        "screenshot_base64": base64.b64encode(b"synthetic-bank-frame").decode("ascii"),
        "ocr_text": "Routing number 021000021 account number 123456789012",
    }
    response = client.post(f"/api/sessions/{session['id']}/events", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] is False
    event = body["event"]
    assert event["privacy_action"] == "metadata_only"
    assert event["event_type"] == "metadata_only"
    assert event["redacted_text_snippet"] == ""
    assert "123456789012" not in event["summary_snippet"]
    assert event["raw_artifact_persisted"] is False


def test_ingest_drop_event_does_not_create_context_event() -> None:
    session = client.post("/api/sessions", json={"objective": "drop-event privacy test"}).json()
    payload = {
        "active_app": "1Password",
        "active_window_title": "Password vault",
        "capture_source": "desktop",
        "screenshot_base64": base64.b64encode(b"synthetic-password-frame").decode("ascii"),
        "ocr_text": "password: synthetic-secret-value",
    }
    response = client.post(f"/api/sessions/{session['id']}/events", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] is True
    assert body["reason"] == "privacy_drop_event"
    assert body["privacy_decision"]["action"] == "drop_event"

    events = client.get(f"/api/sessions/{session['id']}/events").json()
    assert events == []
