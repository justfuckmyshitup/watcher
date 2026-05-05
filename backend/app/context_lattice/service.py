from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import desc
from sqlalchemy.orm import Session as DbSession

from backend.app.storage.models import ContextEvent, Session, TaskRollup, TopicRollup, utcnow


TOPIC_KEYWORDS = {
    "marketing": ("marketing", "campaign", "copy", "brand", "audience", "content", "landing", "social", "newsletter"),
    "education": ("school", "class", "assignment", "course", "homework", "study", "lesson", "essay", "research"),
    "security": ("alert", "incident", "ioc", "malware", "vulnerability", "scan", "siem", "firewall"),
    "it_admin": ("server", "docker", "service", "registry", "domain", "policy", "endpoint", "powershell"),
    "software": ("commit", "build", "test", "error", "stack", "api", "database", "frontend", "backend"),
    "support": ("ticket", "customer", "case", "issue", "resolution", "sla"),
    "grc": ("audit", "control", "evidence", "risk", "compliance", "policy"),
    "sales": ("opportunity", "lead", "quote", "proposal", "account", "customer"),
}

TASK_KEYWORDS = {
    "writing": ("write", "writing", "draft", "outline", "edit", "revise", "copy", "essay"),
    "research": ("research", "read", "source", "citation", "study", "analyze"),
    "troubleshooting": ("error", "failed", "timeout", "exception", "diagnose", "restart"),
    "configuration": ("setting", "configure", "policy", "profile", "permission"),
    "evidence_collection": ("audit", "evidence", "control", "screenshot", "log"),
    "documentation": ("note", "sop", "runbook", "procedure", "summary"),
    "change_management": ("change", "deploy", "release", "rollback", "migration"),
}


class ContextLatticeService:
    def classify(self, text: str, active_app: str = "", window_title: str = "", objective: str = "") -> tuple[str, str, float]:
        observed_haystack = f"{active_app} {window_title} {text}".lower()
        objective_haystack = objective.lower()
        topic = self._best_match(observed_haystack, TOPIC_KEYWORDS, "")
        task = self._best_match(observed_haystack, TASK_KEYWORDS, "")
        objective_used = False
        if not topic:
            topic = self._best_match(objective_haystack, TOPIC_KEYWORDS, "general")
            objective_used = topic != "general"
        if not task:
            task = self._best_match(objective_haystack, TASK_KEYWORDS, "documentation")
            objective_used = objective_used or task != "documentation"
        confidence = 0.72 if not objective_used and (topic != "general" or task != "documentation") else 0.55 if objective_used else 0.45
        return topic, task, confidence

    def related_event_ids(self, db: DbSession, session_id: str, topic: str, task: str, limit: int = 5) -> list[str]:
        rows = (
            db.query(ContextEvent)
            .filter(ContextEvent.session_id == session_id)
            .filter((ContextEvent.detected_topic == topic) | (ContextEvent.detected_task == task))
            .order_by(desc(ContextEvent.timestamp))
            .limit(limit)
            .all()
        )
        return [row.id for row in rows]

    def upsert_rollups(self, db: DbSession, session: Session) -> dict[str, list[dict[str, object]]]:
        events = db.query(ContextEvent).filter(ContextEvent.session_id == session.id).all()
        topics = Counter(event.detected_topic for event in events)
        tasks = Counter(event.detected_task for event in events)
        topic_rows = []
        task_rows = []

        for topic, count in topics.items():
            summary = self._rollup_summary(events, "detected_topic", topic)
            row = db.query(TopicRollup).filter(TopicRollup.session_id == session.id, TopicRollup.topic == topic).first()
            if not row:
                row = TopicRollup(session_id=session.id, topic=topic)
                db.add(row)
            row.summary = summary
            row.event_count = count
            row.updated_at = utcnow()
            topic_rows.append({"topic": topic, "event_count": count, "summary": summary})

        for task, count in tasks.items():
            summary = self._rollup_summary(events, "detected_task", task)
            row = db.query(TaskRollup).filter(TaskRollup.session_id == session.id, TaskRollup.task == task).first()
            if not row:
                row = TaskRollup(session_id=session.id, task=task)
                db.add(row)
            row.summary = summary
            row.event_count = count
            row.updated_at = utcnow()
            task_rows.append({"task": task, "event_count": count, "summary": summary})

        db.commit()
        return {"topics": topic_rows, "tasks": task_rows}

    @staticmethod
    def _best_match(haystack: str, keyword_map: dict[str, tuple[str, ...]], fallback: str) -> str:
        scores = {
            label: sum(1 for keyword in keywords if keyword in haystack)
            for label, keywords in keyword_map.items()
        }
        label, score = max(scores.items(), key=lambda item: item[1])
        return label if score > 0 else fallback

    @staticmethod
    def _rollup_summary(events: list[ContextEvent], attr: str, value: str) -> str:
        snippets = [event.summary_snippet for event in events if getattr(event, attr) == value and event.summary_snippet]
        joined = " ".join(snippets[:5])
        if not joined:
            return f"{value.replace('_', ' ').title()} activity was observed without extracted text."
        if len(joined) <= 500:
            return joined
        return f"{joined[:497]}..."


def json_dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


context_lattice_service = ContextLatticeService()
