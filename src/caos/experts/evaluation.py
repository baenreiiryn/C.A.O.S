from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from ..domain import MarketBar


@dataclass(slots=True)
class ExpertScorecard:
    expert: str
    symbol: str
    horizon: int
    samples: int
    direction_accuracy: float
    mae_pct: float
    naive_mae_pct: float
    mae_ratio_vs_naive: float
    mean_bias_pct: float
    qualified: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def walk_forward_evaluate(
    expert: Any,
    symbol: str,
    bars: list[MarketBar],
    horizon: int = 6,
    min_context: int = 100,
    max_windows: int = 12,
) -> ExpertScorecard:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if min_context < 20:
        raise ValueError("min_context must be >= 20")
    if len(bars) < min_context + horizon:
        raise ValueError("not_enough_bars_for_expert_evaluation")
    if max_windows < 1:
        raise ValueError("max_windows must be positive")

    available = len(bars) - min_context - horizon + 1
    stride = max(1, available // max_windows)
    starts = list(range(min_context, len(bars) - horizon + 1, stride))
    starts = starts[-max_windows:]

    direction_hits: list[float] = []
    errors: list[float] = []
    naive_errors: list[float] = []
    biases: list[float] = []

    for end in starts:
        context = bars[:end]
        actual = float(bars[end + horizon - 1].close)
        last = float(context[-1].close)
        result = expert.forecast(symbol, context, horizon)
        predicted = float(result.forecast_close)

        actual_return = (actual / last - 1.0) * 100.0
        predicted_return = (predicted / last - 1.0) * 100.0
        direction_hits.append(
            1.0
            if (
                (actual_return > 0 and predicted_return > 0)
                or (actual_return < 0 and predicted_return < 0)
                or (actual_return == 0 and predicted_return == 0)
            )
            else 0.0
        )
        errors.append(abs(predicted / actual - 1.0) * 100.0)
        naive_errors.append(abs(last / actual - 1.0) * 100.0)
        biases.append((predicted / actual - 1.0) * 100.0)

    samples = len(errors)
    direction_accuracy = mean(direction_hits) if samples else 0.0
    mae = mean(errors) if samples else 999.0
    naive = mean(naive_errors) if samples else 999.0
    ratio = mae / naive if naive > 1e-12 else 999.0
    bias = mean(biases) if samples else 0.0

    reasons: list[str] = []
    if samples < 5:
        reasons.append("too_few_windows")
    if direction_accuracy < 0.55:
        reasons.append("direction_accuracy_below_55pct")
    if ratio > 1.0:
        reasons.append("worse_than_naive_mae")
    if abs(bias) > max(1.0, mae * 1.5):
        reasons.append("large_systematic_bias")

    return ExpertScorecard(
        expert=getattr(expert, "name", expert.__class__.__name__),
        symbol=symbol.upper(),
        horizon=horizon,
        samples=samples,
        direction_accuracy=round(direction_accuracy, 6),
        mae_pct=round(mae, 6),
        naive_mae_pct=round(naive, 6),
        mae_ratio_vs_naive=round(ratio, 6),
        mean_bias_pct=round(bias, 6),
        qualified=not reasons,
        reasons=reasons,
    )
