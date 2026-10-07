from __future__ import annotations

from dataclasses import asdict, dataclass

from .domain import BacktestResult, MarketBar, StrategySpec
from .quant import (
    RobustnessResult,
    pearson_correlation,
    strategy_return_series,
)


@dataclass(slots=True)
class PortfolioEntry:
    symbol: str
    strategy: StrategySpec
    score: float
    weight: float
    expected: BacktestResult
    robustness: RobustnessResult
    max_abs_correlation: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": asdict(self.strategy),
            "score": self.score,
            "weight": self.weight,
            "expected": self.expected.to_dict(),
            "robustness": asdict(self.robustness),
            "max_abs_correlation": self.max_abs_correlation,
        }


def strategy_score(bt: BacktestResult, rb: RobustnessResult) -> float:
    pf = min(bt.profit_factor, 4.0)
    dd_penalty = 1.0 / (1.0 + bt.max_drawdown_pct / 10.0)
    activity = min(1.0, bt.trades / 20.0)
    robustness_bonus = 0.5 + 0.5 * rb.walk_forward_positive_ratio
    return max(0.0, pf * dd_penalty * activity * robustness_bonus)


def build_portfolio(
    candidates: dict[
        str,
        list[tuple[StrategySpec, BacktestResult, RobustnessResult]],
    ],
    max_entries: int = 6,
    one_per_symbol: bool = True,
    market_data: dict[str, list[MarketBar]] | None = None,
    max_correlation: float = 0.85,
    cost_bps: float = 8.0,
) -> list[PortfolioEntry]:
    if not 0 <= max_correlation <= 1:
        raise ValueError("max_correlation must be between 0 and 1")

    ranked = []
    for symbol, rows in candidates.items():
        for spec, bt, rb in rows:
            if not rb.passed:
                continue
            ranked.append((strategy_score(bt, rb), symbol, spec, bt, rb))
    ranked.sort(key=lambda x: x[0], reverse=True)

    selected: list[
        tuple[float, str, StrategySpec, BacktestResult, RobustnessResult, float]
    ] = []
    selected_series: list[list[float]] = []
    used_symbols: set[str] = set()

    for score, symbol, spec, bt, rb in ranked:
        if one_per_symbol and symbol in used_symbols:
            continue

        candidate_series: list[float] | None = None
        candidate_max_corr = 0.0
        if market_data and symbol in market_data:
            candidate_series = strategy_return_series(
                spec,
                market_data[symbol],
                cost_bps=cost_bps,
            )
            correlations = [
                abs(pearson_correlation(candidate_series, other))
                for other in selected_series
            ]
            candidate_max_corr = max(correlations, default=0.0)
            if candidate_max_corr > max_correlation:
                continue

        selected.append(
            (score, symbol, spec, bt, rb, candidate_max_corr)
        )
        if candidate_series is not None:
            selected_series.append(candidate_series)
        else:
            selected_series.append([])
        used_symbols.add(symbol)

        if len(selected) >= max_entries:
            break

    total = sum(x[0] for x in selected) or 1.0
    return [
        PortfolioEntry(
            symbol=symbol,
            strategy=spec,
            score=score,
            weight=score / total,
            expected=bt,
            robustness=rb,
            max_abs_correlation=corr,
        )
        for score, symbol, spec, bt, rb, corr in selected
    ]
