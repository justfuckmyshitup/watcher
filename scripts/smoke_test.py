from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


API = os.getenv("WATCHER_API", "http://127.0.0.1:8765/api")


def request(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = request("/health")
        assert health["ok"]
        session = request("/sessions", "POST", {"objective": "smoke test", "capture_interval_seconds": 3})
        frame = base64.b64encode(b"transient fake frame").decode("ascii")
        event_result = request(
            f"/sessions/{session['id']}/events",
            "POST",
            {
                "active_app": "SmokeTest",
                "active_window_title": "Local workflow",
                "screenshot_base64": frame,
                "ocr_text": "Restarted service after seeing token=abc12345678901234567890",
            },
        )
        assert event_result["skipped"] is False
        assert event_result["event"]["raw_artifact_persisted"] is False
        assert "[REDACTED_SECRET]" in event_result["event"]["redacted_text_snippet"]
        note = request(f"/sessions/{session['id']}/notes", "POST", {"mode": "sop"})
        export = request(f"/notes/{note['id']}/export", "POST")
        export_path = Path(export["path"])
        assert export_path.exists()
        stopped = request(f"/sessions/{session['id']}/stop", "POST")
        assert stopped["status"] == "stopped"
        deleted = request(f"/sessions/{session['id']}", "DELETE")
        assert deleted["deleted"] is True
        assert not export_path.exists()
        cleanup = request("/cleanup", "POST")
        print(json.dumps({"health": health, "event": event_result["event"]["id"], "export": export["path"], "cleanup": cleanup}, indent=2))
        return 0
    except urllib.error.URLError as exc:
        print(f"Backend is not reachable at {API}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
