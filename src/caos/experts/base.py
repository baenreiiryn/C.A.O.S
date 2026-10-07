from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ..domain import MarketBar


class ExpertUnavailable(RuntimeError):
    """Raised when an optional specialist runtime is not installed or cannot load."""


@dataclass(slots=True)
class ForecastResult:
    model: str
    symbol: str
    horizon: int
    last_close: float
    forecast_close: float
    expected_return_pct: float
    lower_return_pct: float | None = None
    upper_return_pct: float | None = None
    path_volatility_pct: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SentimentResult:
    model: str
    label: str
    score: float
    signed_score: float
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ForecastExpert(Protocol):
    name: str

    def forecast(
        self,
        symbol: str,
        bars: list[MarketBar],
        horizon: int,
    ) -> ForecastResult: ...


class SentimentExpert(Protocol):
    name: str

    def classify(self, text: str) -> SentimentResult: ...
