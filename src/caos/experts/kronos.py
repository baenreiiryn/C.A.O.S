from __future__ import annotations

import os
import statistics
import sys
from typing import Any

from ..domain import MarketBar
from .base import ExpertUnavailable, ForecastResult


class KronosExpert:
    """Adapter for the open-source Kronos financial K-line foundation model.

    C.A.O.S does not vendor Kronos source code. Set CAOS_KRONOS_PATH to a local clone
    of https://github.com/shiyu-coder/Kronos or otherwise make its "model" package
    importable. Weights are loaded from Hugging Face.
    """

    name = "kronos-small"

    def __init__(
        self,
        model_id: str = "NeoQuasar/Kronos-small",
        tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-base",
        device: str | None = None,
        max_context: int = 512,
        sample_count: int = 3,
        predictor: Any | None = None,
    ):
        self.model_id = model_id
        self.tokenizer_id = tokenizer_id
        self.device = device
        self.max_context = max_context
        self.sample_count = sample_count
        self._predictor = predictor

    def _load(self):
        if self._predictor is not None:
            return self._predictor

        path = os.getenv("CAOS_KRONOS_PATH")
        if path and path not in sys.path:
            sys.path.insert(0, path)
        try:
            from model import Kronos, KronosPredictor, KronosTokenizer
        except ImportError as exc:
            raise ExpertUnavailable(
                "Kronos runtime not found. Clone shiyu-coder/Kronos and set "
                "CAOS_KRONOS_PATH to that directory, then install the optional "
                "kronos-runtime dependencies."
            ) from exc

        tokenizer = KronosTokenizer.from_pretrained(self.tokenizer_id)
        model = Kronos.from_pretrained(self.model_id)
        if hasattr(tokenizer, "eval"):
            tokenizer.eval()
        if hasattr(model, "eval"):
            model.eval()

        kwargs = {"max_context": self.max_context}
        if self.device:
            kwargs["device"] = self.device
        self._predictor = KronosPredictor(model, tokenizer, **kwargs)
        return self._predictor

    @staticmethod
    def _timestamp_parts(bars: list[MarketBar], horizon: int):
        try:
            import pandas as pd
        except ImportError as exc:
            raise ExpertUnavailable(
                "Kronos requires pandas; install optional kronos-runtime dependencies."
            ) from exc

        values = [b.ts for b in bars]
        unit = "ms" if max(values) > 10_000_000_000 else "s"
        x_ts = pd.to_datetime(values, unit=unit, utc=True).tz_convert(None)
        if len(x_ts) >= 2:
            step = x_ts[-1] - x_ts[-2]
        else:
            step = pd.Timedelta(hours=1)
        if step <= pd.Timedelta(0):
            step = pd.Timedelta(hours=1)
        y_ts = pd.DatetimeIndex(
            [x_ts[-1] + step * (i + 1) for i in range(horizon)]
        )
        return pd.Series(x_ts), pd.Series(y_ts)

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

        try:
            import pandas as pd
        except ImportError as exc:
            raise ExpertUnavailable(
                "Kronos requires pandas; install optional kronos-runtime dependencies."
            ) from exc

        context = bars[-self.max_context :]
        x_ts, y_ts = self._timestamp_parts(context, horizon)
        frame = pd.DataFrame(
            {
                "open": [b.open for b in context],
                "high": [b.high for b in context],
                "low": [b.low for b in context],
                "close": [b.close for b in context],
                "volume": [b.volume for b in context],
            }
        )
        predictor = self._load()
        pred = predictor.predict(
            df=frame,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=self.sample_count,
            verbose=False,
        )
        closes = [float(v) for v in pred["close"].tolist()]
        last = float(context[-1].close)
        forecast_close = closes[-1]
        expected = (forecast_close / last - 1.0) * 100.0
        returns = [
            (closes[i] / closes[i - 1] - 1.0) * 100.0
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        path_vol = statistics.pstdev(returns) if len(returns) >= 2 else 0.0
        return ForecastResult(
            model=self.name,
            symbol=symbol.upper(),
            horizon=horizon,
            last_close=last,
            forecast_close=forecast_close,
            expected_return_pct=expected,
            path_volatility_pct=path_vol,
            metadata={
                "model_id": self.model_id,
                "tokenizer_id": self.tokenizer_id,
                "sample_count": self.sample_count,
                "probabilistic_bounds": False,
            },
        )
