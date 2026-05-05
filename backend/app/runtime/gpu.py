from __future__ import annotations

import importlib.util
import platform
import re
import shutil
import subprocess
import time
from typing import Any

from backend.app.runtime.cuda_paths import ensure_local_cuda_dll_paths


def collect_gpu_diagnostics(
    *,
    require_gpu: bool = False,
    require_cuda_provider: bool = False,
    require_paddle_gpu: bool = False,
    probe_packages: bool = True,
) -> dict[str, Any]:
    """Collect GPU readiness without starting capture or model inference."""

    warnings: list[str] = []
    errors: list[str] = []
    actions: list[str] = []
    gpus = _query_nvidia_gpus()
    hardware_ready = len(gpus) > 0

    packages = _probe_python_gpu_packages() if probe_packages else _package_probe_skipped()
    cuda_provider_ready = bool(packages.get("onnxruntime_cuda_provider_available"))
    paddle_gpu_ready = bool(packages.get("paddle_gpu_available"))
    provider_ready = cuda_provider_ready or paddle_gpu_ready

    if not hardware_ready:
        message = "No NVIDIA GPU was detected with nvidia-smi."
        if require_gpu:
            errors.append(message)
        else:
            warnings.append(message)
        actions.append("Install or update the NVIDIA driver, then rerun scripts/check-gpu.ps1.")

    if require_cuda_provider and not cuda_provider_ready:
        errors.append("ONNX Runtime CUDA execution provider is not available.")
        actions.append("Install a CUDA-capable ONNX Runtime GenAI profile after confirming CUDA/cuDNN compatibility.")

    if require_paddle_gpu and not paddle_gpu_ready:
        errors.append("PaddlePaddle GPU support is not available.")
        actions.append("Install the PaddlePaddle GPU package that matches the local NVIDIA driver/CUDA profile.")

    if hardware_ready and not provider_ready and probe_packages:
        warnings.append("NVIDIA GPU detected, but no Python OCR/LLM GPU provider is ready yet.")

    selected_provider = _select_gpu_provider(cuda_provider_ready, paddle_gpu_ready, hardware_ready)

    return {
        "gpu_required": require_gpu,
        "cuda_provider_required": require_cuda_provider,
        "paddle_gpu_required": require_paddle_gpu,
        "gpu_ready": hardware_ready and not (require_gpu and errors),
        "hardware_ready": hardware_ready,
        "provider_ready": provider_ready,
        "gpu_provider": selected_provider,
        "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
        "platform": platform.platform(),
        "gpus": gpus,
        "primary_gpu": gpus[0] if gpus else None,
        "packages": packages,
        "warnings": warnings,
        "errors": errors,
        "recommended_actions": _unique(actions),
        "checked_at": time.time(),
    }


def _query_nvidia_gpus() -> list[dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []
    fields = ["name", "memory.total", "memory.free", "driver_version", "compute_cap"]
    rows = _run_nvidia_query(fields)
    if rows is None:
        fields = ["name", "memory.total", "memory.free", "driver_version"]
        rows = _run_nvidia_query(fields)
    if rows is None:
        return []
    return [_gpu_from_row(fields, row) for row in rows if row.strip()]


def _run_nvidia_query(fields: list[str]) -> list[str] | None:
    query = ",".join(fields)
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        return None
    return result.stdout.strip().splitlines()


def _gpu_from_row(fields: list[str], row: str) -> dict[str, Any]:
    parts = [part.strip() for part in row.split(",")]
    data: dict[str, Any] = {}
    for field, value in zip(fields, parts, strict=False):
        key = field.replace(".", "_")
        if key in {"memory_total", "memory_free"}:
            data[f"{key}_mb"] = _parse_mib(value)
        elif key == "compute_cap":
            data["compute_capability"] = value or None
        else:
            data[key] = value
    return data


def _parse_mib(value: str) -> int | None:
    match = re.search(r"\d+", value.replace(",", ""))
    return int(match.group(0)) if match else None


def _probe_python_gpu_packages() -> dict[str, Any]:
    data: dict[str, Any] = {
        "onnxruntime_installed": _module_exists("onnxruntime"),
        "onnxruntime_genai_installed": _module_exists("onnxruntime_genai"),
        "onnxruntime_providers": [],
        "onnxruntime_cuda_provider_available": False,
        "paddle_installed": _module_exists("paddle"),
        "paddle_cuda_compiled": False,
        "paddle_cuda_device_count": 0,
        "paddle_gpu_available": False,
    }

    if data["onnxruntime_installed"]:
        try:
            ensure_local_cuda_dll_paths(preload_genai_cuda=False)
            import onnxruntime as ort  # type: ignore[import-not-found]

            providers = list(ort.get_available_providers())
            data["onnxruntime_providers"] = providers
            data["onnxruntime_cuda_provider_available"] = "CUDAExecutionProvider" in providers
        except Exception as exc:  # noqa: BLE001
            data["onnxruntime_error"] = str(exc)

    if data["paddle_installed"]:
        try:
            ensure_local_cuda_dll_paths(preload_genai_cuda=False)
            import paddle  # type: ignore[import-not-found]

            cuda_compiled = bool(paddle.device.is_compiled_with_cuda())
            device_count = int(paddle.device.cuda.device_count()) if cuda_compiled else 0
            data["paddle_cuda_compiled"] = cuda_compiled
            data["paddle_cuda_device_count"] = device_count
            data["paddle_gpu_available"] = cuda_compiled and device_count > 0
        except Exception as exc:  # noqa: BLE001
            data["paddle_error"] = str(exc)

    return data


def _package_probe_skipped() -> dict[str, Any]:
    return {
        "probe_skipped": True,
        "onnxruntime_cuda_provider_available": False,
        "paddle_gpu_available": False,
    }


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _select_gpu_provider(cuda_provider_ready: bool, paddle_gpu_ready: bool, hardware_ready: bool) -> str:
    if cuda_provider_ready:
        return "onnxruntime-cuda"
    if paddle_gpu_ready:
        return "paddle-gpu"
    if hardware_ready:
        return "nvidia-detected"
    return "none"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
