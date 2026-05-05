from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session as DbSession

from backend.app.api.schemas import CaptureEventIn, ExclusionCreate, NoteCreate, RuntimeProviderRequest, SessionCreate
from backend.app.capture.ephemeral import ephemeral_frame_processor
from backend.app.config import settings
from backend.app.context_lattice.service import context_lattice_service, json_dumps
from backend.app.live_labeler.service import live_labeler_service
from backend.app.notes.generator import note_generator
from backend.app.ocr.providers import OcrProviderError, get_ocr_provider, maybe_extract_ocr_from_payload
from backend.app.privacy.decision_engine import PrivacyDecision, privacy_decision_engine
from backend.app.privacy.exclusions import matching_exclusion
from backend.app.redaction.service import stable_hash
from backend.app.runtime.diagnostics import collect_runtime_diagnostics
from backend.app.runtime.gpu import collect_gpu_diagnostics
from backend.app.storage.database import get_db
from backend.app.storage.models import (
    AppExclusion,
    Artifact,
    ContextEvent,
    Entity,
    ExportRecord,
    ModelRun,
    Note,
    Observation,
    RedactionFinding,
    RuntimeProfile,
    Session,
    TaskRollup,
    TopicRollup,
    UserActionLog,
    utcnow,
)


router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "localhost_only": settings.host in {"127.0.0.1", "localhost"},
        "raw_screenshot_persistence_default": False,
        "tmp_dir": str(settings.tmp_dir),
    }


@router.post("/cleanup")
def cleanup() -> dict[str, Any]:
    removed = ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
    return {"removed": [str(path) for path in removed], "tmp_dir": str(settings.tmp_dir)}


@router.get("/diagnostics")
def diagnostics(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    active_session = db.query(Session).filter(Session.status.in_(["active", "paused"])).order_by(desc(Session.started_at)).first()
    data = collect_runtime_diagnostics()
    data.update(
        {
            "active_session_id": active_session.id if active_session else None,
            "storage": {
                "database_path": str(settings.database_path),
                "raw_screenshots_persisted": False,
                "tmp_dir": str(settings.tmp_dir),
            },
        }
    )
    return data


@router.get("/diagnostics/gpu")
def gpu_diagnostics(require_gpu: bool | None = None) -> dict[str, Any]:
    return collect_gpu_diagnostics(require_gpu=settings.require_gpu if require_gpu is None else require_gpu)


@router.get("/diagnostics/ocr")
def ocr_diagnostics(provider: str | None = None, profile: str | None = None) -> dict[str, Any]:
    return get_ocr_provider(provider, profile=profile).diagnostics()


@router.post("/diagnostics/runtime")
def diagnostics_for_provider(request: RuntimeProviderRequest) -> dict[str, Any]:
    return collect_runtime_diagnostics(request.provider)


@router.post("/sessions")
def create_session(request: SessionCreate, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    model_provider = _model_provider_or_default(request.model_provider)
    ocr_provider = _normalize_provider(request.ocr_provider, "mock")
    ocr_profile = _normalize_ocr_profile(request.ocr_profile)
    privacy_strictness = _normalize_privacy_strictness(request.privacy_strictness)
    _supersede_open_sessions(db)
    session = Session(
        objective=request.objective,
        capture_interval_seconds=request.capture_interval_seconds,
        privacy_mode=request.privacy_mode,
        privacy_strictness=privacy_strictness,
        ocr_provider=ocr_provider,
        ocr_profile=ocr_profile,
        model_provider=model_provider,
        app_exclusion_patterns=json_dumps([pattern.strip() for pattern in request.app_exclusion_patterns if pattern.strip()]),
        evidence_mode=False if not request.evidence_mode else request.evidence_mode,
    )
    db.add(session)
    db.flush()
    _log(
        db,
        session.id,
        "session_started",
        {
            "privacy_mode": request.privacy_mode,
            "privacy_strictness": privacy_strictness,
            "ocr_provider": ocr_provider,
            "ocr_profile": ocr_profile,
            "model_provider": model_provider,
            "evidence_mode": session.evidence_mode,
            "session_exclusion_count": len(request.app_exclusion_patterns),
        },
    )
    db.commit()
    db.refresh(session)
    return _session_dict(session, event_count=0)


@router.get("/sessions")
def list_sessions(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    sessions = db.query(Session).order_by(desc(Session.started_at)).all()
    return [_session_dict(session, event_count=len(session.events)) for session in sessions]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    return _session_dict(session, event_count=len(session.events))


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    if session.status == "active":
        session.status = "paused"
        _log(db, session.id, "session_paused", {})
        db.commit()
    return _session_dict(session, event_count=len(session.events))


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    if session.status == "paused":
        session.status = "active"
        _log(db, session.id, "session_resumed", {})
        db.commit()
    return _session_dict(session, event_count=len(session.events))


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    if session.status != "stopped":
        session.status = "stopped"
        session.ended_at = utcnow()
    removed = ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
    _log(db, session.id, "session_stopped", {"tmp_files_removed": len(removed)})
    db.commit()
    return _session_dict(session, event_count=len(session.events))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    exports_removed = _remove_session_exports(session_id)
    db.delete(session)
    db.query(ExportRecord).filter(ExportRecord.session_id == session_id).delete(synchronize_session=False)
    db.query(ModelRun).filter(ModelRun.session_id == session_id).delete(synchronize_session=False)
    _log(db, session_id, "session_deleted", {"raw_artifacts_deleted": 0, "exports_removed": exports_removed})
    removed = ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
    db.commit()
    return {"deleted": True, "session_id": session_id, "tmp_files_removed": len(removed), "exports_removed": exports_removed}


@router.delete("/data")
def delete_all_local_data(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    counts = {
        "sessions": db.query(Session).count(),
        "events": db.query(ContextEvent).count(),
        "notes": db.query(Note).count(),
        "exports": db.query(ExportRecord).count(),
    }
    for model in (
        RedactionFinding,
        ContextEvent,
        Observation,
        TopicRollup,
        TaskRollup,
        Entity,
        Artifact,
        Note,
        ExportRecord,
        ModelRun,
        RuntimeProfile,
        AppExclusion,
        UserActionLog,
        Session,
    ):
        db.query(model).delete(synchronize_session=False)
    db.commit()
    exports_removed = _clear_directory(settings.exports_dir)
    tmp_removed = len(ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0))
    return {
        "deleted": True,
        "counts_before_delete": counts,
        "exports_removed": exports_removed,
        "tmp_files_removed": tmp_removed,
        "raw_artifacts_deleted": 0,
    }


@router.post("/sessions/{session_id}/events")
def ingest_event(session_id: str, request: CaptureEventIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    if session.status != "active":
        return {"skipped": True, "reason": f"session_{session.status}"}

    exclusion = matching_exclusion(db, request.active_app, request.active_window_title)
    if exclusion:
        ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
        _log(db, session_id, "capture_skipped_exclusion", {"rule_id": exclusion.id})
        db.commit()
        return {"skipped": True, "reason": "exclusion_rule", "rule_id": exclusion.id}

    session_exclusion = _session_exclusion_match(session, request.active_app, request.active_window_title)
    if session_exclusion:
        ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
        _log(db, session_id, "capture_skipped_session_exclusion", {"pattern_hash": hashlib.sha256(session_exclusion.encode("utf-8")).hexdigest()})
        db.commit()
        return {"skipped": True, "reason": "session_exclusion_rule"}

    payload = request.model_dump()
    early_screenshot_sha256 = _screenshot_hash_from_payload(payload)
    if early_screenshot_sha256:
        duplicate = _duplicate_event(db, session_id, {"screenshot_sha256": early_screenshot_sha256, "ocr_text_hash": None})
        if duplicate:
            ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
            return {"skipped": True, "reason": "duplicate_frame", "event_id": duplicate.id}

    ocr_provider = _normalize_provider(request.ocr_provider or session.ocr_provider, session.ocr_provider or "mock")
    ocr_profile = _normalize_ocr_profile(request.ocr_profile or session.ocr_profile)
    try:
        ocr_result = maybe_extract_ocr_from_payload(payload, provider_name=ocr_provider, profile=ocr_profile)
    except OcrProviderError as exc:
        ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if ocr_result and ocr_result.text:
        payload["ocr_text"] = ocr_result.text

    processed = ephemeral_frame_processor.process(payload)
    processed["ocr"] = ocr_result.to_dict() if ocr_result else None
    privacy_decision = privacy_decision_engine.evaluate(
        active_app=request.active_app,
        window_title=request.active_window_title,
        redacted_text=processed["redacted_text_snippet"],
        redaction_findings=processed["redaction_findings"],
        sensitivity_score=processed["sensitivity_score"],
        privacy_mode=session.privacy_mode,
        privacy_strictness=session.privacy_strictness,
    )
    processed["privacy_decision"] = privacy_decision
    processed["sensitivity_score"] = privacy_decision.sensitivity_score
    if privacy_decision.action == "drop_event":
        ephemeral_frame_processor.cleanup_abandoned_temp_files(max_age_seconds=0)
        _log(
            db,
            session_id,
            "capture_dropped_privacy",
            {
                "privacy_decision": _privacy_decision_log_dict(privacy_decision),
                "screenshot_hash_present": bool(processed.get("screenshot_sha256")),
                "ocr_hash_present": bool(processed.get("ocr_text_hash")),
                "ocr": _ocr_log_payload(processed.get("ocr")),
            },
        )
        db.commit()
        return {"skipped": True, "reason": "privacy_drop_event", "privacy_decision": _privacy_decision_log_dict(privacy_decision)}

    duplicate = _duplicate_event(db, session_id, processed)
    if duplicate:
        return {"skipped": True, "reason": "duplicate_frame", "event_id": duplicate.id}

    redacted_text_for_storage = processed["redacted_text_snippet"] if privacy_decision.action == "store_redacted" else ""
    summary_for_storage = processed["summary_snippet"] if privacy_decision.action == "store_redacted" else "Sensitive context stored as metadata only."
    label = live_labeler_service.label(
        text=redacted_text_for_storage,
        active_app=request.active_app,
        window_title=request.active_window_title,
        objective=session.objective or "",
    )
    topic, task, confidence = label.topic, label.task, label.confidence
    related = context_lattice_service.related_event_ids(db, session_id, topic, task)
    findings = privacy_decision.redaction_findings
    event = ContextEvent(
        session_id=session_id,
        active_app=request.active_app,
        active_window_title=request.active_window_title,
        capture_source=request.capture_source,
        screenshot_sha256=processed["screenshot_sha256"],
        perceptual_hash=processed["perceptual_hash"],
        ocr_text_hash=processed["ocr_text_hash"],
        redacted_text_snippet=redacted_text_for_storage,
        event_type=privacy_decision.action if privacy_decision.action != "store_redacted" else request.event_type,
        detected_topic=topic,
        detected_task=task,
        sensitivity_score=processed["sensitivity_score"],
        redaction_summary=json_dumps(_redaction_summary_payload(findings, privacy_decision, processed.get("ocr"))),
        summary_snippet=summary_for_storage,
        related_previous_events=json_dumps(related),
        confidence_score=confidence,
        user_selected_mode=request.user_selected_mode,
        raw_artifact_persisted=False,
    )
    db.add(event)
    db.flush()
    for finding in findings:
        db.add(
            RedactionFinding(
                event_id=event.id,
                kind=finding.kind,
                value_hash=finding.value_hash,
                replacement=finding.replacement,
                confidence=finding.confidence,
            )
        )
    _log(
        db,
        session_id,
        "context_event_created",
        {
            "event_id": event.id,
            "raw_artifact_persisted": False,
            "privacy_action": privacy_decision.action,
            "ocr": _ocr_log_payload(processed.get("ocr")),
        },
    )
    db.commit()
    db.refresh(event)
    return {"skipped": False, "event": _event_dict(event)}


@router.get("/sessions/{session_id}/events")
def list_events(session_id: str, db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    _session_or_404(db, session_id)
    events = db.query(ContextEvent).filter(ContextEvent.session_id == session_id).order_by(ContextEvent.timestamp.asc()).all()
    return [_event_dict(event) for event in events]


@router.post("/sessions/{session_id}/summarize")
def summarize_session(session_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    return context_lattice_service.upsert_rollups(db, session)


@router.post("/sessions/{session_id}/notes")
def create_note(session_id: str, request: NoteCreate, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    session = _session_or_404(db, session_id)
    title, markdown, provider = note_generator.generate_markdown(db, session, request.mode)
    note = Note(session_id=session.id, mode=request.mode, title=title, markdown=markdown, provider=provider)
    db.add(note)
    _log(db, session.id, "note_generated", {"mode": request.mode, "provider": provider})
    db.commit()
    db.refresh(note)
    return _note_dict(note)


@router.get("/sessions/{session_id}/notes")
def list_notes(session_id: str, db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    _session_or_404(db, session_id)
    notes = db.query(Note).filter(Note.session_id == session_id).order_by(desc(Note.created_at)).all()
    return [_note_dict(note) for note in notes]


@router.post("/notes/{note_id}/export")
def export_note(note_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    export_dir = settings.exports_dir / note.session_id
    export_dir.mkdir(parents=True, exist_ok=True)
    path = _safe_export_path(export_dir, f"{note.mode}-{note.id}.md")
    content = note.markdown.encode("utf-8")
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    record = ExportRecord(session_id=note.session_id, note_id=note.id, format="markdown", path=str(path), sha256=digest)
    db.add(record)
    _log(db, note.session_id, "note_exported", {"note_id": note.id, "path": str(path)})
    db.commit()
    return {"exported": True, "path": str(path), "sha256": digest}


@router.get("/privacy/exclusions")
def list_exclusions(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    rules = db.query(AppExclusion).order_by(desc(AppExclusion.created_at)).all()
    return [_exclusion_dict(rule) for rule in rules]


@router.post("/privacy/exclusions")
def create_exclusion(request: ExclusionCreate, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    if request.pattern_type not in {"app", "window", "both"}:
        raise HTTPException(status_code=400, detail="pattern_type must be app, window, or both")
    rule = AppExclusion(**request.model_dump())
    db.add(rule)
    _log(db, None, "exclusion_created", {"pattern_type": request.pattern_type})
    db.commit()
    db.refresh(rule)
    return _exclusion_dict(rule)


@router.delete("/privacy/exclusions/{rule_id}")
def delete_exclusion(rule_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    rule = db.get(AppExclusion, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    db.delete(rule)
    _log(db, None, "exclusion_deleted", {"rule_id": rule_id})
    db.commit()
    return {"deleted": True, "rule_id": rule_id}


def _session_or_404(db: DbSession, session_id: str) -> Session:
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _supersede_open_sessions(db: DbSession) -> None:
    open_sessions = db.query(Session).filter(Session.status.in_(["active", "paused"])).all()
    now = utcnow()
    for session in open_sessions:
        session.status = "stopped"
        session.ended_at = session.ended_at or now
        _log(db, session.id, "session_superseded", {"reason": "new_session_started"})


def _duplicate_event(db: DbSession, session_id: str, processed: dict[str, Any]) -> ContextEvent | None:
    query = db.query(ContextEvent).filter(ContextEvent.session_id == session_id)
    if processed.get("screenshot_sha256"):
        match = query.filter(ContextEvent.screenshot_sha256 == processed["screenshot_sha256"]).order_by(desc(ContextEvent.timestamp)).first()
        if match:
            return match
    if processed.get("ocr_text_hash"):
        match = query.filter(ContextEvent.ocr_text_hash == processed["ocr_text_hash"]).order_by(desc(ContextEvent.timestamp)).first()
        if match:
            return match
    return None


def _screenshot_hash_from_payload(payload: dict[str, Any]) -> str | None:
    screenshot_bytes = ephemeral_frame_processor._decode_data_url(payload.get("screenshot_base64") or "")
    try:
        return stable_hash(screenshot_bytes) if screenshot_bytes else None
    finally:
        del screenshot_bytes


def _session_dict(session: Session, event_count: int) -> dict[str, Any]:
    return {
        "id": session.id,
        "objective": session.objective,
        "status": session.status,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "capture_interval_seconds": session.capture_interval_seconds,
        "privacy_mode": session.privacy_mode,
        "privacy_strictness": session.privacy_strictness or "standard",
        "ocr_provider": session.ocr_provider or "mock",
        "ocr_profile": session.ocr_profile or "screen-fast",
        "model_provider": session.model_provider or "mock",
        "app_exclusion_patterns": _session_exclusion_patterns(session),
        "evidence_mode": session.evidence_mode,
        "event_count": event_count,
    }


def _event_dict(event: ContextEvent) -> dict[str, Any]:
    redaction_summary, privacy_decision, ocr = _event_redaction_privacy_and_ocr(event)
    return {
        "id": event.id,
        "session_id": event.session_id,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "active_app": event.active_app,
        "active_window_title": event.active_window_title,
        "capture_source": event.capture_source,
        "screenshot_sha256": event.screenshot_sha256,
        "perceptual_hash": event.perceptual_hash,
        "ocr_text_hash": event.ocr_text_hash,
        "redacted_text_snippet": event.redacted_text_snippet,
        "event_type": event.event_type,
        "privacy_action": privacy_decision.get("action", "store_redacted"),
        "privacy_decision": privacy_decision,
        "redaction_count": len(redaction_summary),
        "ocr": ocr,
        "ocr_provider": ocr.get("provider") if ocr else "",
        "ocr_profile": ocr.get("profile") if ocr else "",
        "ocr_confidence": ocr.get("average_confidence") if ocr else None,
        "ocr_elapsed_ms": ocr.get("elapsed_ms") if ocr else None,
        "detected_topic": event.detected_topic,
        "detected_task": event.detected_task,
        "sensitivity_score": event.sensitivity_score,
        "redaction_summary": redaction_summary,
        "summary_snippet": event.summary_snippet,
        "related_previous_events": json.loads(event.related_previous_events or "[]"),
        "confidence_score": event.confidence_score,
        "user_selected_mode": event.user_selected_mode,
        "raw_artifact_persisted": event.raw_artifact_persisted,
    }


def _event_redaction_privacy_and_ocr(event: ContextEvent) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    try:
        data = json.loads(event.redaction_summary or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        findings = data.get("findings", [])
        decision = data.get("privacy_decision", {})
        ocr = data.get("ocr")
        return (
            findings if isinstance(findings, list) else [],
            decision if isinstance(decision, dict) else {},
            ocr if isinstance(ocr, dict) else None,
        )
    if isinstance(data, list):
        return data, {}, None
    return [], {}, None


def _redaction_summary_payload(findings: list[Any], privacy_decision: PrivacyDecision, ocr: Any) -> dict[str, Any]:
    return {
        "findings": [finding.__dict__ for finding in findings],
        "privacy_decision": _privacy_decision_log_dict(privacy_decision),
        "ocr": _ocr_log_payload(ocr),
    }


def _privacy_decision_log_dict(decision: PrivacyDecision) -> dict[str, Any]:
    return {
        "action": decision.action,
        "sensitivity_score": decision.sensitivity_score,
        "reasons": decision.reasons,
        "retention_policy": decision.retention_policy,
    }


def _ocr_log_payload(ocr: Any) -> dict[str, Any] | None:
    if not isinstance(ocr, dict):
        return None
    confidences = [
        float(line.get("confidence"))
        for line in (ocr.get("lines") or [])
        if isinstance(line, dict) and line.get("confidence") is not None
    ]
    return {
        "provider": ocr.get("provider"),
        "profile": ocr.get("profile"),
        "device": ocr.get("device"),
        "elapsed_ms": ocr.get("elapsed_ms"),
        "line_count": len(ocr.get("lines") or []),
        "average_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "used_temp_files": bool(ocr.get("used_temp_files")),
    }


def _note_dict(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "session_id": note.session_id,
        "mode": note.mode,
        "title": note.title,
        "markdown": note.markdown,
        "provider": note.provider,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


def _exclusion_dict(rule: AppExclusion) -> dict[str, Any]:
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "pattern_type": rule.pattern_type,
        "is_regex": rule.is_regex,
        "enabled": rule.enabled,
        "reason": rule.reason,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def _log(db: DbSession, session_id: str | None, action: str, details: dict[str, Any]) -> None:
    db.add(UserActionLog(session_id=session_id, action=action, details=json.dumps(details, ensure_ascii=True)))


def _model_provider_or_default(value: str) -> str:
    return _normalize_provider(value, settings.model_provider or "mock")


def _normalize_provider(value: str | None, fallback: str) -> str:
    normalized = (value or fallback or "mock").strip().lower()
    allowed = {"mock", "ollama", "lmstudio", "lm-studio", "onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx", "paddle", "paddleocr"}
    return normalized if normalized in allowed else fallback


def _normalize_ocr_profile(value: str | None) -> str:
    normalized = (value or "screen-fast").strip().lower()
    return normalized if normalized in {"screen-fast", "screen-accurate"} else "screen-fast"


def _normalize_privacy_strictness(value: str | None) -> str:
    normalized = (value or "standard").strip().lower()
    return normalized if normalized in {"standard", "strict", "maximum"} else "standard"


def _session_exclusion_patterns(session: Session) -> list[str]:
    try:
        data = json.loads(session.app_exclusion_patterns or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _session_exclusion_match(session: Session, active_app: str, window_title: str) -> str | None:
    combined = f"{active_app} {window_title}".lower()
    for pattern in _session_exclusion_patterns(session):
        if pattern.lower() in combined:
            return pattern
    return None


def _safe_export_path(base_dir: Path, filename: str) -> Path:
    path = (base_dir / filename).resolve()
    if base_dir.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid export path")
    return path


def _remove_session_exports(session_id: str) -> int:
    export_dir = (settings.exports_dir / session_id).resolve()
    exports_root = settings.exports_dir.resolve()
    if exports_root not in export_dir.parents or not export_dir.exists():
        return 0
    count = sum(1 for path in export_dir.rglob("*") if path.is_file())
    shutil.rmtree(export_dir)
    return count


def _clear_directory(directory: Path) -> int:
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in list(root.iterdir()):
        if path.name == ".gitkeep":
            continue
        if path.is_dir():
            removed += sum(1 for child in path.rglob("*") if child.is_file())
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
            removed += 1
    return removed
