from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.context_lattice.service import context_lattice_service


@dataclass(frozen=True)
class LabelResult:
    topic: str
    task: str
    confidence: float
    provider: str
    model: str


class LiveLabelerService:
    """Fast per-event labeler for the capture loop.

    The POC keeps this inline so OCR remains the only live GPU workload during frame
    ingestion. A future 1B-3B local model can be added behind this API as a
    single-worker queue after benchmarking.
    """

    mode = "fast_inline"
    provider = "context_lattice"
    model = "objective_keyword_labeler"
    gpu_instances = 0

    def label(self, *, text: str, active_app: str, window_title: str, objective: str) -> LabelResult:
        topic, task, confidence = context_lattice_service.classify(
            text,
            active_app=active_app,
            window_title=window_title,
            objective=objective,
        )
        return LabelResult(topic=topic, task=task, confidence=confidence, provider=self.provider, model=self.model)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "gpu_instances": self.gpu_instances,
            "queue": "inline",
            "notes": "Frame ingestion uses a lightweight local labeler; the larger reasoning model is reserved for stop/manual note generation.",
        }


live_labeler_service = LiveLabelerService()
