from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from backend.app.config import settings
from backend.app.live_labeler.service import live_labeler_service
from backend.app.ocr.providers import get_ocr_provider
from backend.app.runtime.gpu import collect_gpu_diagnostics
from backend.app.runtime.providers import get_provider


def collect_runtime_diagnostics(provider_name: str | None = None) -> dict[str, Any]:
    provider = get_provider(provider_name)
    diagnostics = provider.runtime_diagnostics()
    gpu = collect_gpu_diagnostics(require_gpu=settings.require_gpu, probe_packages=False)
    ocr = get_ocr_provider().diagnostics()
    diagnostics.update(
        {
            "configured_model_provider": settings.model_provider,
            "configured_ocr_provider": settings.ocr_provider,
            "configured_ocr_profile": settings.ocr_profile,
            "require_gpu": settings.require_gpu,
            "ocr_require_gpu": settings.ocr_require_gpu,
            "os": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
            "ollama_available": provider_name == "ollama" or shutil.which("ollama") is not None,
            "lmstudio_url": settings.lmstudio_url,
            "ollama_url": settings.ollama_url,
            "gpu": gpu,
            "ocr": ocr,
            "live_labeler": live_labeler_service.diagnostics(),
        }
    )
    nvidia = _nvidia_smi()
    if nvidia:
        diagnostics["nvidia"] = nvidia
        if diagnostics["provider"] != "mock" and diagnostics.get("gpu_status") in {None, "", "unknown"}:
            diagnostics["gpu_status"] = "available_unverified"
    return diagnostics


def _nvidia_smi() -> dict[str, str] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        first = result.stdout.strip().splitlines()[0]
        name, memory, driver = [part.strip() for part in first.split(",", 2)]
        return {"name": name, "memory_total": memory, "driver_version": driver}
    except Exception:  # noqa: BLE001
        return None
