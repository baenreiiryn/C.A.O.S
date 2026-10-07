from __future__ import annotations

from typing import Any

from ..domain import MarketBar
from .base import ExpertUnavailable, ForecastResult


class Chronos2Expert:
    """General time-series foundation-model baseline using amazon/chronos-2."""

    name = "chronos-2"

    def __init__(
        self,
        model_id: str = "amazon/chronos-2",
        device_map: str = "cuda",
        pipeline: Any | None = None,
    ):
        self.model_id = model_id
        self.device_map = device_map
        self._pipeline = pipeline

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from chronos import Chronos2Pipeline
        except ImportError as exc:
            raise ExpertUnavailable(
                "Chronos-2 requires optional chronos dependencies: "
                "pip install -e .[chronos]"
            ) from exc
        self._pipeline = Chronos2Pipeline.from_pretrained(
            self.model_id,
            device_map=self.device_map,
        )
        return self._pipeline

    @staticmethod
    def _frame(bars: list[MarketBar]):
        try:
            import pandas as pd
        except ImportError as exc:
            raise ExpertUnavailable(
                "Chronos-2 requires pandas; install optional chronos dependencies."
            ) from exc
        values = [b.ts for b in bars]
        unit = "ms" if max(values) > 10_000_000_000 else "s"
        ts = pd.to_datetime(values, unit=unit, utc=True).tz_convert(None)
        return pd.DataFrame(
            {
                "item_id": ["series"] * len(bars),
                "timestamp": ts,
                "target": [float(b.close) for b in bars],
            }
        )

    @staticmethod
    def _quantile_value(row, q: float) -> float | None:
        candidates = [
            str(q),
            f"{q:.1f}",
            f"quantile_{q}",
            f"quantile_{q:.1f}",
            f"target_{q}",
            f"target_{q:.1f}",
        ]
        for key in candidates:
            if key in row.index:
                return float(row[key])
        qtxt = str(q)
        for key in row.index:
            if qtxt in str(key):
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    continue
        return None

    def forecast(
        self,
        symbol: str,
        bars: list[MarketBar],
        horizon: int,
    ) -> ForecastResult:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        if len(bars) < 20:
            raise ValueError("at least 20 bars are required")

        frame = self._frame(bars)
        pred = self._load().predict_df(
            frame,
            prediction_length=horizon,
            quantile_levels=[0.1, 0.5, 0.9],
            id_column="item_id",
            timestamp_column="timestamp",
            target="target",
        )
        last_row = pred.iloc[-1]
        q50 = self._quantile_value(last_row, 0.5)
        q10 = self._quantile_value(last_row, 0.1)
        q90 = self._quantile_value(last_row, 0.9)
        if q50 is None:
            for fallback in ("mean", "prediction", "target"):
                if fallback in last_row.index:
                    q50 = float(last_row[fallback])
                    break
        if q50 is None:
            raise ExpertUnavailable(
                "Chronos-2 output did not expose a median/mean forecast column."
            )

        last = float(bars[-1].close)
        expected = (q50 / last - 1.0) * 100.0
        lower = (q10 / last - 1.0) * 100.0 if q10 is not None else None
        upper = (q90 / last - 1.0) * 100.0 if q90 is not None else None
        return ForecastResult(
            model=self.name,
            symbol=symbol.upper(),
            horizon=horizon,
            last_close=last,
            forecast_close=q50,
            expected_return_pct=expected,
            lower_return_pct=lower,
            upper_return_pct=upper,
            metadata={
                "model_id": self.model_id,
                "quantiles": [0.1, 0.5, 0.9],
                "probabilistic_bounds": q10 is not None and q90 is not None,
            },
        )
