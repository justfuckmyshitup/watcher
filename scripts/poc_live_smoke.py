from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    configure_environment(args, repo_root)
    if not args.keep_session:
        shutil.rmtree(repo_root / "app-data" / "poc-smoke", ignore_errors=True)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from fastapi.testclient import TestClient
    from sqlalchemy import desc

    from backend.app.main import app
    from backend.app.storage.database import SessionLocal
    from backend.app.storage.models import ModelRun

    client = TestClient(app)
    result: dict[str, Any] = {
        "ok": False,
        "session_id": "",
        "safe_event_id": "",
        "sensitive_event_id": "",
        "note_id": "",
        "note_hash": "",
        "model_run_status": "",
        "model_run_provider": "",
        "control_lifecycle": {},
        "tmp_files_after": [],
        "deleted": False,
    }

    session_id = ""
    try:
        health = client.get("/api/health")
        health.raise_for_status()

        session = client.post(
            "/api/sessions",
            json={
                "objective": "Real POC smoke: GPU OCR, inferred privacy, and local note generation",
                "capture_interval_seconds": 1.0,
                "privacy_mode": True,
                "privacy_strictness": "strict",
                "ocr_provider": "mock" if args.skip_ocr else args.ocr_provider,
                "ocr_profile": args.ocr_profile,
                "model_provider": "mock" if args.skip_llm else args.model_provider,
                "app_exclusion_patterns": ["password manager", "authenticator", "banking"],
                "evidence_mode": False,
            },
        )
        session.raise_for_status()
        session_payload = session.json()
        session_id = session_payload["id"]
        result["session_id"] = session_id

        paused = client.post(f"/api/sessions/{session_id}/pause")
        paused.raise_for_status()
        assert paused.json()["status"] == "paused"
        paused_event = client.post(
            f"/api/sessions/{session_id}/events",
            json={
                "active_app": "Editor",
                "active_window_title": "Paused session",
                "capture_source": "poc-live-smoke",
                "screenshot_base64": base64.b64encode(b"paused-frame").decode("ascii"),
                "ocr_text": "This should be skipped while paused.",
                "user_selected_mode": "standard",
            },
        )
        paused_event.raise_for_status()
        assert paused_event.json() == {"skipped": True, "reason": "session_paused"}
        resumed = client.post(f"/api/sessions/{session_id}/resume")
        resumed.raise_for_status()
        assert resumed.json()["status"] == "active"
        result["control_lifecycle"]["pause_resume"] = "ok"

        safe_event = client.post(
            f"/api/sessions/{session_id}/events",
            json={
                "active_app": "Terminal",
                "active_window_title": "Watcher POC",
                "capture_source": "poc-live-smoke",
                "screenshot_base64": _synthetic_screen_png(),
                "ocr_text": "" if not args.skip_ocr else "Restarted backend, checked health, and generated local notes.",
                "user_selected_mode": "standard",
            },
        )
        safe_event.raise_for_status()
        safe_payload = safe_event.json()
        assert safe_payload["skipped"] is False, safe_payload
        safe_data = safe_payload["event"]
        assert safe_data["raw_artifact_persisted"] is False
        assert safe_data["privacy_action"] == "store_redacted"
        if not args.skip_ocr:
            assert safe_data["ocr_provider"] not in {"", "mock"}, safe_data
            if args.require_gpu:
                assert (safe_data.get("ocr") or {}).get("device") == "gpu:0" or safe_data.get("ocr_elapsed_ms") is not None
        result["safe_event_id"] = safe_data["id"]

        synthetic_value = "abcdefghijklmnopqrstuvwxyz123456"
        sensitive_event = client.post(
            f"/api/sessions/{session_id}/events",
            json={
                "active_app": "Terminal",
                "active_window_title": "Deployment",
                "capture_source": "poc-live-smoke",
                "screenshot_base64": base64.b64encode(b"synthetic-sensitive-frame").decode("ascii"),
                "ocr_text": f"Set {'api' + '_key'}={synthetic_value} and then rotated the deployment credential.",
                "user_selected_mode": "standard",
            },
        )
        sensitive_event.raise_for_status()
        sensitive_payload = sensitive_event.json()
        assert sensitive_payload["skipped"] is False, sensitive_payload
        sensitive_data = sensitive_payload["event"]
        assert sensitive_data["privacy_action"] == "metadata_only"
        assert synthetic_value not in json.dumps(sensitive_data)
        assert sensitive_data["redacted_text_snippet"] == ""
        result["sensitive_event_id"] = sensitive_data["id"]

        note = client.post(f"/api/sessions/{session_id}/notes", json={"mode": "activity_log"})
        note.raise_for_status()
        note_payload = note.json()
        markdown = note_payload["markdown"]
        assert "<think>" not in markdown.lower()
        assert synthetic_value not in markdown
        assert "raw screenshot" not in markdown.lower() or "not" in markdown.lower()
        if not args.skip_llm:
            assert note_payload["provider"] != "mock", note_payload
        result["note_id"] = note_payload["id"]
        result["note_hash"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

        with SessionLocal() as db:
            model_run = (
                db.query(ModelRun)
                .filter(ModelRun.session_id == session_id)
                .order_by(desc(ModelRun.created_at))
                .first()
            )
            assert model_run is not None
            result["model_run_status"] = model_run.status
            result["model_run_provider"] = model_run.provider
            if not args.skip_llm:
                assert model_run.status == "ok", model_run.error
                assert model_run.gpu_active is True if args.require_gpu else True

        cleanup = client.post("/api/cleanup")
        cleanup.raise_for_status()
        result["tmp_files_after"] = _tmp_files()
        assert result["tmp_files_after"] == []

        if not args.keep_session:
            stopped = client.post(f"/api/sessions/{session_id}/stop")
            stopped.raise_for_status()
            assert stopped.json()["status"] == "stopped"
            stopped_again = client.post(f"/api/sessions/{session_id}/stop")
            stopped_again.raise_for_status()
            assert stopped_again.json()["status"] == "stopped"
            resumed_after_stop = client.post(f"/api/sessions/{session_id}/resume")
            resumed_after_stop.raise_for_status()
            assert resumed_after_stop.json()["status"] == "stopped"
            stopped_event = client.post(
                f"/api/sessions/{session_id}/events",
                json={
                    "active_app": "Editor",
                    "active_window_title": "Stopped session",
                    "capture_source": "poc-live-smoke",
                    "screenshot_base64": base64.b64encode(b"stopped-frame").decode("ascii"),
                    "ocr_text": "This should be skipped after stop.",
                    "user_selected_mode": "standard",
                },
            )
            stopped_event.raise_for_status()
            assert stopped_event.json() == {"skipped": True, "reason": "session_stopped"}
            result["control_lifecycle"]["stop_idempotence"] = "ok"
            deleted = client.delete(f"/api/sessions/{session_id}")
            deleted.raise_for_status()
            result["deleted"] = deleted.json()["deleted"] is True

        result["ok"] = True
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        if session_id and not args.keep_session:
            try:
                client.post(f"/api/sessions/{session_id}/stop")
                client.delete(f"/api/sessions/{session_id}")
            except Exception:
                pass
        print(json.dumps(result, indent=2, ensure_ascii=True), file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the real Watcher POC loop in-process.")
    parser.add_argument("--ocr-provider", default="paddle")
    parser.add_argument("--ocr-profile", default="screen-fast")
    parser.add_argument("--model-provider", default="onnx-phi")
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--keep-session", action="store_true")
    return parser.parse_args()


def configure_environment(args: argparse.Namespace, repo_root: Path) -> None:
    os.environ.setdefault("WATCHER_APP_DATA", str(repo_root / "app-data" / "poc-smoke"))
    os.environ["WATCHER_PROVIDER"] = "mock" if args.skip_llm else args.model_provider
    os.environ["WATCHER_OCR_PROVIDER"] = "mock" if args.skip_ocr else args.ocr_provider
    os.environ["WATCHER_OCR_PROFILE"] = args.ocr_profile
    os.environ["WATCHER_REQUIRE_GPU"] = "true" if args.require_gpu else "false"
    os.environ["WATCHER_OCR_REQUIRE_GPU"] = "true" if args.require_gpu and not args.skip_ocr else "false"
    if not args.skip_llm and args.model_provider.lower() in {"onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx"}:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _synthetic_screen_png() -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1100, 260), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 48), "Restarted the backend service and checked the health endpoint.", fill="black")
    draw.text((32, 110), "Generated a local Markdown activity log from redacted context.", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _tmp_files() -> list[str]:
    from backend.app.config import settings

    if not settings.tmp_dir.exists():
        return []
    return [
        str(path)
        for path in settings.tmp_dir.rglob("*")
        if path.is_file() and ("ocr-cycle-" in str(path).lower() or "frame" in path.name.lower() or "screenshot" in path.name.lower())
    ]


if __name__ == "__main__":
    raise SystemExit(main())
