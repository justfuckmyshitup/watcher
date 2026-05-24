from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter

from backend.app.context.focus_filter import clean_focus_text, contains_ocr_dump, looks_noisy, readable_terms
from sqlalchemy.orm import Session as DbSession

from backend.app.context_lattice.service import context_lattice_service
from backend.app.runtime.providers import get_provider
from backend.app.storage.models import ContextEvent, ModelRun, Session


MODE_TITLES = {
    "activity_log": "Activity Log",
    "clean_summary": "Clean Summary",
    "procedure": "Step-by-Step Procedure",
    "sop": "SOP / Runbook",
    "runbook": "Runbook",
    "ticket_update": "Ticket Update",
    "change_summary": "Change Management Summary",
    "decision_record": "Decision Record",
    "audit_evidence": "Audit Evidence Narrative",
    "security_notes": "Security Investigation Notes",
    "sales_notes": "Sales / Customer Interaction Notes",
    "training_notes": "Training Notes",
    "recap": "What Did I Just Do?",
}


class NoteGenerator:
    def generate_markdown(self, db: DbSession, session: Session, mode: str = "clean_summary") -> tuple[str, str, str]:
        events = (
            db.query(ContextEvent)
            .filter(ContextEvent.session_id == session.id)
            .order_by(ContextEvent.timestamp.asc())
            .all()
        )
        context_lattice_service.upsert_rollups(db, session)
        provider = get_provider(session.model_provider)
        provider_diagnostics = provider.runtime_diagnostics()
        title = MODE_TITLES.get(mode, MODE_TITLES["clean_summary"])
        deterministic = self._deterministic_markdown(session, events, title, mode, provider.name)

        if provider.name != "mock" and events:
            prompt = self._prompt(session, events, mode)
            try:
                generated = self._sanitize_model_output(provider.generate(prompt))
                if self._model_output_is_useful(generated, events):
                    deterministic = generated.strip()
                    status = "ok"
                    error = ""
                else:
                    status = "fallback_low_quality"
                    error = "model output did not pass note quality gate"
            except Exception as exc:  # noqa: BLE001
                status = "fallback_to_template"
                error = str(exc)
        else:
            prompt = "mock-template"
            status = "ok"
            error = ""

        db.add(
            ModelRun(
                session_id=session.id,
                provider=provider.name,
                model=self._provider_model_name(provider),
                mode=mode,
                prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                output_hash=hashlib.sha256(deterministic.encode("utf-8")).hexdigest(),
                gpu_active=bool(provider_diagnostics.get("gpu_active")),
                runtime_location=provider.runtime_location,
                status=status,
                error=error,
            )
        )
        db.commit()
        return title, deterministic, provider.name

    def _deterministic_markdown(
        self,
        session: Session,
        events: list[ContextEvent],
        title: str,
        mode: str,
        provider_name: str,
    ) -> str:
        apps = sorted({event.active_app for event in events if event.active_app}) or ["Unknown"]
        topics = Counter(event.detected_topic for event in events)
        tasks = Counter(event.detected_task for event in events)
        started = session.started_at.isoformat() if session.started_at else ""
        ended = session.ended_at.isoformat() if session.ended_at else "In progress"
        warnings = sum(1 for event in events if event.sensitivity_score >= 0.5)
        stored_events = [event for event in events if _event_privacy_action(event) == "store_redacted"]
        omitted_events = len(events) - len(stored_events)
        confidences = [_event_ocr_confidence(event) for event in stored_events]
        confidences = [value for value in confidences if value is not None]
        average_confidence = sum(confidences) / len(confidences) if confidences else None
        low_confidence_count = sum(1 for value in confidences if value < 0.72)
        timeline = _timeline_entries(stored_events)
        capture_quality = _capture_quality_text(len(events), average_confidence, low_confidence_count, omitted_events)

        body = [
            f"# {title}",
            "",
            f"- Session ID: `{session.id}`",
            f"- Date/time: {started}",
            f"- Session end: {ended}",
            f"- Objective: {session.objective or 'Not provided'}",
            f"- Generation mode: `{mode}`",
            f"- AI provider: `{provider_name}`",
            f"- Local model preference: `{session.model_provider}`",
            f"- OCR profile: `{session.ocr_provider}/{session.ocr_profile}`",
            f"- Privacy strictness: `{session.privacy_strictness}`",
            f"- Context events: {len(events)}",
            f"- Apps involved: {', '.join(apps)}",
            f"- Privacy mode: {'enabled' if session.privacy_mode else 'disabled'}",
            f"- Evidence mode: {'enabled' if session.evidence_mode else 'disabled'}",
            "",
            "## Session Goal",
            "",
            f"> {session.objective or 'Not provided'}",
            "",
            "## Capture Quality",
            "",
            *capture_quality,
            "",
            "## Activity Rollup",
            "",
            self._counter_text("Topics", topics),
            self._counter_text("Tasks", tasks),
            "",
            "## Observed Timeline",
            "",
            *timeline,
            "",
            "## Useful Details",
            "",
            *_useful_detail_lines(events, topics, tasks),
            "",
            "## Follow-Up Actions",
            "",
            *_follow_up_lines(events, average_confidence, low_confidence_count),
            "",
            "## Open Questions",
            "",
            *_open_question_lines(events, omitted_events),
            "",
            "## Confidence",
            "",
            f"- Confidence level: {_confidence_level(events, average_confidence, low_confidence_count)}",
            f"- Redaction notices: {warnings} event(s) had elevated sensitivity.",
        ]
        return "\n".join(body)

    @staticmethod
    def _counter_text(label: str, values: Counter[str]) -> str:
        if not values:
            return f"- {label}: none detected"
        return f"- {label}: " + ", ".join(f"{name} ({count})" for name, count in values.most_common())

    @staticmethod
    def _prompt(session: Session, events: list[ContextEvent], mode: str) -> str:
        snippets = "\n".join(_event_prompt_line(event) for event in events[:80])
        return f"""Generate a Markdown {mode} from local, redacted context.

Rules:
- Do not claim access to raw screenshots.
- Mention when OCR/context is incomplete.
- Do not dump, reconstruct, or quote raw OCR transcripts.
- Do not list UI chrome, OCR artifacts, random symbols, or special-character noise.
- Synthesize concise observations from event metadata and any readable keyword hints.
- Do not include verbatim excerpts longer than 10 words.
- Treat low-confidence OCR as uncertain and say so.
- Include redaction notices.
- Preserve [REDACTED_*] placeholders exactly and do not infer hidden values.
- Treat the session goal as user intent for interpretation, not as observed evidence.
- If the goal asks for time/task split, organize the output by the stated tasks where the events support it.
- Prefer useful headings like Capture Quality, Observed Timeline, Activity Rollup, Follow-Up Actions, and Open Questions.
- Return final Markdown only. Do not include hidden reasoning, scratch work, or chain-of-thought.
- Do not wrap the answer in a Markdown code fence.
- Keep output enterprise-defensible.

Session goal: {session.objective or 'Not provided'}
Started: {session.started_at.isoformat() if session.started_at else dt.datetime.now(dt.UTC).isoformat()}

Redacted structured events:
{snippets}
"""

    @staticmethod
    def _provider_model_name(provider: object) -> str:
        try:
            models = provider.list_models()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return ""
        if not models:
            return ""
        return str(models[0].get("name", ""))

    @staticmethod
    def _sanitize_model_output(text: str) -> str:
        import re

        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
        fenced = re.match(r"^```(?:markdown|md)?\s*(.*?)\s*```$", cleaned, flags=re.I | re.S)
        return (fenced.group(1) if fenced else cleaned).strip()

    @staticmethod
    def _model_output_is_useful(text: str, events: list[ContextEvent]) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return False
        if events and len(cleaned) < 120:
            return False
        lowered = cleaned.lower()
        rejected_phrases = (
            "durable memory contains only structured metadata",
            "raw screenshots are treated as ephemeral processing material",
            "mock ai mode active",
        )
        if any(phrase in lowered for phrase in rejected_phrases):
            return False
        if contains_ocr_dump(cleaned):
            return False
        return cleaned.startswith("#") or "\n## " in cleaned


note_generator = NoteGenerator()


def _event_privacy_action(event: ContextEvent) -> str:
    try:
        data = json.loads(event.redaction_summary or "{}")
    except json.JSONDecodeError:
        return "store_redacted"
    if isinstance(data, dict):
        decision = data.get("privacy_decision", {})
        if isinstance(decision, dict):
            return str(decision.get("action") or "store_redacted")
    return "store_redacted"


def _event_ocr_payload(event: ContextEvent) -> dict | None:
    try:
        data = json.loads(event.redaction_summary or "{}")
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and isinstance(data.get("ocr"), dict):
        return data["ocr"]
    return None


def _event_ocr_confidence(event: ContextEvent) -> float | None:
    ocr = _event_ocr_payload(event)
    if not ocr:
        return None
    try:
        value = ocr.get("average_confidence")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _event_ocr_elapsed_ms(event: ContextEvent) -> float | None:
    ocr = _event_ocr_payload(event)
    if not ocr:
        return None
    try:
        value = ocr.get("elapsed_ms")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _event_excerpt(event: ContextEvent, limit: int = 280) -> str:
    text = event.summary_snippet or event.redacted_text_snippet or ""
    return _clean_excerpt(text, limit=limit)


def _clean_excerpt(text: str, limit: int | None = None) -> str:
    return clean_focus_text(text, strip_file_references=True, limit=limit)


def _timeline_entries(events: list[ContextEvent]) -> list[str]:
    entries: list[str] = []
    for event in events:
        timestamp = event.timestamp.strftime("%H:%M:%S") if event.timestamp else "time unknown"
        window = _display_window_title(event.active_window_title)
        topic_task = f"{event.detected_topic}/{event.detected_task}"
        excerpt = _event_excerpt(event)
        quality = _ocr_quality_label(_event_ocr_confidence(event), excerpt)
        elapsed = _event_ocr_elapsed_ms(event)
        elapsed_text = f", {round(elapsed)} ms" if elapsed is not None else ""
        entries.append(
            f"- {timestamp} - {event.active_app or 'Unknown app'} / {window}: "
            f"observed {topic_task.replace('_', ' ')} activity ({quality}{elapsed_text}). {_event_text_hint(event)}"
        )
        if len(entries) >= 18:
            remaining = len(events) - 18
            if remaining > 0:
                entries.append(f"- {remaining} additional event(s) were captured and included in rollups.")
            break
    return entries or ["- No redacted OCR text was available for the stored context events."]


def _display_window_title(title: str | None) -> str:
    cleaned = clean_focus_text(title or "", strip_file_references=True, limit=60)
    return cleaned or "focused window"


def _capture_quality_text(
    event_count: int,
    average_confidence: float | None,
    low_confidence_count: int,
    omitted_events: int,
) -> list[str]:
    if event_count == 0:
        return ["- No context events were captured, so no reliable work summary can be inferred."]
    lines = [f"- Stored {event_count} compact context event(s); raw frame artifacts were not retained."]
    if average_confidence is None:
        lines.append("- OCR confidence was not reported by the provider.")
    else:
        lines.append(f"- Average OCR confidence: {round(average_confidence * 100)}%.")
    if low_confidence_count:
        lines.append(f"- {low_confidence_count} event(s) had low OCR confidence; transcript text was not used for exact notes.")
    if omitted_events:
        lines.append(f"- {omitted_events} event(s) were omitted or reduced to metadata by privacy policy.")
    return lines


def _useful_detail_lines(events: list[ContextEvent], topics: Counter[str], tasks: Counter[str]) -> list[str]:
    if not events:
        return ["- No observed activity was available. Start a longer capture and keep the target screen visible."]
    lines: list[str] = []
    lines.append("- Generated notes intentionally summarize session activity instead of dumping OCR transcripts.")
    if topics:
        topic, topic_count = topics.most_common(1)[0]
        lines.append(f"- Main observed topic: {topic.replace('_', ' ')} ({topic_count} event(s)).")
    if tasks:
        task, task_count = tasks.most_common(1)[0]
        lines.append(f"- Main observed task type: {task.replace('_', ' ')} ({task_count} event(s)).")
    terms = _recurring_readable_terms(events)
    if terms:
        lines.append(f"- Recurring readable terms: {', '.join(terms)}.")
    else:
        lines.append("- No clean recurring text terms passed the note-quality gate; OCR transcript text was omitted.")
    if len(events) < 3:
        lines.append("- The session has very few events, so time split and sequence inference are limited.")
    return lines


def _follow_up_lines(events: list[ContextEvent], average_confidence: float | None, low_confidence_count: int) -> list[str]:
    if not events:
        return ["- Capture again with the target application selected until at least a few events are stored."]
    lines = ["- Review the source session in the app if exact wording matters; exported notes intentionally avoid OCR transcript dumps."]
    if low_confidence_count or (average_confidence is not None and average_confidence < 0.78):
        lines.append("- If this text matters, rerun with `screen-accurate` OCR or increase the target app font size.")
    if len(events) < 5:
        lines.append("- Run a longer session if you need a defensible time/task split.")
    return lines


def _open_question_lines(events: list[ContextEvent], omitted_events: int) -> list[str]:
    if not events:
        return ["- Was the intended screen or window selected in the capture picker?"]
    lines = ["- Did the captured window stay on the intended task for the full session?"]
    if omitted_events:
        lines.append("- Were the metadata-only privacy reductions expected for this workflow?")
    return lines


def _ocr_quality_label(confidence: float | None, excerpt: str) -> str:
    if confidence is None:
        return "OCR confidence unknown" + (", noisy text" if looks_noisy(excerpt) else "")
    label = f"OCR {round(confidence * 100)}%"
    if confidence < 0.72 or looks_noisy(excerpt):
        return f"{label}, noisy text"
    return label


def _event_text_hint(event: ContextEvent) -> str:
    terms = _event_readable_terms(event, limit=5)
    if terms:
        return f"Readable keyword hints: {', '.join(terms)}."
    excerpt = _event_excerpt(event)
    if excerpt:
        return "OCR transcript omitted from notes because it was noisy, low-confidence, or too transcript-like."
    return "No readable text hint was available."


def _event_readable_terms(event: ContextEvent, limit: int = 8) -> list[str]:
    confidence = _event_ocr_confidence(event)
    text = event.summary_snippet or event.redacted_text_snippet or ""
    if not text:
        return []
    if confidence is not None and confidence < 0.78:
        return []
    return readable_terms(text, limit=limit)


def _recurring_readable_terms(events: list[ContextEvent], limit: int = 8) -> list[str]:
    counts: Counter[str] = Counter()
    for event in events:
        counts.update(_event_readable_terms(event, limit=12))
    return [word for word, _count in counts.most_common(limit)]


def _confidence_level(events: list[ContextEvent], average_confidence: float | None, low_confidence_count: int) -> str:
    if not events:
        return "low"
    if len(events) < 3:
        return "low"
    if average_confidence is not None and average_confidence >= 0.85 and low_confidence_count == 0:
        return "high"
    if average_confidence is not None and average_confidence < 0.72:
        return "low"
    return "medium"


def _event_prompt_line(event: ContextEvent) -> str:
    timestamp = event.timestamp.isoformat() if event.timestamp else ""
    privacy_action = _event_privacy_action(event)
    if privacy_action != "store_redacted":
        return (
            f"- [{timestamp}] {event.active_app or 'Unknown app'}: "
            f"[{privacy_action} context omitted before LLM ingestion; "
            f"topic={event.detected_topic}; task={event.detected_task}; sensitivity={event.sensitivity_score:.2f}]"
        )
    excerpt = _event_excerpt(event)
    confidence = _event_ocr_confidence(event)
    quality = _ocr_quality_label(confidence, excerpt)
    return (
        f"- [{timestamp}] {event.active_app} / {_display_window_title(event.active_window_title)}: "
        f"topic={event.detected_topic}; task={event.detected_task}; quality={quality}; "
        f"{_event_text_hint(event)}"
    )
