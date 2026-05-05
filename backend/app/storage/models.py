from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.app.storage.database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=new_id)
    objective = Column(Text, default="")
    status = Column(String, default="active", index=True)
    started_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    capture_interval_seconds = Column(Float, default=3.0)
    privacy_mode = Column(Boolean, default=True)
    privacy_strictness = Column(String, default="standard")
    ocr_provider = Column(String, default="mock")
    ocr_profile = Column(String, default="screen-fast")
    model_provider = Column(String, default="mock")
    app_exclusion_patterns = Column(Text, default="[]")
    evidence_mode = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    events = relationship("ContextEvent", cascade="all, delete-orphan", back_populates="session")
    notes = relationship("Note", cascade="all, delete-orphan", back_populates="session")
    topic_rollups = relationship("TopicRollup", cascade="all, delete-orphan", back_populates="session")
    task_rollups = relationship("TaskRollup", cascade="all, delete-orphan", back_populates="session")


class ContextEvent(Base):
    __tablename__ = "context_events"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)
    active_app = Column(String, default="")
    active_window_title = Column(String, default="")
    capture_source = Column(String, default="desktop")
    screenshot_sha256 = Column(String, nullable=True, index=True)
    perceptual_hash = Column(String, nullable=True)
    ocr_text_hash = Column(String, nullable=True, index=True)
    redacted_text_snippet = Column(Text, default="")
    event_type = Column(String, default="frame")
    detected_topic = Column(String, default="general")
    detected_task = Column(String, default="documentation")
    sensitivity_score = Column(Float, default=0.0)
    redaction_summary = Column(Text, default="[]")
    summary_snippet = Column(Text, default="")
    related_previous_events = Column(Text, default="[]")
    confidence_score = Column(Float, default=0.5)
    user_selected_mode = Column(String, default="standard")
    raw_artifact_persisted = Column(Boolean, default=False)

    session = relationship("Session", back_populates="events")
    findings = relationship("RedactionFinding", cascade="all, delete-orphan", back_populates="event")


class Observation(Base):
    __tablename__ = "observations"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    event_id = Column(String, ForeignKey("context_events.id"), nullable=True)
    text = Column(Text, default="")
    confidence_score = Column(Float, default=0.5)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TopicRollup(Base):
    __tablename__ = "topic_rollups"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    topic = Column(String, default="general", index=True)
    summary = Column(Text, default="")
    event_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("Session", back_populates="topic_rollups")


class TaskRollup(Base):
    __tablename__ = "task_rollups"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    task = Column(String, default="documentation", index=True)
    summary = Column(Text, default="")
    event_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("Session", back_populates="task_rollups")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    kind = Column(String, default="term")
    label = Column(String, default="")
    value_hash = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    kind = Column(String, default="markdown")
    path = Column(Text, default="")
    sha256 = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RedactionFinding(Base):
    __tablename__ = "redaction_findings"

    id = Column(String, primary_key=True, default=new_id)
    event_id = Column(String, ForeignKey("context_events.id"), index=True, nullable=False)
    kind = Column(String, default="unknown")
    value_hash = Column(String, default="")
    replacement = Column(String, default="[REDACTED]")
    confidence = Column(Float, default=0.7)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    event = relationship("ContextEvent", back_populates="findings")


class Note(Base):
    __tablename__ = "notes"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    mode = Column(String, default="clean_summary")
    title = Column(String, default="")
    markdown = Column(Text, default="")
    provider = Column(String, default="mock")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("Session", back_populates="notes")


class ExportRecord(Base):
    __tablename__ = "exports"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=False)
    note_id = Column(String, ForeignKey("notes.id"), nullable=False)
    format = Column(String, default="markdown")
    path = Column(Text, default="")
    sha256 = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), index=True, nullable=True)
    provider = Column(String, default="mock")
    model = Column(String, default="mock-note-generator")
    mode = Column(String, default="summarize")
    prompt_hash = Column(String, default="")
    output_hash = Column(String, default="")
    gpu_active = Column(Boolean, default=False)
    runtime_location = Column(String, default="host")
    status = Column(String, default="ok")
    error = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RuntimeProfile(Base):
    __tablename__ = "runtime_profiles"

    id = Column(String, primary_key=True, default=new_id)
    provider = Column(String, default="mock")
    model = Column(String, default="")
    gpu_status = Column(String, default="unknown")
    runtime_location = Column(String, default="host")
    diagnostics = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AppExclusion(Base):
    __tablename__ = "app_exclusions"

    id = Column(String, primary_key=True, default=new_id)
    pattern = Column(String, nullable=False)
    pattern_type = Column(String, default="window")
    is_regex = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class UserActionLog(Base):
    __tablename__ = "user_action_logs"

    id = Column(String, primary_key=True, default=new_id)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True, index=True)
    action = Column(String, default="")
    details = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow)
