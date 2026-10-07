from __future__ import annotations

from uuid import uuid4

from .adapter import CAOSAdapter
from .domain import Opportunity
from .market import OpportunityRegistry


class MarketScout:
    """Turns C.A.O.S market evidence into expiring Company opportunities."""

    def __init__(self, engine: CAOSAdapter, registry: OpportunityRegistry):
        self.engine = engine
        self.registry = registry

    @staticmethod
    def _score(regime: dict, direction: str) -> float:
        trend = float(regime.get("trend_pct", 0.0))
        vol = max(0.0, float(regime.get("volatility_pct", 0.0)))
        name = str(regime.get("regime", "unknown"))

        alignment = 0.0
        if direction == "long" and name == "trend_up":
            alignment = 25.0
        elif direction == "short" and name == "trend_down":
            alignment = 25.0
        elif name == "range":
            alignment = 8.0

        strength = min(20.0, abs(trend) * 4.0)
        volatility_penalty = min(25.0, vol * 5.0)
        return max(0.0, min(100.0, 50.0 + alignment + strength - volatility_penalty))

    def discover(
        self,
        symbol: str,
        *,
        direction: str,
        expires_at: int | None = None,
        opportunity_id: str | None = None,
        strategy_candidates: tuple[str, ...] = (),
    ) -> Opportunity:
        if direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        regime = self.engine.regime(symbol)
        opportunity = Opportunity(
            id=opportunity_id or uuid4().hex,
            symbol=symbol,
            direction=direction,
            score=self._score(regime, direction),
            regime=str(regime.get("regime", "unknown")),
            strategy_candidates=strategy_candidates,
            expires_at=expires_at,
            metadata={
                "trend_pct": float(regime.get("trend_pct", 0.0)),
                "volatility_pct": float(regime.get("volatility_pct", 0.0)),
            },
        )
        return self.registry.add(opportunity)

    def publish(self, opportunity_id: str) -> Opportunity:
        opportunity = self.registry.get(opportunity_id)
        if opportunity.status.value == "discovered":
            self.registry.validate(opportunity_id)
        return self.registry.make_available(opportunity_id)

    def discover_and_publish(self, *args, **kwargs) -> Opportunity:
        opportunity = self.discover(*args, **kwargs)
        return self.publish(opportunity.id)
