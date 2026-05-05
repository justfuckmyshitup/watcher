from __future__ import annotations

import base64
import binascii
import importlib.util
import io
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.app.config import settings
from backend.app.runtime.gpu import collect_gpu_diagnostics


@dataclass(frozen=True)
class OcrTextLine:
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: list[OcrTextLine]
    provider: str
    profile: str
    device: str
    elapsed_ms: float
    used_temp_files: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lines"] = [asdict(line) for line in self.lines]
        return data


class OcrProviderError(RuntimeError):
    pass


class OcrProvider:
    name = "base"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": False,
            "profile": settings.ocr_profile,
            "require_gpu": settings.ocr_require_gpu,
            "allow_temp_files": settings.ocr_allow_temp_files,
        }

    def extract_text(self, image_bytes: bytes) -> OcrResult:
        raise OcrProviderError("OCR provider is not implemented.")


class MockOcrProvider(OcrProvider):
    name = "mock"

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update(
            {
                "available": True,
                "gpu_required": False,
                "gpu_active": False,
                "message": "Mock OCR mode active. No image OCR is performed.",
            }
        )
        return data

    def extract_text(self, image_bytes: bytes) -> OcrResult:
        start = time.perf_counter()
        return OcrResult(
            text="",
            lines=[],
            provider=self.name,
            profile=settings.ocr_profile,
            device="none",
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )


class PaddleOcrProvider(OcrProvider):
    name = "paddle"

    def __init__(
        self,
        *,
        profile: str | None = None,
        require_gpu: bool | None = None,
        allow_temp_files: bool | None = None,
    ) -> None:
        self.profile = profile or settings.ocr_profile
        self.require_gpu = settings.ocr_require_gpu if require_gpu is None else require_gpu
        self.allow_temp_files = settings.ocr_allow_temp_files if allow_temp_files is None else allow_temp_files
        self._pipeline: Any | None = None

    def diagnostics(self) -> dict[str, Any]:
        _ensure_paddle_cache_env()
        gpu = collect_gpu_diagnostics(require_gpu=self.require_gpu, require_paddle_gpu=self.require_gpu)
        paddleocr_installed = _module_exists("paddleocr")
        pillow_installed = _module_exists("PIL")
        numpy_installed = _module_exists("numpy")
        python_supported = _python_supported_for_paddle()
        available = (
            python_supported
            and paddleocr_installed
            and pillow_installed
            and numpy_installed
            and (not self.require_gpu or gpu["packages"].get("paddle_gpu_available"))
        )
        reasons: list[str] = []
        if not python_supported:
            reasons.append("python_version_not_supported_by_paddle")
        if not paddleocr_installed:
            reasons.append("paddleocr_not_installed")
        if not pillow_installed:
            reasons.append("pillow_not_installed")
        if not numpy_installed:
            reasons.append("numpy_not_installed")
        if self.require_gpu and not gpu["packages"].get("paddle_gpu_available"):
            reasons.append("paddle_gpu_not_available")

        return {
            "provider": self.name,
            "available": available,
            "profile": self.profile,
            "require_gpu": self.require_gpu,
            "allow_temp_files": self.allow_temp_files,
            "device": self._device(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_supported": python_supported,
            "paddleocr_installed": paddleocr_installed,
            "pillow_installed": pillow_installed,
            "numpy_installed": numpy_installed,
            "gpu": gpu,
            "reasons": reasons,
        }

    def extract_text(self, image_bytes: bytes) -> OcrResult:
        diagnostics = self.diagnostics()
        if not diagnostics["available"]:
            raise OcrProviderError("PaddleOCR is not ready: " + ", ".join(diagnostics["reasons"]))
        start = time.perf_counter()
        used_temp_files = False
        pipeline = self._get_pipeline()
        if self.allow_temp_files:
            raw_result = self._predict_with_temp_file(pipeline, image_bytes)
            used_temp_files = True
        else:
            raw_result = pipeline.predict(self._image_bytes_to_array(image_bytes))
        lines = _extract_lines(raw_result)
        text = "\n".join(line.text for line in lines if line.text).strip()
        return OcrResult(
            text=text,
            lines=lines,
            provider=self.name,
            profile=self.profile,
            device=self._device(),
            elapsed_ms=(time.perf_counter() - start) * 1000,
            used_temp_files=used_temp_files,
        )

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        _ensure_paddle_cache_env()
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        kwargs = {
            "ocr_version": "PP-OCRv5",
            "device": self._device(),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        kwargs.update(_profile_model_kwargs(self.profile))
        self._pipeline = PaddleOCR(**kwargs)
        return self._pipeline

    def _device(self) -> str:
        if self.require_gpu:
            return "gpu:0"
        return "gpu:0" if collect_gpu_diagnostics(probe_packages=False)["hardware_ready"] else "cpu"

    @staticmethod
    def _image_bytes_to_array(image_bytes: bytes) -> Any:
        from PIL import Image  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        with Image.open(io.BytesIO(image_bytes)) as image:
            return np.array(image.convert("RGB"))

    @staticmethod
    def _predict_with_temp_file(pipeline: Any, image_bytes: bytes) -> Any:
        temp_dir = settings.tmp_dir / f"ocr-cycle-{uuid4()}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / "frame.jpg"
        try:
            temp_path.write_bytes(image_bytes)
            return pipeline.predict(str(temp_path))
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


def get_ocr_provider(
    name: str | None = None,
    *,
    profile: str | None = None,
    require_gpu: bool | None = None,
    allow_temp_files: bool | None = None,
) -> OcrProvider:
    provider_name = (name or settings.ocr_provider).lower()
    if provider_name in {"paddle", "paddleocr"}:
        return PaddleOcrProvider(profile=profile, require_gpu=require_gpu, allow_temp_files=allow_temp_files)
    return MockOcrProvider()


def _ensure_paddle_cache_env() -> None:
    settings.ocr_models_dir.mkdir(parents=True, exist_ok=True)
    settings.paddlex_cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(settings.paddlex_cache_dir))


def maybe_extract_ocr_from_payload(
    payload: dict[str, Any],
    *,
    provider_name: str | None = None,
    profile: str | None = None,
) -> OcrResult | None:
    if (payload.get("ocr_text") or "").strip():
        return None
    provider = get_ocr_provider(provider_name, profile=profile)
    if provider.name == "mock":
        return None
    image_bytes = _decode_data_url(payload.get("screenshot_base64") or "")
    if not image_bytes:
        return None
    try:
        return provider.extract_text(image_bytes)
    finally:
        del image_bytes


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _python_supported_for_paddle() -> bool:
    return (sys.version_info.major, sys.version_info.minor) >= (3, 9) and (sys.version_info.major, sys.version_info.minor) <= (3, 13)


def _decode_data_url(value: str) -> bytes:
    if not value:
        return b""
    if "," in value and value.strip().lower().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        return b""


def _profile_model_kwargs(profile: str) -> dict[str, str]:
    if profile == "screen-accurate":
        return {
            "text_detection_model_name": "PP-OCRv5_server_det",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        }
    return {
        "text_detection_model_name": "PP-OCRv5_mobile_det",
        "text_recognition_model_name": "PP-OCRv5_mobile_rec",
    }


def _extract_lines(raw_result: Any) -> list[OcrTextLine]:
    lines: list[OcrTextLine] = []
    for item in raw_result or []:
        payload = _result_payload(item)
        texts = payload.get("rec_texts") if isinstance(payload, dict) else None
        scores = payload.get("rec_scores") if isinstance(payload, dict) else None
        if isinstance(texts, list):
            for index, text in enumerate(texts):
                score = None
                if isinstance(scores, list) and index < len(scores):
                    try:
                        score = float(scores[index])
                    except (TypeError, ValueError):
                        score = None
                lines.append(OcrTextLine(text=str(text), confidence=score))
    return lines


def _result_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = item
    elif hasattr(item, "json"):
        payload = item.json
    else:
        return {}
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
        return payload["res"]
    return payload if isinstance(payload, dict) else {}
