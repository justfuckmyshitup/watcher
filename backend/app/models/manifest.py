from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.config import settings


@dataclass(frozen=True)
class LocalModelEntry:
    key: str
    repo_id: str
    local_path: Path
    selected_path: Path
    revision: str
    license: str
    provider: str
    include: list[str]
    downloaded_at: str | None = None

    @property
    def exists(self) -> bool:
        return self.selected_path.exists()


DEFAULT_POC_MODEL = LocalModelEntry(
    key="phi4-mini-reasoning-onnx",
    repo_id="microsoft/Phi-4-mini-reasoning-onnx",
    local_path=settings.models_dir / "llm" / "microsoft--Phi-4-mini-reasoning-onnx",
    selected_path=settings.models_dir / "llm" / "microsoft--Phi-4-mini-reasoning-onnx" / "gpu" / "gpu-int4-rtn-block-32",
    revision="main",
    license="MIT",
    provider="onnxruntime-genai-cuda",
    include=["gpu/*"],
)


def manifest_path() -> Path:
    return settings.models_dir / "manifest.json"


def read_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.exists():
        return {"version": 1, "models": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "models": {}}


def get_manifest_entry(key: str) -> dict[str, Any] | None:
    manifest = read_manifest()
    models = manifest.get("models", {})
    if not isinstance(models, dict):
        return None
    entry = models.get(key)
    return entry if isinstance(entry, dict) else None


def get_default_model_entry() -> LocalModelEntry:
    entry = get_manifest_entry(DEFAULT_POC_MODEL.key)
    if not entry:
        return DEFAULT_POC_MODEL
    local_path = Path(entry.get("local_path") or DEFAULT_POC_MODEL.local_path)
    selected_path = Path(entry.get("selected_path") or DEFAULT_POC_MODEL.selected_path)
    return LocalModelEntry(
        key=str(entry.get("key") or DEFAULT_POC_MODEL.key),
        repo_id=str(entry.get("repo_id") or DEFAULT_POC_MODEL.repo_id),
        local_path=local_path,
        selected_path=selected_path,
        revision=str(entry.get("revision") or DEFAULT_POC_MODEL.revision),
        license=str(entry.get("license") or DEFAULT_POC_MODEL.license),
        provider=str(entry.get("provider") or DEFAULT_POC_MODEL.provider),
        include=[str(item) for item in entry.get("include", DEFAULT_POC_MODEL.include)],
        downloaded_at=entry.get("downloaded_at"),
    )
