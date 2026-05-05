from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    objective: str = ""
    capture_interval_seconds: float = Field(default=0.5, ge=0.5, le=60)
    privacy_mode: bool = True
    privacy_strictness: str = "standard"
    ocr_provider: str = "mock"
    ocr_profile: str = "screen-fast"
    model_provider: str = ""
    app_exclusion_patterns: list[str] = Field(default_factory=list)
    evidence_mode: bool = False


class CaptureEventIn(BaseModel):
    active_app: str = ""
    active_window_title: str = ""
    capture_source: str = "desktop"
    screenshot_base64: str | None = None
    ocr_text: str | None = None
    ocr_provider: str | None = None
    ocr_profile: str | None = None
    event_type: str = "frame"
    user_selected_mode: str = "standard"
    custom_redaction_terms: list[str] = Field(default_factory=list)


class NoteCreate(BaseModel):
    mode: str = "clean_summary"


class ExclusionCreate(BaseModel):
    pattern: str
    pattern_type: str = "window"
    is_regex: bool = False
    enabled: bool = True
    reason: str = ""

class RuntimeProviderRequest(BaseModel):
    provider: str | None = None
