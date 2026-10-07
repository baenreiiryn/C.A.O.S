from __future__ import annotations

from typing import Any

from ..domain import StrategySpec
from ..orchestrator import CAOS
from ..quant import current_signal


class CAOSAdapter:
    """Stable Company-facing port over the C.A.O.S engine.

    The Company consumes capabilities, not C.A.O.S internals. This is also the
    seam a future Drizzt adapter can call through without broker access.
    """

    def __init__(self, caos: CAOS):
        self.caos = caos

    @property
    def store(self):
        return self.caos.store

    def health(self) -> dict:
        status = self.caos.status()
        return {
            "ok": True,
            "orchestrator": status["orchestrator"],
            "kill_switch": status["kill_switch"],
            "symbols_loaded": status["symbols_loaded"],
            "experts": status["experts"],
        }

    def load_bars(self, symbol: str, bars: list[Any]) -> None:
        self.caos.load_bars(symbol, bars)

    def fetch_market(
        self,
        symbol: str,
        *,
        interval: str = "60",
        limit: int = 500,
        category: str = "linear",
    ) -> dict:
        return self.caos.tool_fetch_market(
            symbol,
            interval=interval,
            limit=limit,
            category=category,
        )

    def bars(self, symbol: str) -> list[Any]:
        return list(self.caos.market_data.get(symbol.upper(), []))

    def regime(self, symbol: str) -> dict:
        return self.caos.tool_market_regime(symbol)

    def current_signal(
        self,
        strategy: StrategySpec,
        symbol: str,
    ) -> str:
        bars = self.bars(symbol)
        if not bars:
            raise RuntimeError("market_data_required")
        return current_signal(strategy, bars)

    def execution_cost_bps(self, symbol: str) -> float:
        return float(self.caos.execution_costs.get(symbol.upper(), 0.0))

    def estimate_cost(
        self,
        symbol: str,
        *,
        side: str = "buy",
        notional: float = 100.0,
        fee_bps: float = 5.0,
        depth: int = 50,
        category: str = "linear",
    ) -> dict:
        return self.caos.tool_estimate_cost(
            symbol,
            side=side,
            notional=notional,
            fee_bps=fee_bps,
            depth=depth,
            category=category,
        )

    def forecast(
        self,
        symbol: str,
        *,
        expert: str = "kronos",
        horizon: int = 12,
    ) -> dict:
        return self.caos.tool_forecast(
            symbol,
            expert=expert,
            horizon=horizon,
        )

    def forecast_ensemble(
        self,
        symbol: str,
        *,
        horizon: int = 12,
        experts: list[str] | None = None,
        news_text: str | None = None,
    ) -> dict:
        return self.caos.tool_forecast_ensemble(
            symbol,
            horizon=horizon,
            experts=experts,
            news_text=news_text,
        )

    def supervisor_audit(self) -> dict:
        return self.caos.tool_supervisor_audit()

    def emergency_kill(self) -> dict:
        return self.caos.tool_kill()
