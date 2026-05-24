from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import settings
from backend.app.models.manifest import get_default_model_entry
from backend.app.ocr.providers import OcrProviderError, get_ocr_provider
from backend.app.privacy.decision_engine import privacy_decision_engine
from backend.app.redaction.service import redaction_service, stable_hash
from backend.app.runtime.gpu import collect_gpu_diagnostics
from backend.app.runtime.providers import get_provider


SAFE_OCR_TEXT = "Restarted the backend service, checked health, and generated a redacted workflow note."


def main() -> int:
    args = parse_args()
    settings.ensure_directories()
    output_dir = Path(args.output_dir or (settings.app_data_dir / "benchmarks"))
    output_dir.mkdir(parents=True, exist_ok=True)

    settings.require_gpu = bool(args.require_gpu)
    os.environ["WATCHER_REQUIRE_GPU"] = "true" if args.require_gpu else "false"
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    started = datetime.now(UTC)
    before_tmp = _tmp_files()
    report: dict[str, Any] = {
        "version": 1,
        "started_at": started.isoformat(),
        "completed_at": None,
        "parameters": vars(args),
        "privacy_posture": {
            "raw_screenshots_persisted": False,
            "unredacted_ocr_persisted": False,
            "cloud_ai_calls": False,
            "backend_binding": "127.0.0.1",
        },
        "gpu_before": collect_gpu_diagnostics(require_gpu=args.require_gpu, probe_packages=True),
        "offline": offline_report(),
        "privacy_regression": privacy_regression(),
        "ocr": {},
        "llm": {},
        "tmp_cleanup": {},
        "acceptance": {},
    }

    if not args.skip_ocr:
        report["ocr"] = benchmark_ocr(args.ocr_provider, args.ocr_profile, args.iterations, args.require_gpu)
    else:
        report["ocr"] = {"status": "skipped", "reason": "skip_ocr_requested"}

    if not args.skip_llm:
        report["llm"] = benchmark_llm(args.model_provider, args.iterations)
    else:
        report["llm"] = {"status": "skipped", "reason": "skip_llm_requested"}

    report["gpu_after"] = collect_gpu_diagnostics(require_gpu=args.require_gpu, probe_packages=True)
    removed = _cleanup_tmp()
    after_tmp = _tmp_files()
    report["tmp_cleanup"] = {
        "files_before": len(before_tmp),
        "files_after": len(after_tmp),
        "removed": [str(path) for path in removed],
        "raw_frame_temp_files_remaining": [
            str(path)
            for path in after_tmp
            if "ocr-cycle-" in str(path).lower() or "frame" in path.name.lower() or "screenshot" in path.name.lower()
        ],
    }
    report["acceptance"] = acceptance(report, require_gpu=args.require_gpu)
    report["completed_at"] = datetime.now(UTC).isoformat()

    stamp = started.strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"poc-benchmark-{stamp}.json"
    md_path = output_dir / f"poc-benchmark-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"[Watcher] Benchmark JSON: {json_path}")
        print(f"[Watcher] Benchmark report: {md_path}")
        print(f"[Watcher] Acceptance passed: {report['acceptance']['passed']}")
        for item in report["acceptance"]["failures"]:
            print(f"[Watcher] BLOCKED: {item}")
        for item in report["acceptance"]["warnings"]:
            print(f"[Watcher] WARNING: {item}")

    return 0 if report["acceptance"]["passed"] or args.allow_incomplete else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark and harden the Watcher POC runtime.")
    parser.add_argument("--ocr-provider", default=os.getenv("WATCHER_OCR_PROVIDER", "mock"))
    parser.add_argument("--ocr-profile", default=os.getenv("WATCHER_OCR_PROFILE", "screen-fast"))
    parser.add_argument("--model-provider", default=os.getenv("WATCHER_PROVIDER", "mock"))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def benchmark_ocr(provider_name: str, profile: str, iterations: int, require_gpu: bool) -> dict[str, Any]:
    os.environ["WATCHER_OCR_PROVIDER"] = provider_name
    os.environ["WATCHER_OCR_PROFILE"] = profile
    os.environ["WATCHER_OCR_REQUIRE_GPU"] = "true" if require_gpu else "false"
    provider = get_ocr_provider(provider_name, profile=profile, require_gpu=require_gpu)
    diagnostics = provider.diagnostics()
    result: dict[str, Any] = {
        "provider": provider.name,
        "profile": profile,
        "diagnostics": diagnostics,
    }
    if provider.name == "mock":
        result.update({"status": "skipped", "reason": "mock_ocr_provider"})
        return result
    if not diagnostics.get("available"):
        result.update({"status": "blocked", "reason": "ocr_provider_not_ready", "reasons": diagnostics.get("reasons", [])})
        return result

    image_bytes = _synthetic_png()
    durations: list[float] = []
    line_counts: list[int] = []
    try:
        for _ in range(max(1, iterations)):
            start = time.perf_counter()
            ocr = provider.extract_text(image_bytes)
            durations.append((time.perf_counter() - start) * 1000)
            line_counts.append(len(ocr.lines))
    except OcrProviderError as exc:
        result.update({"status": "failed", "error": str(exc)})
        return result
    finally:
        del image_bytes

    result.update(
        {
            "status": "ok",
            "iterations": len(durations),
            "latency_ms": _stats(durations),
            "line_count": _stats([float(count) for count in line_counts]),
            "gpu_required": require_gpu,
        }
    )
    return result


def benchmark_llm(provider_name: str, iterations: int) -> dict[str, Any]:
    provider = get_provider(provider_name)
    health = provider.health_check()
    result: dict[str, Any] = {
        "provider": provider.name,
        "health": health,
        "models": _safe_list_models(provider),
    }
    if provider.name == "mock":
        result.update({"status": "skipped", "reason": "mock_model_provider"})
        return result
    if not health.get("ok"):
        result.update({"status": "blocked", "reason": "model_provider_not_ready", "reasons": health.get("reasons") or health.get("error")})
        return result

    prompt = (
        "Generate a concise Markdown activity log from these redacted events. "
        "Preserve [REDACTED_SECRET] exactly.\n"
        "- [2026-05-02T20:00:00Z] Terminal: restarted backend and checked /api/health.\n"
        "- [2026-05-02T20:01:00Z] Browser: reviewed deployment notes with [REDACTED_SECRET]."
    )
    durations: list[float] = []
    output_lengths: list[float] = []
    last_output_hash = ""
    for _ in range(max(1, iterations)):
        start = time.perf_counter()
        output = provider.generate(prompt)
        durations.append((time.perf_counter() - start) * 1000)
        output_lengths.append(float(len(output.split())))
        last_output_hash = stable_hash(output)
    tokens_per_second = [
        length / (duration / 1000)
        for length, duration in zip(output_lengths, durations, strict=False)
        if duration > 0
    ]
    result.update(
        {
            "status": "ok",
            "iterations": len(durations),
            "latency_ms": _stats(durations),
            "approx_output_tokens": _stats(output_lengths),
            "approx_tokens_per_second": _stats(tokens_per_second),
            "last_output_hash": last_output_hash,
        }
    )
    return result


def privacy_regression() -> dict[str, Any]:
    cases = [
        {
            "name": "password_assignment",
            "app": "Terminal",
            "title": "Deployment",
            "text": "password: SyntheticSecret123!",
            "must_not_contain": ["SyntheticSecret123"],
            "expected_action": "metadata_only",
            "strictness": "standard",
        },
        {
            "name": "api_key_strict",
            "app": "Terminal",
            "title": "Deployment",
            "text": "api" + "_key" + "=" + "abcdefghijklmnopqrstuvwxyz123456",
            "must_not_contain": ["abcdefghijklmnopqrstuvwxyz123456"],
            "expected_action": "metadata_only",
            "strictness": "strict",
        },
        {
            "name": "banking_metadata",
            "app": "Browser",
            "title": "Banking account",
            "text": "Routing number 021000021 account number 123456789012",
            "must_not_contain": ["021000021", "123456789012"],
            "expected_action": "metadata_only",
            "strictness": "standard",
        },
        {
            "name": "mfa_drop",
            "app": "Authenticator",
            "title": "MFA code",
            "text": "Verification code 123456",
            "must_not_contain": ["123456"],
            "expected_action": "drop_event",
            "strictness": "standard",
        },
        {
            "name": "safe_store",
            "app": "Terminal",
            "title": "Watcher",
            "text": "Restarted the backend service and generated notes.",
            "must_not_contain": [],
            "expected_action": "store_redacted",
            "strictness": "standard",
        },
    ]
    results = []
    failures = []
    for case in cases:
        redacted = redaction_service.redact_text(case["text"])
        decision = privacy_decision_engine.evaluate(
            active_app=case["app"],
            window_title=case["title"],
            redacted_text=redacted.text,
            redaction_findings=redacted.findings,
            sensitivity_score=redacted.sensitivity_score,
            privacy_strictness=case["strictness"],
        )
        leaked = [value for value in case["must_not_contain"] if value and value in redacted.text]
        ok = not leaked and decision.action == case["expected_action"]
        if not ok:
            failures.append({"case": case["name"], "leaked": leaked, "action": decision.action, "expected": case["expected_action"]})
        results.append(
            {
                "name": case["name"],
                "ok": ok,
                "action": decision.action,
                "sensitivity_score": decision.sensitivity_score,
                "redaction_count": len(redacted.findings),
                "redacted_text_hash": stable_hash(redacted.text),
            }
        )
    return {"passed": len(failures) == 0, "cases": results, "failures": failures}


def offline_report() -> dict[str, Any]:
    entry = get_default_model_entry()
    selected_path = entry.selected_path
    return {
        "hf_hub_offline": os.getenv("HF_HUB_OFFLINE") == "1",
        "transformers_offline": os.getenv("TRANSFORMERS_OFFLINE") == "1",
        "selected_model": entry.repo_id,
        "selected_path": str(selected_path),
        "model_files_ready": selected_path.exists() and ((selected_path / "genai_config.json").exists() or (selected_path / "config.json").exists()),
        "manifest_present": (settings.models_dir / "manifest.json").exists(),
    }


def acceptance(report: dict[str, Any], *, require_gpu: bool) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    gpu = report["gpu_after"]
    if require_gpu and not gpu.get("hardware_ready"):
        failures.append("NVIDIA GPU hardware was required but not detected.")
    if require_gpu and not gpu.get("provider_ready"):
        failures.append("NVIDIA GPU was detected, but no Python GPU inference provider is ready.")
    if not report["privacy_regression"]["passed"]:
        failures.append("Privacy regression corpus failed.")
    if report["tmp_cleanup"]["raw_frame_temp_files_remaining"]:
        failures.append("Raw frame or OCR-cycle temp files remained after benchmark cleanup.")

    if report["ocr"].get("status") in {"blocked", "failed"}:
        warnings.append(f"OCR benchmark did not run live: {report['ocr'].get('reason') or report['ocr'].get('error')}")
    if report["llm"].get("status") in {"blocked", "failed"}:
        warnings.append(f"LLM benchmark did not run live: {report['llm'].get('reason') or report['llm'].get('error')}")
    if require_gpu and report["llm"].get("provider") not in {None, "", "mock"} and report["llm"].get("health", {}).get("gpu_required") is False:
        failures.append("LLM provider did not report GPU-required mode.")
    if not report["offline"]["model_files_ready"]:
        warnings.append("Local ONNX Phi model files are not ready.")
    return {"passed": not failures, "failures": failures, "warnings": warnings}


def markdown_report(report: dict[str, Any]) -> str:
    gpu = report["gpu_after"]
    primary_gpu = gpu.get("primary_gpu") or {}
    lines = [
        "# Watcher POC Benchmark",
        "",
        f"- Started: `{report['started_at']}`",
        f"- Completed: `{report['completed_at']}`",
        f"- Acceptance passed: `{report['acceptance']['passed']}`",
        f"- GPU: `{primary_gpu.get('name', 'not detected')}`",
        f"- GPU provider ready: `{gpu.get('provider_ready')}`",
        f"- OCR: `{report['ocr'].get('status', 'unknown')}` via `{report['ocr'].get('provider', '')}`",
        f"- LLM: `{report['llm'].get('status', 'unknown')}` via `{report['llm'].get('provider', '')}`",
        f"- Privacy regression: `{report['privacy_regression']['passed']}`",
        f"- Raw temp files remaining: `{len(report['tmp_cleanup']['raw_frame_temp_files_remaining'])}`",
        "",
        "## Failures",
        "",
    ]
    failures = report["acceptance"]["failures"] or ["None"]
    lines.extend(f"- {item}" for item in failures)
    lines.extend(["", "## Warnings", ""])
    warnings = report["acceptance"]["warnings"] or ["None"]
    lines.extend(f"- {item}" for item in warnings)
    lines.extend(["", "## Privacy Notes", ""])
    lines.extend(
        [
            "- Benchmark images are generated in memory and not written to disk.",
            "- Unredacted OCR text is not persisted in the benchmark report.",
            "- Reports store hashes, timings, provider metadata, and pass/fail status.",
        ]
    )
    return "\n".join(lines) + "\n"


def _synthetic_png() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1100, 260), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 48), SAFE_OCR_TEXT, fill="black")
    draw.text((32, 110), "No secrets are present in this synthetic benchmark frame.", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return base64.b64decode(data_url.split(",", 1)[1])


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None, "mean": None}
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.fmean(values), 3),
    }


def _safe_list_models(provider: Any) -> list[dict[str, Any]]:
    try:
        return provider.list_models()
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def _tmp_files() -> list[Path]:
    if not settings.tmp_dir.exists():
        return []
    return [path for path in settings.tmp_dir.rglob("*") if path.is_file()]


def _cleanup_tmp() -> list[Path]:
    from backend.app.capture.ephemeral import ephemeral_frame_processor

    return ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)


if __name__ == "__main__":
    raise SystemExit(main())
