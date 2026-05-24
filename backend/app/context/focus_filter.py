from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable


UI_CHROME_PATTERNS = (
    r"\bFile\s+Edit\s+View(?:\s+Window\s+Help)?\b",
    r"\bLn\s+\d+\s*,\s*Col\s+\d+\b",
    r"\b\d+\s+characters?\b",
    r"\bPlain\s+text\b",
    r"\bWindows\s+\(CRLF\)",
    r"\bUTF-?8\b",
    r"\b\d+\s*%",
    r"\bShow\s+\d+\s+more\b",
    r"\bShow\s+more\b",
    r"\bReview\s+attachment\b",
    r"\bBranch\s+details\b",
    r"\bNo\s+changes\b",
    r"\bGit\s+actions\b",
    r"\bGitHub\s+CLI\s+unavailable\b",
    r"\bArtifacts?\b",
    r"\bSources?\b",
    r"\bWeb\s+search\b",
    r"\bWork\s+locally\b",
    r"\bDefault\s+permissions\b",
    r"\bExtra\s+High\b",
    r"\bStart\s+menu\b",
    r"\bTaskbar\b",
    r"\bSystem\s+tray\b",
)

FILE_REFERENCE_PATTERN = (
    r"\b[A-Za-z0-9_.\\/+-]+\."
    r"(?:md|py|ts|tsx|js|jsx|json|lock|toml|yml|yaml|env|txt|png|jpg|jpeg|svg|bin|onnx|gguf)\b"
)

DEFAULT_STOPWORDS = {
    "about",
    "active",
    "after",
    "again",
    "also",
    "and",
    "are",
    "artifact",
    "artifacts",
    "attachment",
    "branch",
    "but",
    "can",
    "capture",
    "characters",
    "click",
    "cli",
    "codex",
    "column",
    "changes",
    "default",
    "details",
    "desktop",
    "does",
    "edit",
    "extra",
    "file",
    "from",
    "git",
    "github",
    "have",
    "help",
    "high",
    "into",
    "line",
    "local",
    "master",
    "menu",
    "more",
    "next",
    "not",
    "notes",
    "open",
    "permissions",
    "plain",
    "review",
    "screen",
    "search",
    "show",
    "source",
    "sources",
    "start",
    "taskbar",
    "text",
    "that",
    "the",
    "this",
    "unavailable",
    "view",
    "web",
    "window",
    "with",
    "work",
    "working",
}


def clean_focus_text(text: str, *, strip_file_references: bool = False, limit: int | None = None) -> str:
    """Remove obvious UI chrome and OCR glitches from a text snippet.

    This is intentionally conservative: it does not try to preserve an exact
    transcript. It prepares OCR text for summarization, labeling, and preview.
    """

    cleaned = " ".join((text or "").split())
    for pattern in UI_CHROME_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    if strip_file_references:
        cleaned = re.sub(FILE_REFERENCE_PATTERN, " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:\s*\.env\b){2,}", " .env", cleaned, flags=re.I)
    cleaned = re.sub(r"\b([A-Za-z][A-Za-z0-9_.-]{1,24})(?:\s+\1\b){3,}", r"\1", cleaned)
    if looks_noisy(cleaned):
        cleaned = re.sub(r"[^\x20-\x7E]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.")
    if limit is not None and len(cleaned) > limit:
        return f"{cleaned[: max(limit - 3, 0)].rstrip()}..."
    return cleaned


def contains_ui_chrome(text: str) -> bool:
    return any(re.search(pattern, text or "", flags=re.I) for pattern in UI_CHROME_PATTERNS)


def looks_noisy(text: str) -> bool:
    if len(text) < 20:
        return False
    ascii_letters = sum(1 for char in text if ("a" <= char.lower() <= "z"))
    digits = sum(1 for char in text if char.isdigit())
    spaces = sum(1 for char in text if char.isspace())
    punctuation = sum(1 for char in text if char in ".,:;!?/_-[]()'\"`")
    signal = ascii_letters + digits + spaces + punctuation
    unusual_ratio = 1 - (signal / max(len(text), 1))
    return unusual_ratio > 0.22


def contains_ocr_dump(text: str) -> bool:
    lowered = (text or "").lower()
    transcript_markers = (
        "file edit view",
        "ln 1, col",
        "plain text",
        "windows (crlf)",
        "utf-8",
        "review attachment",
        "branch details",
        "github cli unavailable",
        "web search",
    )
    if any(term in lowered for term in transcript_markers):
        return True
    noisy_lines = 0
    candidate_lines = [line.strip() for line in (text or "").splitlines() if len(line.strip()) >= 80]
    for line in candidate_lines:
        if looks_noisy(line):
            noisy_lines += 1
    return noisy_lines >= 2


def readable_terms(text: str, *, limit: int = 8, extra_stopwords: Iterable[str] = ()) -> list[str]:
    focused = clean_focus_text(text, strip_file_references=True)
    if not focused or looks_noisy(focused):
        return []
    stopwords = DEFAULT_STOPWORDS | {word.lower() for word in extra_stopwords}
    words = [
        word.lower()
        for word in re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", focused)
        if word.lower() not in stopwords and len(word) <= 24
    ]
    counts = Counter(words)
    return [word for word, _count in counts.most_common(limit)]
