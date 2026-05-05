from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ.setdefault("LOCAL_SCRIBE_PROVIDER", "mock")

from backend.app.capture.ephemeral import EphemeralFrameProcessor
from backend.app.main import app


client = TestClient(app)


def test_ingest_does_not_persist_raw_screenshot_artifacts() -> None:
    session = client.post("/api/sessions", json={"objective": "ephemeral raw capture test"}).json()
    payload = {
        "active_app": "Terminal",
        "active_window_title": "Admin task",
        "capture_source": "desktop",
        "screenshot_base64": base64.b64encode(b"fake-png-bytes").decode("ascii"),
        "ocr_text": "Set " + "api" + "_key" + "=" + "abc123456789012345678901234 then restarted service",
    }
    response = client.post(f"/api/sessions/{session['id']}/events", json=payload)

    assert response.status_code == 200
    event = response.json()["event"]
    assert event["raw_artifact_persisted"] is False
    assert event["screenshot_sha256"]
    assert "[REDACTED_SECRET]" in event["redacted_text_snippet"]


def test_cleanup_removes_abandoned_temp_files() -> None:
    tmp_dir = Path.cwd() / "app-data" / "tmp" / f"pytest-{uuid4()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    processor = EphemeralFrameProcessor(tmp_dir)
    stale = tmp_dir / "stale-frame.tmp"
    stale.write_bytes(b"temporary frame")
    old = time.time() - 1000
    os.utime(stale, (old, old))

    removed = processor.cleanup_abandoned_temp_files(max_age_seconds=300)

    assert stale in removed
    assert not stale.exists()
    tmp_dir.rmdir()


def test_summary_snippet_removes_common_editor_chrome() -> None:
    snippet = EphemeralFrameProcessor._summary_snippet(
        "File Edit View This is a typed note about school work. Ln 1, Col 1 Plain text 100% Windows (CRLF) UTF-8"
    )

    assert snippet == "This is a typed note about school work"
