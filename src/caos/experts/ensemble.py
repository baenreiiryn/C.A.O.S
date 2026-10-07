from __future__ import annotations

import math
from dataclasses import dataclass

from .base import ForecastResult, SentimentResult


@dataclass(slots=True)
class EnsembleOutlook:
    direction: str
    expected_return_pct: float
    agreement_score: float
    forecast_count: int
    sentiment_signed_score: float | None
    forecasts: list[dict]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "expected_return_pct": self.expected_return_pct,
            "agreement_score": self.agreement_score,
            "forecast_count": self.forecast_count,
            "sentiment_signed_score": self.sentiment_signed_score,
            "forecasts": self.forecasts,
            "notes": self.notes,
        }


class ExpertEnsemble:
    """Combine specialist evidence without turning it directly into an order.

    agreement_score is a bounded heuristic about model agreement, not a calibrated
    probability of profit.
    """

    DEFAULT_WEIGHTS = {
        "kronos-small": 0.60,
        "chronos-2": 0.40,
    }

    def combine(
        self,
        forecasts: list[ForecastResult],
        sentiment: SentimentResult | None = None,
        neutral_band_pct: float = 0.20,
    ) -> EnsembleOutlook:
        if not forecasts:
            return EnsembleOutlook(
                "unknown",
                0.0,
                0.0,
                0,
                sentiment.signed_score if sentiment else None,
                [],
                ["no_forecast_evidence"],
            )

        raw_weights = [
            self.DEFAULT_WEIGHTS.get(f.model, 1.0)
            for f in forecasts
        ]
        total = sum(raw_weights) or 1.0
        weights = [w / total for w in raw_weights]
        expected = sum(
            f.expected_return_pct * w
            for f, w in zip(forecasts, weights)
        )

        vals = [f.expected_return_pct for f in forecasts]
        if len(vals) == 1:
            agreement = 0.5
        else:
            mean = sum(vals) / len(vals)
            variance = sum((x - mean) ** 2 for x in vals) / len(vals)
            dispersion = math.sqrt(variance)
            scale = max(abs(mean), 0.50)
            agreement = max(0.0, min(1.0, 1.0 - dispersion / (scale + 1.0)))

        direction = (
            "bullish"
            if expected > neutral_band_pct
            else "bearish"
            if expected < -neutral_band_pct
            else "neutral"
        )
        notes = [
            "forecast_is_evidence_not_an_order",
            "agreement_score_is_not_profit_probability",
        ]
        if sentiment is not None:
            notes.append("sentiment_is_context_only")

        return EnsembleOutlook(
            direction=direction,
            expected_return_pct=round(expected, 6),
            agreement_score=round(agreement, 6),
            forecast_count=len(forecasts),
            sentiment_signed_score=(
                round(sentiment.signed_score, 6)
                if sentiment is not None
                else None
            ),
            forecasts=[f.to_dict() for f in forecasts],
            notes=notes,
        )
