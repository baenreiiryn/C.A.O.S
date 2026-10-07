from __future__ import annotations

from .domain import BacktestResult, Fill, Mandate, Position, StrategySpec, Trade
from .portfolio import PortfolioEntry
from .quant import RobustnessResult


def _backtest_from_dict(data: dict) -> BacktestResult:
    return BacktestResult(
        strategy=data["strategy"],
        trades=int(data["trades"]),
        pnl_pct=float(data["pnl_pct"]),
        win_rate_pct=float(data["win_rate_pct"]),
        profit_factor=float(data["profit_factor"]),
        max_drawdown_pct=float(data["max_drawdown_pct"]),
        expectancy_pct=float(data["expectancy_pct"]),
        equity_curve=[float(x) for x in data.get("equity_curve", [])],
        trade_log=[Trade(**row) for row in data.get("trade_log", [])],
    )


def _portfolio_entry_from_dict(data: dict) -> PortfolioEntry:
    robustness = data["robustness"]
    return PortfolioEntry(
        symbol=data["symbol"],
        strategy=StrategySpec(**data["strategy"]),
        score=float(data["score"]),
        weight=float(data["weight"]),
        expected=_backtest_from_dict(data["expected"]),
        robustness=RobustnessResult(
            passed=bool(robustness["passed"]),
            walk_forward_positive_ratio=float(
                robustness["walk_forward_positive_ratio"]
            ),
            monte_carlo_p05_pct=float(robustness["monte_carlo_p05_pct"]),
            stressed_profit_factor=float(robustness["stressed_profit_factor"]),
            reasons=list(robustness.get("reasons", [])),
        ),
        max_abs_correlation=float(data.get("max_abs_correlation", 0.0)),
    )


class RuntimeCheckpoint:
    KEY = "runtime_checkpoint_v1"

    @classmethod
    def save(cls, caos, store) -> dict:
        paper = caos.paper.snapshot() if caos.paper is not None else None
        payload = {
            "mandate": caos.mandate.to_dict() if caos.mandate else None,
            "portfolio": [entry.to_dict() for entry in caos.portfolio],
            "paper": paper,
            "risk": (
                {
                    "kill_switch": caos.risk.state.kill_switch,
                    "day_start_equity": caos.risk.state.day_start_equity,
                    "current_equity": caos.risk.state.current_equity,
                }
                if caos.risk is not None
                else None
            ),
            "execution_costs": dict(caos.execution_costs),
        }
        store.set_json(cls.KEY, payload)
        store.event(
            "checkpoint",
            {
                "portfolio_entries": len(payload["portfolio"]),
                "has_paper": paper is not None,
            },
        )
        return payload

    @classmethod
    def restore(cls, caos, store) -> bool:
        payload = store.get_json(cls.KEY)
        if not payload or not payload.get("mandate"):
            return False

        caos.set_mandate(Mandate(**payload["mandate"]))
        caos.portfolio = [
            _portfolio_entry_from_dict(row)
            for row in payload.get("portfolio", [])
        ]
        caos.execution_costs = {
            str(k): float(v)
            for k, v in payload.get("execution_costs", {}).items()
        }

        if caos.paper is not None and payload.get("paper"):
            paper = payload["paper"]
            caos.paper.cash = float(paper.get("cash", caos.paper.cash))
            caos.paper.positions = {
                symbol: Position(**data)
                for symbol, data in paper.get("positions", {}).items()
            }
            caos.paper.fills = [
                Fill(**row)
                for row in paper.get("fills", [])
            ]

        if caos.risk is not None and payload.get("risk"):
            risk = payload["risk"]
            caos.risk.state.kill_switch = bool(risk.get("kill_switch", False))
            caos.risk.state.day_start_equity = float(
                risk.get("day_start_equity", caos.risk.state.day_start_equity)
            )
            caos.risk.state.current_equity = float(
                risk.get("current_equity", caos.risk.state.current_equity)
            )

        store.event(
            "restore",
            {
                "portfolio_entries": len(caos.portfolio),
                "kill_switch": (
                    caos.risk.state.kill_switch
                    if caos.risk is not None
                    else None
                ),
            },
        )
        return True
