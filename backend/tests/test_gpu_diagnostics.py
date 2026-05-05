from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.runtime import gpu


client = TestClient(app)


def test_gpu_diagnostics_reports_missing_required_gpu(monkeypatch) -> None:
    monkeypatch.setattr(gpu.shutil, "which", lambda _name: None)

    diagnostics = gpu.collect_gpu_diagnostics(require_gpu=True)

    assert diagnostics["gpu_required"] is True
    assert diagnostics["hardware_ready"] is False
    assert diagnostics["gpu_ready"] is False
    assert diagnostics["errors"]
    assert "NVIDIA" in diagnostics["errors"][0]


def test_gpu_diagnostics_parses_nvidia_smi(monkeypatch) -> None:
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "nvidia-smi.exe" if name == "nvidia-smi" else None)

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout="NVIDIA GeForce RTX 3060, 12288, 10000, 555.85, 8.6\n")

    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    monkeypatch.setattr(gpu, "_probe_python_gpu_packages", lambda: {"onnxruntime_cuda_provider_available": False, "paddle_gpu_available": False})

    diagnostics = gpu.collect_gpu_diagnostics()

    assert diagnostics["hardware_ready"] is True
    assert diagnostics["primary_gpu"]["name"] == "NVIDIA GeForce RTX 3060"
    assert diagnostics["primary_gpu"]["memory_total_mb"] == 12288
    assert diagnostics["primary_gpu"]["memory_free_mb"] == 10000
    assert diagnostics["primary_gpu"]["compute_capability"] == "8.6"


def test_gpu_diagnostics_endpoint_shape() -> None:
    response = client.get("/api/diagnostics/gpu")

    assert response.status_code == 200
    data = response.json()
    assert "gpu_ready" in data
    assert "provider_ready" in data
    assert "packages" in data
