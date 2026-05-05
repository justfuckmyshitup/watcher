from __future__ import annotations

import re

from sqlalchemy.orm import Session as DbSession

from backend.app.storage.models import AppExclusion


def matching_exclusion(db: DbSession, active_app: str, window_title: str) -> AppExclusion | None:
    rules = db.query(AppExclusion).filter(AppExclusion.enabled.is_(True)).all()
    app = active_app or ""
    title = window_title or ""
    for rule in rules:
        target = _target_for_rule(rule.pattern_type, app, title)
        if _matches(rule, target):
            return rule
    return None


def _target_for_rule(pattern_type: str, app: str, title: str) -> str:
    if pattern_type == "app":
        return app
    if pattern_type == "both":
        return f"{app} {title}"
    return title


def _matches(rule: AppExclusion, target: str) -> bool:
    if rule.is_regex:
        try:
            return re.search(rule.pattern, target, re.I) is not None
        except re.error:
            return False
    return rule.pattern.lower() in target.lower()

