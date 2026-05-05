from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from backend.app.runtime import providers
from backend.app.runtime.providers import OnnxPhiReasoningProvider, _clean_model_output, get_provider


def test_get_provider_returns_onnx_phi_without_fallback(monkeypatch) -> None:
    monkeypatch.setattr(providers.settings, "model_provider", "onnx-phi")

    provider = get_provider()

    assert isinstance(provider, OnnxPhiReasoningProvider)


def test_onnx_phi_health_reports_missing_model_and_runtime(monkeypatch) -> None:
    model_root = Path.cwd() / "app-data" / "tmp" / f"pytest-model-{uuid4()}"
    monkeypatch.setattr(providers.settings, "onnx_phi_model_dir", model_root / "missing-model")
    monkeypatch.setattr(providers.settings, "require_gpu", False)
    monkeypatch.setattr(providers, "_module_exists", lambda name: False if name == "onnxruntime_genai" else True)

    health = OnnxPhiReasoningProvider().health_check()

    assert health["ok"] is False
    assert "model_missing" in health["reasons"]
    assert "onnxruntime_genai_missing" in health["reasons"]


def test_onnx_phi_health_accepts_config_shape_without_runtime(monkeypatch) -> None:
    model_root = Path.cwd() / "app-data" / "tmp" / f"pytest-model-{uuid4()}"
    model_dir = model_root / "model"
    model_dir.mkdir(parents=True)
    try:
        (model_dir / "genai_config.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(providers.settings, "onnx_phi_model_dir", model_dir)
        monkeypatch.setattr(providers.settings, "require_gpu", False)
        monkeypatch.setattr(providers, "_module_exists", lambda name: False if name == "onnxruntime_genai" else True)

        health = OnnxPhiReasoningProvider().health_check()

        assert health["model_exists"] is True
        assert health["ok"] is False
        assert "model_missing" not in health["reasons"]
    finally:
        shutil.rmtree(model_root, ignore_errors=True)


def test_clean_model_output_strips_prompt_and_think_block() -> None:
    prompt = "<|im_start|>user<|im_sep|>\nPrompt<|im_end|>\n"
    output = prompt + "<think>hidden scratch</think>\n# Note\nFinal only<|im_end|>"

    cleaned = _clean_model_output(output, prompt)

    assert "hidden scratch" not in cleaned
    assert cleaned == "# Note\nFinal only"
