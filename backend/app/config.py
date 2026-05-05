from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings for the localhost-only backend."""

    def __init__(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        app_data = Path(os.getenv("LOCAL_SCRIBE_APP_DATA", repo_root / "app-data"))
        self.app_name = "Local Scribe"
        self.host = os.getenv("LOCAL_SCRIBE_HOST", "127.0.0.1")
        self.port = int(os.getenv("LOCAL_SCRIBE_PORT", "8765"))
        self.model_provider = os.getenv("LOCAL_SCRIBE_PROVIDER", "mock").lower()
        self.ollama_url = os.getenv("LOCAL_SCRIBE_OLLAMA_URL", "http://127.0.0.1:11434")
        self.lmstudio_url = os.getenv("LOCAL_SCRIBE_LMSTUDIO_URL", "http://127.0.0.1:1234")
        self.require_gpu = _env_bool("LOCAL_SCRIBE_REQUIRE_GPU", False)
        self.ocr_provider = os.getenv("LOCAL_SCRIBE_OCR_PROVIDER", "mock").lower()
        self.ocr_profile = os.getenv("LOCAL_SCRIBE_OCR_PROFILE", "screen-fast").lower()
        self.ocr_require_gpu = _env_bool("LOCAL_SCRIBE_OCR_REQUIRE_GPU", self.require_gpu)
        self.ocr_allow_temp_files = _env_bool("LOCAL_SCRIBE_OCR_ALLOW_TEMP_FILES", False)
        self.models_dir = Path(os.getenv("LOCAL_SCRIBE_MODELS_DIR", repo_root / "models"))
        self.ocr_models_dir = Path(os.getenv("LOCAL_SCRIBE_OCR_MODELS_DIR", self.models_dir / "ocr"))
        self.paddlex_cache_dir = Path(os.getenv("PADDLE_PDX_CACHE_HOME", self.ocr_models_dir / "paddlex"))
        self.onnx_phi_model_dir = Path(
            os.getenv(
                "LOCAL_SCRIBE_ONNX_PHI_MODEL_DIR",
                self.models_dir / "llm" / "microsoft--Phi-4-mini-reasoning-onnx" / "gpu" / "gpu-int4-rtn-block-32",
            )
        )
        self.local_llm_max_new_tokens = int(os.getenv("LOCAL_SCRIBE_LLM_MAX_NEW_TOKENS", "1024"))
        self.app_data_dir = app_data
        self.db_dir = app_data / "db"
        self.exports_dir = app_data / "exports"
        self.logs_dir = app_data / "logs"
        self.tmp_dir = app_data / "tmp"
        self.database_path = self.db_dir / "local_scribe.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.backend_containerized = os.getenv("LOCAL_SCRIBE_CONTAINERIZED", "false").lower() == "true"

    def ensure_directories(self) -> None:
        for directory in (
            self.app_data_dir,
            self.db_dir,
            self.exports_dir,
            self.logs_dir,
            self.tmp_dir,
            self.models_dir,
            self.ocr_models_dir,
            self.paddlex_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
