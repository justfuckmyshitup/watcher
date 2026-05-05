from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ.setdefault("LOCAL_SCRIBE_PROVIDER", "mock")
os.environ.setdefault("LOCAL_SCRIBE_OCR_PROVIDER", "mock")

from backend.app.main import app
from backend.app.ocr import providers as ocr_providers
from backend.app.ocr.providers import OcrResult, OcrTextLine, PaddleOcrProvider, _extract_lines


client = TestClient(app)


def test_mock_ocr_diagnostics_endpoint() -> None:
    response = client.get("/api/diagnostics/ocr")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock"
    assert data["available"] is True


def test_paddle_diagnostics_reports_missing_package(monkeypatch) -> None:
    def fake_module_exists(name: str) -> bool:
        if name == "paddleocr":
            return False
        return True

    monkeypatch.setattr(ocr_providers, "_module_exists", fake_module_exists)

    diagnostics = PaddleOcrProvider(require_gpu=True).diagnostics()

    assert diagnostics["provider"] == "paddle"
    assert diagnostics["available"] is False
    assert "paddleocr_not_installed" in diagnostics["reasons"]


def test_extract_lines_from_paddle_json_payload() -> None:
    raw = [{"res": {"rec_texts": ["Open settings", "Restart service"], "rec_scores": [0.91, 0.87]}}]

    lines = _extract_lines(raw)

    assert [line.text for line in lines] == ["Open settings", "Restart service"]
    assert lines[0].confidence == 0.91


def test_ingest_uses_ocr_result_before_privacy(monkeypatch) -> None:
    class FakeOcrProvider:
        name = "fake"

        def extract_text(self, image_bytes: bytes) -> OcrResult:
            assert image_bytes == b"synthetic-frame"
            return OcrResult(
                text="Restarted backend and checked health endpoint",
                lines=[OcrTextLine("Restarted backend and checked health endpoint", 0.99)],
                provider="fake",
                profile="screen-fast",
                device="gpu:0",
                elapsed_ms=1.2,
            )

    def fake_provider(_name: str | None = None, **_kwargs: object) -> FakeOcrProvider:
        return FakeOcrProvider()

    monkeypatch.setenv("LOCAL_SCRIBE_OCR_PROVIDER", "fake")
    monkeypatch.setattr("backend.app.ocr.providers.get_ocr_provider", fake_provider)

    session = client.post("/api/sessions", json={"objective": "ocr ingest test"}).json()
    response = client.post(
        f"/api/sessions/{session['id']}/events",
        json={
            "active_app": "Terminal",
            "active_window_title": "Local Scribe",
            "capture_source": "desktop",
            "screenshot_base64": base64.b64encode(b"synthetic-frame").decode("ascii"),
            "ocr_text": "",
        },
    )

    assert response.status_code == 200
    event = response.json()["event"]
    assert event["privacy_action"] == "store_redacted"
    assert "Restarted backend" in event["redacted_text_snippet"]
    assert event["raw_artifact_persisted"] is False


def test_ocr_temp_directory_cleanup_in_temp_mode(monkeypatch) -> None:
    class FakePipeline:
        def predict(self, path: str) -> list[dict[str, object]]:
            assert Path(path).exists()
            return [{"res": {"rec_texts": ["temporary file OCR"], "rec_scores": [0.8]}}]

    temp_root = Path.cwd() / "app-data" / "tmp" / f"pytest-ocr-{uuid4()}"
    temp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ocr_providers.settings, "tmp_dir", temp_root)
    try:
        result = PaddleOcrProvider._predict_with_temp_file(FakePipeline(), b"fake-image-bytes")

        assert _extract_lines(result)[0].text == "temporary file OCR"
        assert list(temp_root.rglob("*")) == []
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
