from __future__ import annotations

from backend.app.runtime import diagnostics as runtime_diagnostics


class FakeLiveProvider:
    name = "onnx-phi-reasoning"
    runtime_location = "host"

    def runtime_diagnostics(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "health": {"ok": True},
            "models": [],
            "gpu_active": True,
            "gpu_status": "cuda_ready",
            "cpu_fallback": False,
            "runtime_location": self.runtime_location,
        }


class FakeOcrProvider:
    def diagnostics(self) -> dict[str, object]:
        return {"provider": "paddle", "available": True, "profile": "screen-fast"}


def test_runtime_diagnostics_preserves_proven_live_gpu_status(monkeypatch) -> None:
    monkeypatch.setattr(runtime_diagnostics, "get_provider", lambda _name=None: FakeLiveProvider())
    monkeypatch.setattr(runtime_diagnostics, "get_ocr_provider", lambda: FakeOcrProvider())
    monkeypatch.setattr(
        runtime_diagnostics,
        "collect_gpu_diagnostics",
        lambda **_kwargs: {"hardware_ready": True, "provider_ready": True},
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "_nvidia_smi",
        lambda: {"name": "NVIDIA GeForce RTX 3060", "memory_total": "12288 MiB", "driver_version": "591.86"},
    )
    monkeypatch.setattr(runtime_diagnostics.settings, "model_provider", "onnx-phi")
    monkeypatch.setattr(runtime_diagnostics.settings, "ocr_provider", "paddle")
    monkeypatch.setattr(runtime_diagnostics.settings, "ocr_profile", "screen-fast")

    result = runtime_diagnostics.collect_runtime_diagnostics()

    assert result["gpu_status"] == "cuda_ready"
    assert result["cpu_fallback"] is False
    assert result["configured_model_provider"] == "onnx-phi"
    assert result["configured_ocr_provider"] == "paddle"
    assert result["live_labeler"]["provider"] == "context_lattice"
    assert result["live_labeler"]["gpu_instances"] == 0
