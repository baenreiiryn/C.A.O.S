from __future__ import annotations

from dataclasses import asdict, dataclass

from .domain import BacktestResult, StrategySpec
from .quant import RobustnessResult


@dataclass(slots=True)
class PortfolioEntry:
    symbol: str
    strategy: StrategySpec
    score: float
    weight: float
    expected: BacktestResult
    robustness: RobustnessResult

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": asdict(self.strategy),
            "score": self.score,
            "weight": self.weight,
            "expected": self.expected.to_dict(),
            "robustness": asdict(self.robustness),
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
) -> list[PortfolioEntry]:
    ranked = []
    for symbol, rows in candidates.items():
        for spec, bt, rb in rows:
            if not rb.passed:
                continue
            ranked.append((strategy_score(bt, rb), symbol, spec, bt, rb))
    ranked.sort(key=lambda x: x[0], reverse=True)
    selected = []
    used_symbols: set[str] = set()
    for score, symbol, spec, bt, rb in ranked:
        if one_per_symbol and symbol in used_symbols:
            continue
        selected.append((score, symbol, spec, bt, rb))
        used_symbols.add(symbol)
        if len(selected) >= max_entries:
            break
    total = sum(x[0] for x in selected) or 1.0
    return [
        PortfolioEntry(symbol, spec, score, score / total, bt, rb)
        for score, symbol, spec, bt, rb in selected
    ]
