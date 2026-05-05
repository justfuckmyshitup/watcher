from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from backend.app.redaction.service import RedactionFindingDTO, stable_hash


PrivacyAction = Literal["store_redacted", "metadata_only", "drop_event", "needs_user_review"]


@dataclass(frozen=True)
class PrivacyDecision:
    action: PrivacyAction
    sensitivity_score: float
    reasons: list[str]
    retention_policy: dict[str, bool | str]
    redaction_findings: list[RedactionFindingDTO]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["redaction_findings"] = [asdict(finding) for finding in self.redaction_findings]
        return data


DROP_WINDOW_TERMS = (
    "1password",
    "bitwarden",
    "lastpass",
    "keeper",
    "dashlane",
    "password manager",
    "credential manager",
    "keychain",
    "authenticator",
    "microsoft authenticator",
    "google authenticator",
    "authy",
    "duo",
    "okta verify",
    "mfa",
    "2fa",
    "two-factor",
    "passkey",
)

METADATA_ONLY_WINDOW_TERMS = (
    "bank",
    "banking",
    "credit union",
    "brokerage",
    "trading",
    "payroll",
    "benefits",
    "medical",
    "patient",
    "health",
    "hr system",
    "human resources",
    "tax",
    "insurance",
    "social security",
    "account number",
    "billing",
)

DROP_FINDING_KINDS = {
    "private_key",
    "mfa_code",
    "masked_password",
}

METADATA_ONLY_FINDING_KINDS = {
    "password_assignment",
    "ssn",
    "credit_card",
    "routing_number",
    "account_number",
    "iban",
}

HIGH_SECRET_FINDING_KINDS = {
    "api_key",
    "bearer_token",
    "jwt",
    "aws_access_key",
}


class PrivacyDecisionEngine:
    def evaluate(
        self,
        *,
        active_app: str,
        window_title: str,
        redacted_text: str,
        redaction_findings: list[RedactionFindingDTO],
        sensitivity_score: float,
        privacy_mode: bool = True,
        privacy_strictness: str = "standard",
    ) -> PrivacyDecision:
        strictness = _normalize_strictness(privacy_strictness)
        if not privacy_mode:
            return self._decision(
                "store_redacted",
                sensitivity_score,
                ["privacy_mode_disabled_but_raw_artifacts_still_ephemeral"],
                redaction_findings,
            )

        reasons: list[str] = []
        decision_findings: list[RedactionFindingDTO] = []
        combined = f"{active_app} {window_title}".lower()

        for term in DROP_WINDOW_TERMS:
            if term in combined:
                reasons.append(f"drop_window_term:{term}")
                decision_findings.append(_window_finding(term, "drop_window"))

        if reasons:
            action: PrivacyAction = "drop_event" if strictness in {"standard", "strict", "maximum"} else "metadata_only"
            return self._decision(action, max(sensitivity_score, 0.95), reasons, [*redaction_findings, *decision_findings])

        for term in METADATA_ONLY_WINDOW_TERMS:
            if term in combined:
                reasons.append(f"metadata_window_term:{term}")
                decision_findings.append(_window_finding(term, "metadata_window"))

        finding_kinds = {finding.kind for finding in redaction_findings}
        if DROP_FINDING_KINDS.intersection(finding_kinds):
            reasons.append("drop_finding:" + ",".join(sorted(DROP_FINDING_KINDS.intersection(finding_kinds))))
            return self._decision("drop_event", max(sensitivity_score, 0.92), reasons, redaction_findings)

        metadata_kinds = METADATA_ONLY_FINDING_KINDS.intersection(finding_kinds)
        if metadata_kinds:
            reasons.append("metadata_finding:" + ",".join(sorted(metadata_kinds)))

        high_secret_count = sum(1 for finding in redaction_findings if finding.kind in HIGH_SECRET_FINDING_KINDS)
        if high_secret_count >= 3:
            reasons.append("metadata_many_secret_findings")

        if _looks_like_credential_form(redacted_text):
            reasons.append("metadata_credential_form_layout")

        if reasons:
            return self._decision(
                "drop_event" if strictness == "maximum" else "metadata_only",
                max(sensitivity_score, 0.76),
                reasons,
                [*redaction_findings, *decision_findings],
            )

        if strictness == "maximum" and redaction_findings:
            return self._decision("metadata_only", max(sensitivity_score, 0.72), ["metadata_maximum_privacy_any_redaction"], redaction_findings)

        if strictness == "strict" and (redaction_findings or sensitivity_score >= 0.5):
            return self._decision("metadata_only", max(sensitivity_score, 0.68), ["metadata_strict_privacy_signal"], redaction_findings)

        if sensitivity_score >= 0.88:
            return self._decision("metadata_only", sensitivity_score, ["metadata_high_sensitivity_score"], redaction_findings)

        return self._decision("store_redacted", sensitivity_score, ["redacted_text_allowed"], redaction_findings)

    @staticmethod
    def _decision(
        action: PrivacyAction,
        sensitivity_score: float,
        reasons: list[str],
        findings: list[RedactionFindingDTO],
    ) -> PrivacyDecision:
        return PrivacyDecision(
            action=action,
            sensitivity_score=round(min(1.0, max(0.0, sensitivity_score)), 3),
            reasons=reasons,
            redaction_findings=findings,
            retention_policy={
                "persist_raw_screenshot": False,
                "persist_unredacted_ocr": False,
                "persist_redacted_text": action == "store_redacted",
                "persist_metadata": action in {"store_redacted", "metadata_only", "needs_user_review"},
                "send_to_llm": action == "store_redacted",
                "notes": "drop_event stores only a user action log; metadata_only stores hashes/app/window metadata without OCR text.",
            },
        )


def _window_finding(term: str, kind: str) -> RedactionFindingDTO:
    return RedactionFindingDTO(
        kind=kind,
        value_hash=stable_hash(term),
        replacement="[SENSITIVE_WINDOW]",
        confidence=0.9,
    )


def _looks_like_credential_form(text: str) -> bool:
    lowered = text.lower()
    labels = sum(1 for token in ("username", "email", "password", "sign in", "login", "remember me") if token in lowered)
    return labels >= 2 and ("[redacted_password" in lowered or "password" in lowered)


def _normalize_strictness(value: str) -> str:
    normalized = (value or "standard").strip().lower()
    if normalized in {"standard", "strict", "maximum"}:
        return normalized
    return "standard"


privacy_decision_engine = PrivacyDecisionEngine()
