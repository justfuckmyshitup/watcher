from __future__ import annotations

import importlib.util
from pathlib import Path


def _benchmark_module():
    path = Path.cwd() / "scripts" / "benchmark_poc.py"
    spec = importlib.util.spec_from_file_location("benchmark_poc", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_privacy_regression_corpus_passes() -> None:
    benchmark = _benchmark_module()

    result = benchmark.privacy_regression()

    assert result["passed"] is True
    assert result["failures"] == []


def test_markdown_report_does_not_include_raw_synthetic_secret() -> None:
    benchmark = _benchmark_module()
    report = {
        "started_at": "2026-05-03T00:00:00Z",
        "completed_at": "2026-05-03T00:00:01Z",
        "acceptance": {"passed": False, "failures": ["blocked"], "warnings": []},
        "gpu_after": {"provider_ready": False, "primary_gpu": {"name": "NVIDIA GeForce RTX 3060"}},
        "ocr": {"status": "blocked", "provider": "paddle"},
        "llm": {"status": "blocked", "provider": "onnx-phi"},
        "privacy_regression": {"passed": True},
        "tmp_cleanup": {"raw_frame_temp_files_remaining": []},
    }

    markdown = benchmark.markdown_report(report)

    assert "SyntheticSecret123" not in markdown
    assert "abcdefghijklmnopqrstuvwxyz123456" not in markdown
    assert "raw frames ephemeral" not in markdown.lower()
    assert "Benchmark images are generated in memory" in markdown


def test_cuda_dll_path_helper_is_report_shaped() -> None:
    from backend.app.runtime.cuda_paths import ensure_local_cuda_dll_paths

    result = ensure_local_cuda_dll_paths(preload_genai_cuda=False)

    assert result["ok"] in {True, False}
    assert isinstance(result["added_paths"], list)
    assert isinstance(result["errors"], list)
