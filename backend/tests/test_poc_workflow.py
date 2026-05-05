from __future__ import annotations

import base64
import json
import os
import datetime as dt

from fastapi.testclient import TestClient

os.environ.setdefault("LOCAL_SCRIBE_PROVIDER", "mock")
os.environ.setdefault("LOCAL_SCRIBE_OCR_PROVIDER", "mock")

from backend.app.main import app
from backend.app.notes.generator import NoteGenerator
from backend.app.ocr.providers import OcrResult, OcrTextLine
from backend.app.storage.models import ContextEvent, Session


client = TestClient(app)


def test_session_settings_are_applied_to_ocr_and_event_metadata(monkeypatch) -> None:
    class FakeOcrProvider:
        name = "fake"

        def extract_text(self, image_bytes: bytes) -> OcrResult:
            assert image_bytes == b"workflow-frame"
            return OcrResult(
                text="Restarted the backend service and verified the health endpoint",
                lines=[OcrTextLine("Restarted the backend service and verified the health endpoint", 0.98)],
                provider="fake",
                profile="screen-accurate",
                device="gpu:0",
                elapsed_ms=12.5,
            )

    def fake_provider(name: str | None = None, *, profile: str | None = None, **_kwargs: object) -> FakeOcrProvider:
        assert name == "paddle"
        assert profile == "screen-accurate"
        return FakeOcrProvider()

    monkeypatch.setattr("backend.app.ocr.providers.get_ocr_provider", fake_provider)

    session = client.post(
        "/api/sessions",
        json={
            "objective": "end-to-end workflow",
            "capture_interval_seconds": 1.5,
            "privacy_strictness": "strict",
            "ocr_provider": "paddle",
            "ocr_profile": "screen-accurate",
            "model_provider": "mock",
            "app_exclusion_patterns": ["payroll"],
        },
    ).json()

    assert session["ocr_provider"] == "paddle"
    assert session["ocr_profile"] == "screen-accurate"
    assert session["privacy_strictness"] == "strict"
    assert session["app_exclusion_patterns"] == ["payroll"]

    response = client.post(
        f"/api/sessions/{session['id']}/events",
        json={
            "active_app": "Terminal",
            "active_window_title": "Local Scribe POC",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"workflow-frame").decode("ascii"),
            "ocr_text": "",
        },
    )

    assert response.status_code == 200
    event = response.json()["event"]
    assert event["privacy_action"] == "store_redacted"
    assert event["ocr_provider"] == "fake"
    assert event["ocr_profile"] == "screen-accurate"
    assert event["ocr_confidence"] == 0.98
    assert event["ocr_elapsed_ms"] == 12.5
    assert "verified the health endpoint" in event["redacted_text_snippet"]


def test_strict_privacy_moves_secret_findings_to_metadata_only() -> None:
    session = client.post(
        "/api/sessions",
        json={"objective": "strict privacy", "privacy_strictness": "strict"},
    ).json()
    response = client.post(
        f"/api/sessions/{session['id']}/events",
        json={
            "active_app": "Terminal",
            "active_window_title": "Deployment",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"strict-frame").decode("ascii"),
            "ocr_text": "Set " + "api" + "_key" + "=" + "abcdefghijklmnopqrstuvwxyz123456 and restarted service",
        },
    )

    assert response.status_code == 200
    event = response.json()["event"]
    assert event["privacy_action"] == "metadata_only"
    assert event["redacted_text_snippet"] == ""
    assert event["redaction_count"] >= 1
    assert event["raw_artifact_persisted"] is False


def test_session_exclusion_skips_before_context_event_storage() -> None:
    session = client.post(
        "/api/sessions",
        json={"objective": "session exclusion", "app_exclusion_patterns": ["payroll"]},
    ).json()
    response = client.post(
        f"/api/sessions/{session['id']}/events",
        json={
            "active_app": "Browser",
            "active_window_title": "Payroll dashboard",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"excluded-frame").decode("ascii"),
            "ocr_text": "Timesheet approved",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"skipped": True, "reason": "session_exclusion_rule"}
    assert client.get(f"/api/sessions/{session['id']}/events").json() == []


def test_session_goal_guides_event_classification() -> None:
    session = client.post(
        "/api/sessions",
        json={"objective": "Track marketing material and school work separately."},
    ).json()
    response = client.post(
        f"/api/sessions/{session['id']}/events",
        json={
            "active_app": "Editor",
            "active_window_title": "Assignment outline",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"goal-frame").decode("ascii"),
            "ocr_text": "Drafting an essay outline and collecting research citations",
        },
    )

    assert response.status_code == 200
    event = response.json()["event"]
    assert event["detected_topic"] == "education"
    assert event["detected_task"] in {"research", "writing"}


def test_duplicate_screenshot_skips_before_ocr(monkeypatch) -> None:
    calls = {"count": 0}

    class FakeOcrProvider:
        name = "fake"

        def extract_text(self, image_bytes: bytes) -> OcrResult:
            calls["count"] += 1
            return OcrResult(
                text="Writing a marketing campaign outline",
                lines=[OcrTextLine("Writing a marketing campaign outline", 0.98)],
                provider="fake",
                profile="screen-fast",
                device="gpu:0",
                elapsed_ms=10,
            )

    monkeypatch.setattr("backend.app.ocr.providers.get_ocr_provider", lambda *_args, **_kwargs: FakeOcrProvider())
    session = client.post(
        "/api/sessions",
        json={"objective": "marketing work", "ocr_provider": "paddle", "model_provider": "mock"},
    ).json()
    payload = {
        "active_app": "Editor",
        "active_window_title": "Campaign notes",
        "capture_source": "desktop",
        "screenshot_base64": base64.b64encode(b"same-frame").decode("ascii"),
        "ocr_text": "",
    }

    first = client.post(f"/api/sessions/{session['id']}/events", json=payload).json()
    second = client.post(f"/api/sessions/{session['id']}/events", json=payload).json()

    assert first["skipped"] is False
    assert second["skipped"] is True
    assert second["reason"] == "duplicate_frame"
    assert calls["count"] == 1


def test_session_control_lifecycle_is_idempotent_and_stopped_sessions_do_not_ingest() -> None:
    session = client.post("/api/sessions", json={"objective": "session controls"}).json()
    session_id = session["id"]

    paused = client.post(f"/api/sessions/{session_id}/pause").json()
    paused_again = client.post(f"/api/sessions/{session_id}/pause").json()
    resumed = client.post(f"/api/sessions/{session_id}/resume").json()
    stopped = client.post(f"/api/sessions/{session_id}/stop").json()
    resumed_after_stop = client.post(f"/api/sessions/{session_id}/resume").json()
    stopped_again = client.post(f"/api/sessions/{session_id}/stop").json()

    assert paused["status"] == "paused"
    assert paused_again["status"] == "paused"
    assert resumed["status"] == "active"
    assert stopped["status"] == "stopped"
    assert stopped["ended_at"]
    assert resumed_after_stop["status"] == "stopped"
    assert stopped_again["status"] == "stopped"

    response = client.post(
        f"/api/sessions/{session_id}/events",
        json={
            "active_app": "Editor",
            "active_window_title": "Stopped session",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"after-stop-frame").decode("ascii"),
            "ocr_text": "This should not be stored after stop.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"skipped": True, "reason": "session_stopped"}
    assert client.get(f"/api/sessions/{session_id}/events").json() == []


def test_starting_new_session_supersedes_prior_open_session() -> None:
    first = client.post("/api/sessions", json={"objective": "first open session"}).json()
    second = client.post("/api/sessions", json={"objective": "second open session"}).json()

    refreshed_first = client.get(f"/api/sessions/{first['id']}").json()
    diagnostics = client.get("/api/diagnostics").json()
    response = client.post(
        f"/api/sessions/{first['id']}/events",
        json={
            "active_app": "Editor",
            "active_window_title": "Superseded session",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"old-open-frame").decode("ascii"),
            "ocr_text": "This should not be stored on a superseded session.",
        },
    )

    assert refreshed_first["status"] == "stopped"
    assert refreshed_first["ended_at"]
    assert second["status"] == "active"
    assert diagnostics["active_session_id"] == second["id"]
    assert response.json() == {"skipped": True, "reason": "session_stopped"}


def test_backend_startup_closes_open_sessions() -> None:
    from backend.app.main import close_open_sessions_on_start

    session = client.post("/api/sessions", json={"objective": "stale after app restart"}).json()

    result = close_open_sessions_on_start()
    refreshed = client.get(f"/api/sessions/{session['id']}").json()
    diagnostics = client.get("/api/diagnostics").json()

    assert result["closed_sessions"] >= 1
    assert refreshed["status"] == "stopped"
    assert refreshed["ended_at"]
    assert diagnostics["active_session_id"] is None


def test_note_sanitizer_removes_markdown_fence() -> None:
    cleaned = NoteGenerator._sanitize_model_output("```markdown\n# Activity Log\n\nDone\n```")

    assert cleaned == "# Activity Log\n\nDone"


def test_deterministic_notes_are_quality_aware_and_do_not_dump_old_boilerplate() -> None:
    session = Session(
        id="session-quality-test",
        objective="Track writing work and useful details.",
        started_at=dt.datetime(2026, 5, 3, 12, 45, tzinfo=dt.UTC),
        ended_at=dt.datetime(2026, 5, 3, 12, 50, tzinfo=dt.UTC),
        ocr_provider="paddle",
        ocr_profile="screen-fast",
        model_provider="mock",
        privacy_mode=True,
        privacy_strictness="strict",
        evidence_mode=False,
    )
    event = ContextEvent(
        timestamp=dt.datetime(2026, 5, 3, 12, 46, tzinfo=dt.UTC),
        active_app="Desktop",
        active_window_title="Screen 2",
        redacted_text_snippet="File Edit View This is a test sentence about marketing copy. Ln 1, Col 1 Plain text Windows (CRLF) UTF-8",
        summary_snippet="File Edit View This is a test sentence about marketing copy. Ln 1, Col 1 Plain text Windows (CRLF) UTF-8",
        detected_topic="marketing",
        detected_task="writing",
        sensitivity_score=0,
        redaction_summary=json.dumps(
            {
                "privacy_decision": {"action": "store_redacted"},
                "ocr": {"average_confidence": 0.64, "elapsed_ms": 4373, "lines": []},
            }
        ),
    )

    markdown = NoteGenerator()._deterministic_markdown(session, [event], "Activity Log", "activity_log", "mock")

    assert "## Capture Quality" in markdown
    assert "low OCR confidence" in markdown
    assert "This is a test sentence about marketing copy" in markdown
    assert "File Edit View" not in markdown
    assert "Durable memory contains only structured metadata" not in markdown
