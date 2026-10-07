from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from ..domain import Mandate, MarketBar, StrategySpec
from ..quant import backtest, robustness


@dataclass(slots=True, frozen=True)
class TrainingVariant:
    name: str
    strategy: StrategySpec

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strategy": asdict(self.strategy),
        }


@dataclass(slots=True)
class TrainingExperiment:
    id: str
    symbol: str
    starting_capital: float
    cost_bps: float
    results: list[dict]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "starting_capital": self.starting_capital,
            "cost_bps": self.cost_bps,
            "results": list(self.results),
        }


class TrainingArena:
    """Fair same-market/same-period strategy comparison.

    This deliberately uses the deterministic C.A.O.S backtest stack. Specialist
    model filters will be added only after their real benchmark is qualified.
    """

    def __init__(self):
        self.experiments: dict[str, TrainingExperiment] = {}

    def run(
        self,
        symbol: str,
        bars: list[MarketBar],
        variants: list[TrainingVariant],
        *,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
        max_drawdown_pct: float = 30.0,
        max_position_pct: float = 20.0,
    ) -> TrainingExperiment:
        if not variants:
            raise ValueError("at least one training variant is required")
        mandate = Mandate(
            starting_capital,
            max_drawdown_pct,
            max_position_pct=max_position_pct,
        )
        rows = []
        for variant in variants:
            bt = backtest(variant.strategy, bars, cost_bps=cost_bps)
            rb = robustness(
                variant.strategy,
                bars,
                mandate,
                cost_bps=cost_bps,
            )
            rows.append(
                {
                    "variant": variant.name,
                    "strategy": asdict(variant.strategy),
                    "backtest": bt.to_dict(),
                    "robustness": asdict(rb),
                }
            )
        rows.sort(
            key=lambda row: (
                bool(row["robustness"]["passed"]),
                float(row["backtest"]["profit_factor"]),
                -float(row["backtest"]["max_drawdown_pct"]),
                float(row["backtest"]["pnl_pct"]),
            ),
            reverse=True,
        )
        experiment = TrainingExperiment(
            id=uuid4().hex,
            symbol=symbol.upper(),
            starting_capital=float(starting_capital),
            cost_bps=float(cost_bps),
            results=rows,
        )
        self.experiments[experiment.id] = experiment
        return experiment

    def snapshot(self) -> dict:
        return {
            experiment_id: experiment.to_dict()
            for experiment_id, experiment in self.experiments.items()
        }
