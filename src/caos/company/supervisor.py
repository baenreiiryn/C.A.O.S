from __future__ import annotations

from dataclasses import dataclass

from .adapter import CAOSAdapter
from .capital import CapitalAllocator
from .diversity import StrategyDiversity
from .domain import CompanyPolicy, TraderStatus
from .market import MarketAllocator, OpportunityRegistry
from .registry import TraderRegistry
from .risk import CompanyRiskGovernor
from .treasury import Treasury


@dataclass(slots=True)
class CompanyAudit:
    status: str
    alerts: list[dict]
    metrics: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "alerts": list(self.alerts),
            "metrics": dict(self.metrics),
        }


class CompanySupervisor:
    def __init__(
        self,
        policy: CompanyPolicy,
        treasury: Treasury,
        registry: TraderRegistry,
        capital: CapitalAllocator,
        opportunities: OpportunityRegistry,
        market: MarketAllocator,
        risk: CompanyRiskGovernor,
        diversity: StrategyDiversity,
        engine: CAOSAdapter,
    ):
        self.policy = policy
        self.treasury = treasury
        self.registry = registry
        self.capital = capital
        self.opportunities = opportunities
        self.market = market
        self.risk = risk
        self.diversity = diversity
        self.engine = engine

    def audit(self) -> CompanyAudit:
        alerts: list[dict] = []

        if self.registry.slot_count() > self.policy.hard_max_active_traders:
            alerts.append({"kind": "hard_trader_limit_violated", "severity": "critical"})

        for trader in self.registry.traders.values():
            if trader.status == TraderStatus.RETIRED:
                continue
            balance = self.treasury.balance(trader.id)
            if balance < self.policy.trader_stop_floor:
                alerts.append(
                    {
                        "kind": "trader_stop_floor",
                        "severity": "high",
                        "trader_id": trader.id,
                        "equity": balance,
                    }
                )
            if (
                balance > 0
                and trader.status == TraderStatus.WAITING_ASSIGNMENT
            ):
                alerts.append(
                    {
                        "kind": "funded_trader_unassigned",
                        "severity": "medium",
                        "trader_id": trader.id,
                    }
                )

        diversity = self.diversity.audit()
        for warning in diversity.warnings:
            alerts.append(
                {
                    "kind": warning,
                    "severity": "medium",
                }
            )

        if self.risk.state.kill_switch:
            alerts.append({"kind": "company_kill_switch", "severity": "critical"})

        engine_health = self.engine.health()
        if engine_health.get("kill_switch"):
            alerts.append({"kind": "caos_kill_switch", "severity": "critical"})

        status = (
            "critical"
            if any(a["severity"] == "critical" for a in alerts)
            else "attention"
            if alerts
            else "healthy"
        )
        return CompanyAudit(
            status=status,
            alerts=alerts,
            metrics={
                "company_equity": self.treasury.company_equity,
                "treasury_reserve": self.treasury.reserve,
                "trader_slots": self.registry.slot_count(),
                "hard_max_traders": self.policy.hard_max_active_traders,
                "company_drawdown_pct": self.risk.drawdown_pct(),
                "opportunities": len(self.opportunities.opportunities),
                "assignments": len(self.market.assignments),
                "diversity": diversity.to_dict(),
                "caos": engine_health,
            },
        )
