from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True, frozen=True)
class ModelInfo:
    key: str
    model_id: str
    role: str
    parameters_millions: float
    license: str
    priority: str
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


MODEL_CATALOG = {
    "kronos": ModelInfo(
        key="kronos",
        model_id="NeoQuasar/Kronos-small",
        role="financial_ohlcv_forecast",
        parameters_millions=24.7,
        license="MIT",
        priority="primary",
        rationale=(
            "Finance-specific K-line foundation model trained across 45+ exchanges; "
            "small enough to run cheaply and suitable as a forecast feature."
        ),
    ),
    "chronos2": ModelInfo(
        key="chronos2",
        model_id="amazon/chronos-2",
        role="general_timeseries_forecast",
        parameters_millions=120.0,
        license="Apache-2.0",
        priority="baseline",
        rationale=(
            "Strong general zero-shot time-series model with probabilistic quantiles; "
            "useful as an independent baseline against finance-specific forecasts."
        ),
    ),
    "finbert": ModelInfo(
        key="finbert",
        model_id="neoyipeng/ModernFinBERT-base",
        role="financial_news_sentiment",
        parameters_millions=149.0,
        license="Apache-2.0",
        priority="context",
        rationale=(
            "Small financial text classifier for NEWS context; sentiment is never "
            "allowed to bypass quantitative validation or risk controls."
        ),
    ),
}


def recommended_stack() -> list[dict]:
    return [
        MODEL_CATALOG["kronos"].to_dict(),
        MODEL_CATALOG["chronos2"].to_dict(),
        MODEL_CATALOG["finbert"].to_dict(),
    ]


def build_experts(
    names: list[str] | tuple[str, ...],
) -> tuple[dict[str, Any], Any | None]:
    forecasts: dict[str, Any] = {}
    sentiment = None
    normalized = {name.strip().lower() for name in names if name.strip()}

    if "kronos" in normalized:
        from .kronos import KronosExpert

        forecasts["kronos"] = KronosExpert()
    if "chronos2" in normalized or "chronos-2" in normalized:
        from .chronos import Chronos2Expert

        forecasts["chronos2"] = Chronos2Expert()
    if "finbert" in normalized or "modernfinbert" in normalized:
        from .sentiment import ModernFinBERTExpert

        sentiment = ModernFinBERTExpert()

    return forecasts, sentiment
