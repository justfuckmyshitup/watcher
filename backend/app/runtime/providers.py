from __future__ import annotations

import json
import platform
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from abc import ABC, abstractmethod
import importlib.util
from typing import Any

from backend.app.config import settings
from backend.app.models.manifest import get_default_model_entry
from backend.app.runtime.cuda_paths import ensure_local_cuda_dll_paths
from backend.app.runtime.gpu import collect_gpu_diagnostics


class ModelProvider(ABC):
    name: str = "base"
    runtime_location: str = "host"

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, model: str | None = None) -> str:
        raise NotImplementedError

    def summarize(self, prompt: str, model: str | None = None) -> str:
        return self.generate(prompt, model=model)

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        return None

    def vision_analyze(self, image_bytes: bytes, prompt: str, model: str | None = None) -> str | None:
        return None

    def runtime_diagnostics(self) -> dict[str, Any]:
        health = self.health_check()
        return {
            "provider": self.name,
            "health": health,
            "models": self.list_models() if health.get("ok") else [],
            "gpu_active": False,
            "gpu_status": "unknown",
            "cpu_fallback": True,
            "runtime_location": self.runtime_location,
            "backend_containerized": settings.backend_containerized,
            "platform": platform.platform(),
            "last_checked_at": time.time(),
        }


class MockProvider(ModelProvider):
    name = "mock"

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "mode": "mock", "message": "Mock AI mode active. No real local model analysis has occurred."}

    def list_models(self) -> list[dict[str, Any]]:
        return [{"name": "mock-note-generator", "provider": self.name, "size": "0B"}]

    def generate(self, prompt: str, model: str | None = None) -> str:
        return (
            "Mock AI mode active. No real local model analysis has occurred.\n\n"
            "The generated content below is deterministic placeholder output based only on redacted, structured context."
        )

    def runtime_diagnostics(self) -> dict[str, Any]:
        diagnostics = super().runtime_diagnostics()
        diagnostics.update(
            {
                "active_model": "mock-note-generator",
                "gpu_status": "not_applicable",
                "cpu_fallback": False,
                "mock_mode": True,
            }
        )
        return diagnostics


class OllamaProvider(ModelProvider):
    name = "ollama"

    def health_check(self) -> dict[str, Any]:
        try:
            self._get_json(f"{settings.ollama_url}/api/tags", timeout=2.0)
            return {"ok": True, "mode": "live", "url": settings.ollama_url}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "mode": "live", "url": settings.ollama_url, "error": str(exc)}

    def list_models(self) -> list[dict[str, Any]]:
        data = self._get_json(f"{settings.ollama_url}/api/tags", timeout=4.0)
        return data.get("models", [])

    def generate(self, prompt: str, model: str | None = None) -> str:
        selected_model = model or self._default_model()
        payload = json.dumps({"model": selected_model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{settings.ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("response", "")

    def _default_model(self) -> str:
        models = self.list_models()
        if not models:
            raise RuntimeError("Ollama is reachable but no local models were found.")
        return models[0]["name"]

    @staticmethod
    def _get_json(url: str, timeout: float) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class LMStudioProvider(ModelProvider):
    name = "lmstudio"

    def health_check(self) -> dict[str, Any]:
        try:
            self._get_json(f"{settings.lmstudio_url}/v1/models", timeout=2.0)
            return {"ok": True, "mode": "live", "url": settings.lmstudio_url}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "mode": "live", "url": settings.lmstudio_url, "error": str(exc)}

    def list_models(self) -> list[dict[str, Any]]:
        data = self._get_json(f"{settings.lmstudio_url}/v1/models", timeout=4.0)
        return data.get("data", [])

    def generate(self, prompt: str, model: str | None = None) -> str:
        selected_model = model or self._default_model()
        payload = json.dumps(
            {
                "model": selected_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{settings.lmstudio_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _default_model(self) -> str:
        models = self.list_models()
        if not models:
            raise RuntimeError("LM Studio is reachable but no loaded models were found.")
        return models[0]["id"]

    @staticmethod
    def _get_json(url: str, timeout: float) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class OnnxPhiReasoningProvider(ModelProvider):
    name = "onnx-phi-reasoning"
    runtime_location = "host"

    def __init__(self) -> None:
        self.entry = get_default_model_entry()
        override = settings.onnx_phi_model_dir
        self.model_dir = override if override else self.entry.selected_path
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    def health_check(self) -> dict[str, Any]:
        reasons: list[str] = []
        model_exists = self._model_dir_ready()
        genai_installed = _module_exists("onnxruntime_genai")
        gpu = collect_gpu_diagnostics(require_gpu=settings.require_gpu, probe_packages=False)
        cuda_available = self._genai_cuda_available() if genai_installed else False

        if not model_exists:
            reasons.append("model_missing")
        if not genai_installed:
            reasons.append("onnxruntime_genai_missing")
        if settings.require_gpu and not gpu["hardware_ready"]:
            reasons.append("nvidia_gpu_missing")
        if settings.require_gpu and genai_installed and not cuda_available:
            reasons.append("onnxruntime_genai_cuda_not_available")

        return {
            "ok": not reasons,
            "mode": "local_onnx",
            "repo_id": self.entry.repo_id,
            "model_dir": str(self.model_dir),
            "model_exists": model_exists,
            "onnxruntime_genai_installed": genai_installed,
            "cuda_available": cuda_available,
            "gpu_required": settings.require_gpu,
            "reasons": reasons,
        }

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "name": self.entry.key,
                "repo_id": self.entry.repo_id,
                "provider": self.name,
                "path": str(self.model_dir),
                "license": self.entry.license,
                "revision": self.entry.revision,
            }
        ]

    def generate(self, prompt: str, model: str | None = None) -> str:
        health = self.health_check()
        if not health.get("ok"):
            raise RuntimeError("ONNX Phi provider is not ready: " + ", ".join(health.get("reasons", [])))

        og, np, loaded_model, tokenizer = self._load()
        formatted = _phi_chat_prompt(prompt)
        input_tokens = tokenizer.encode(formatted)
        params = og.GeneratorParams(loaded_model)
        max_length = int(len(input_tokens) + settings.local_llm_max_new_tokens)
        params.set_search_options(max_length=max_length, temperature=0.2, top_p=0.9)

        generator = og.Generator(loaded_model, params)
        generator.append_tokens(np.array(input_tokens, dtype=np.int32))
        while not generator.is_done():
            generator.generate_next_token()
        sequence = generator.get_sequence(0)
        decoded = tokenizer.decode(sequence)
        return _clean_model_output(decoded, formatted)

    def runtime_diagnostics(self) -> dict[str, Any]:
        diagnostics = super().runtime_diagnostics()
        health = diagnostics["health"]
        diagnostics.update(
            {
                "active_model": self.entry.key,
                "gpu_active": bool(health.get("ok")) and settings.require_gpu,
                "gpu_status": "cuda_ready" if health.get("cuda_available") else "cuda_unavailable",
                "cpu_fallback": not settings.require_gpu,
                "model_dir": str(self.model_dir),
            }
        )
        return diagnostics

    def _load(self) -> tuple[Any, Any, Any, Any]:
        if self._model is not None and self._tokenizer is not None:
            if settings.require_gpu:
                ensure_local_cuda_dll_paths(preload_genai_cuda=True)
            import numpy as np  # type: ignore[import-not-found]
            import onnxruntime_genai as og  # type: ignore[import-not-found]

            return og, np, self._model, self._tokenizer

        import numpy as np  # type: ignore[import-not-found]

        if settings.require_gpu:
            cuda_paths = ensure_local_cuda_dll_paths(preload_genai_cuda=True)
            if not cuda_paths["ok"]:
                raise RuntimeError("Unable to prepare local CUDA DLL paths: " + "; ".join(cuda_paths["errors"]))

        import onnxruntime_genai as og  # type: ignore[import-not-found]

        config = og.Config(str(self.model_dir))
        if settings.require_gpu:
            config.clear_providers()
            config.append_provider("cuda")
            config.set_provider_option("cuda", "device_id", "0")
        self._model = og.Model(config)
        self._tokenizer = og.Tokenizer(self._model)
        return og, np, self._model, self._tokenizer

    def _model_dir_ready(self) -> bool:
        path = Path(self.model_dir)
        return path.exists() and ((path / "genai_config.json").exists() or (path / "config.json").exists())

    @staticmethod
    def _genai_cuda_available() -> bool:
        try:
            ensure_local_cuda_dll_paths(preload_genai_cuda=True)
            import onnxruntime_genai as og  # type: ignore[import-not-found]

            checker = getattr(og, "is_cuda_available", None)
            return bool(checker()) if checker else False
        except Exception:  # noqa: BLE001
            return False


def get_provider(name: str | None = None) -> ModelProvider:
    provider_name = (name or settings.model_provider).lower()
    if provider_name in {"onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx"}:
        return OnnxPhiReasoningProvider()
    if provider_name == "ollama":
        provider = OllamaProvider()
        return provider if provider.health_check().get("ok") else MockProvider()
    if provider_name in {"lmstudio", "lm-studio"}:
        provider = LMStudioProvider()
        return provider if provider.health_check().get("ok") else MockProvider()
    return MockProvider()


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _phi_chat_prompt(prompt: str) -> str:
    system = (
        "You are Local Scribe, a private local note-taking assistant. "
        "Use only the supplied redacted context. Preserve redaction placeholders exactly. "
        "Do not reveal or invent hidden values. Return final Markdown only."
    )
    return (
        "<|im_start|>system<|im_sep|>\n"
        f"{system}<|im_end|>\n"
        "<|im_start|>user<|im_sep|>\n"
        f"{prompt}<|im_end|>\n"
        "<|im_start|>assistant<|im_sep|>\n"
    )


def _clean_model_output(output: str, prompt: str) -> str:
    text = output
    if text.startswith(prompt):
        text = text[len(prompt) :]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S)
    text = text.replace("<|im_end|>", "").strip()
    if "## " not in text and "#" not in text[:10]:
        text = text.strip()
    return text
