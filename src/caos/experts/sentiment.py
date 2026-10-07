from __future__ import annotations

from typing import Any

from .base import ExpertUnavailable, SentimentResult


class ModernFinBERTExpert:
    """Financial text sentiment specialist.

    Default model: neoyipeng/ModernFinBERT-base (Apache-2.0, 149M parameters).
    The classifier is lazily created, so base C.A.O.S installs remain dependency-light.
    """

    name = "modernfinbert"

    def __init__(
        self,
        model_id: str = "neoyipeng/ModernFinBERT-base",
        device: int | str | None = None,
        classifier: Any | None = None,
    ):
        self.model_id = model_id
        self.device = device
        self._classifier = classifier

    def _load(self):
        if self._classifier is not None:
            return self._classifier
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise ExpertUnavailable(
                "ModernFinBERT requires optional sentiment dependencies: "
                "pip install -e .[sentiment]"
            ) from exc

        kwargs: dict[str, Any] = {
            "task": "text-classification",
            "model": self.model_id,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        self._classifier = pipeline(**kwargs)
        return self._classifier

    @staticmethod
    def _signed(label: str, score: float) -> float:
        label = label.upper()
        if "POS" in label:
            return score
        if "NEG" in label:
            return -score
        return 0.0

    def classify(self, text: str) -> SentimentResult:
        if not text.strip():
            raise ValueError("text required")
        result = self._load()(text)
        if isinstance(result, list):
            result = result[0]
        label = str(result["label"]).upper()
        score = float(result["score"])
        return SentimentResult(
            model=self.name,
            label=label,
            score=score,
            signed_score=self._signed(label, score),
            metadata={"model_id": self.model_id},
        )
