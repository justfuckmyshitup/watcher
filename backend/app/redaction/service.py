from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionFindingDTO:
    kind: str
    value_hash: str
    replacement: str
    confidence: float


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: list[RedactionFindingDTO]
    sensitivity_score: float


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str, float], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.I | re.S), "[REDACTED_PRIVATE_KEY]", 0.98),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]", 0.94),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I), "[REDACTED_BEARER_TOKEN]", 0.92),
    ("api_key", re.compile(r"\b(?:api[_-]?key|secret|token|client[_-]?secret|access[_-]?token|refresh[_-]?token|oauth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{16,}['\"]?", re.I), "[REDACTED_SECRET]", 0.88),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]", 0.95),
    ("ssn", re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"), "[REDACTED_SSN]", 0.9),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.I), "[REDACTED_IBAN]", 0.86),
    ("routing_number", re.compile(r"\b(?:routing|aba)\s*(?:number|no\.?|#)?\s*[:=]?\s*\d{9}\b", re.I), "[REDACTED_ROUTING_NUMBER]", 0.86),
    ("account_number", re.compile(r"\b(?:account|acct|member|policy|customer)\s*(?:number|no\.?|id|#)?\s*[:=]?\s*[A-Z0-9 -]{6,24}\b", re.I), "[REDACTED_ACCOUNT_ID]", 0.82),
    ("password_assignment", re.compile(r"\b(password|passwd|pwd)\s*[:=]\s*\S+", re.I), "[REDACTED_PASSWORD_FIELD]", 0.92),
    ("masked_password", re.compile(r"\b(?:password|passwd|pwd)\b.{0,24}(?:\*{4,}|[.\u2022]{4,})", re.I), "[REDACTED_MASKED_PASSWORD]", 0.9),
    ("mfa_code", re.compile(r"\b(?:mfa|otp|verification|auth(?:entication)? code|2fa|two[- ]factor)\D{0,24}\d{6,8}\b", re.I), "[REDACTED_MFA_CODE]", 0.84),
)

CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

SENSITIVE_WINDOW_TERMS = (
    "1password",
    "bitwarden",
    "lastpass",
    "keeper",
    "dashlane",
    "password manager",
    "bank",
    "payroll",
    "medical",
    "patient",
    "hr system",
    "human resources",
    "mfa",
    "two-factor",
    "2fa",
    "authenticator",
    "okta verify",
    "duo",
    "login",
    "sign in",
    "routing",
    "account number",
    "social security",
    "credit card",
    "brokerage",
    "tax",
    "insurance",
)


def stable_hash(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8", errors="ignore")
    return hashlib.sha256(value).hexdigest()


class RedactionService:
    def redact_text(self, text: str, custom_terms: list[str] | None = None) -> RedactionResult:
        if not text:
            return RedactionResult(text="", findings=[], sensitivity_score=0.0)

        redacted = text
        findings: list[RedactionFindingDTO] = []

        for kind, pattern, replacement, confidence in SECRET_PATTERNS:
            redacted = pattern.sub(lambda match: self._record(match.group(0), kind, replacement, confidence, findings), redacted)

        redacted = CREDIT_CARD_PATTERN.sub(lambda match: self._redact_card(match.group(0), findings), redacted)

        for term in custom_terms or []:
            if not term:
                continue
            pattern = re.compile(re.escape(term), re.I)
            redacted = pattern.sub(lambda match: self._record(match.group(0), "custom_term", "[REDACTED_CUSTOM_TERM]", 0.8, findings), redacted)

        score = min(1.0, 0.12 * len(findings) + max((finding.confidence for finding in findings), default=0.0) * 0.45)
        return RedactionResult(text=redacted, findings=findings, sensitivity_score=round(score, 3))

    def sensitive_window_score(self, app_name: str, window_title: str) -> tuple[float, list[RedactionFindingDTO]]:
        combined = f"{app_name} {window_title}".lower()
        findings: list[RedactionFindingDTO] = []
        for term in SENSITIVE_WINDOW_TERMS:
            if term in combined:
                findings.append(
                    RedactionFindingDTO(
                        kind="sensitive_window",
                        value_hash=stable_hash(term),
                        replacement="[SENSITIVE_WINDOW]",
                        confidence=0.86,
                    )
                )
        if not findings:
            return 0.0, []
        return min(1.0, 0.35 + 0.1 * len(findings)), findings

    @staticmethod
    def _record(
        value: str,
        kind: str,
        replacement: str,
        confidence: float,
        findings: list[RedactionFindingDTO],
    ) -> str:
        findings.append(
            RedactionFindingDTO(
                kind=kind,
                value_hash=stable_hash(value),
                replacement=replacement,
                confidence=confidence,
            )
        )
        return replacement

    def _redact_card(self, value: str, findings: list[RedactionFindingDTO]) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) < 13 or len(digits) > 19 or not self._luhn_valid(digits):
            return value
        return self._record(value, "credit_card", "[REDACTED_CARD]", 0.9, findings)

    @staticmethod
    def _luhn_valid(digits: str) -> bool:
        total = 0
        parity = len(digits) % 2
        for index, char in enumerate(digits):
            value = int(char)
            if index % 2 == parity:
                value *= 2
                if value > 9:
                    value -= 9
            total += value
        return total % 10 == 0


redaction_service = RedactionService()
