from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    CompanyPolicy,
    Opportunity,
    OpportunityStatus,
    TraderMode,
    TraderStatus,
)
from .registry import TraderRegistry


class OpportunityError(RuntimeError):
    pass


class MarketAllocationError(RuntimeError):
    pass


class OpportunityRegistry:
    def __init__(self):
        self.opportunities: dict[str, Opportunity] = {}

    def add(self, opportunity: Opportunity) -> Opportunity:
        if opportunity.id in self.opportunities:
            raise OpportunityError("duplicate_opportunity")
        self.opportunities[opportunity.id] = opportunity
        return opportunity

    def get(self, opportunity_id: str) -> Opportunity:
        try:
            return self.opportunities[opportunity_id]
        except KeyError as exc:
            raise OpportunityError("unknown_opportunity") from exc

    def validate(self, opportunity_id: str) -> Opportunity:
        opportunity = self.get(opportunity_id)
        if opportunity.status != OpportunityStatus.DISCOVERED:
            raise OpportunityError("opportunity_not_discovered")
        opportunity.status = OpportunityStatus.VALIDATED
        return opportunity

    def make_available(self, opportunity_id: str) -> Opportunity:
        opportunity = self.get(opportunity_id)
        if opportunity.status not in {
            OpportunityStatus.DISCOVERED,
            OpportunityStatus.VALIDATED,
        }:
            raise OpportunityError("opportunity_not_publishable")
        opportunity.status = OpportunityStatus.AVAILABLE
        return opportunity

    def expire_due(self, now: int) -> list[str]:
        expired = []
        for opportunity in self.opportunities.values():
            if (
                opportunity.status
                not in {OpportunityStatus.ACTIVE, OpportunityStatus.EXPIRED}
                and opportunity.expired(now)
            ):
                opportunity.status = OpportunityStatus.EXPIRED
                opportunity.reserved_by = None
                expired.append(opportunity.id)
        return expired

    def available(self, *, now: int | None = None) -> list[Opportunity]:
        if now is not None:
            self.expire_due(now)
        return sorted(
            [
                opportunity
                for opportunity in self.opportunities.values()
                if opportunity.status == OpportunityStatus.AVAILABLE
                and not opportunity.expired(now)
            ],
            key=lambda x: x.score,
            reverse=True,
        )

    def snapshot(self) -> dict:
        return {
            opportunity_id: opportunity.to_dict()
            for opportunity_id, opportunity in self.opportunities.items()
        }


@dataclass(slots=True)
class MarketAssignment:
    trader_id: str
    opportunity_id: str
    symbol: str
    direction: str
    mode: TraderMode

    def to_dict(self) -> dict:
        return {
            "trader_id": self.trader_id,
            "opportunity_id": self.opportunity_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "mode": self.mode.value,
        }


class MarketAllocator:
    def __init__(
        self,
        policy: CompanyPolicy,
        registry: TraderRegistry,
        opportunities: OpportunityRegistry,
    ):
        self.policy = policy
        self.registry = registry
        self.opportunities = opportunities
        self.assignments: dict[str, MarketAssignment] = {}

    def _symbol_occupied_in_production(
        self,
        symbol: str,
        *,
        excluding_trader: str | None = None,
    ) -> bool:
        symbol = symbol.upper()
        for trader_id, assignment in self.assignments.items():
            if trader_id == excluding_trader:
                continue
            if (
                assignment.mode == TraderMode.PRODUCTION
                and assignment.symbol == symbol
            ):
                trader = self.registry.get(trader_id)
                if trader.status != TraderStatus.RETIRED:
                    return True
        return False

    def candidates_for_mode(
        self,
        mode: TraderMode,
        *,
        now: int | None = None,
    ) -> list[Opportunity]:
        result = []
        for opportunity in self.opportunities.available(now=now):
            if (
                mode == TraderMode.PRODUCTION
                and self.policy.production_market_exclusivity
                and self._symbol_occupied_in_production(opportunity.symbol)
            ):
                continue
            if (
                mode == TraderMode.TRAINING
                and not self.policy.training_market_overlap
                and any(
                    a.symbol == opportunity.symbol
                    for a in self.assignments.values()
                )
            ):
                continue
            result.append(opportunity)
        return result

    def candidates(
        self,
        trader_id: str,
        *,
        now: int | None = None,
    ) -> list[Opportunity]:
        trader = self.registry.get(trader_id)
        return self.candidates_for_mode(trader.mode, now=now)

    def peek_best_for_mode(
        self,
        mode: TraderMode,
        *,
        now: int | None = None,
    ) -> Opportunity | None:
        rows = self.candidates_for_mode(mode, now=now)
        return rows[0] if rows else None

    def peek_best(
        self,
        trader_id: str,
        *,
        now: int | None = None,
    ) -> Opportunity | None:
        rows = self.candidates(trader_id, now=now)
        return rows[0] if rows else None

    def assign(
        self,
        trader_id: str,
        opportunity_id: str,
        *,
        strategy_id: str | None = None,
        now: int | None = None,
    ) -> MarketAssignment:
        trader = self.registry.get(trader_id)
        opportunity = self.opportunities.get(opportunity_id)
        if opportunity.expired(now):
            opportunity.status = OpportunityStatus.EXPIRED
            raise MarketAllocationError("opportunity_expired")
        if opportunity.status != OpportunityStatus.AVAILABLE:
            raise MarketAllocationError("opportunity_not_available")
        if (
            trader.mode == TraderMode.PRODUCTION
            and self.policy.production_market_exclusivity
            and self._symbol_occupied_in_production(
                opportunity.symbol,
                excluding_trader=trader_id,
            )
        ):
            raise MarketAllocationError("production_symbol_occupied")
        if (
            trader.mode == TraderMode.TRAINING
            and not self.policy.training_market_overlap
            and any(
                a.symbol == opportunity.symbol and a.trader_id != trader_id
                for a in self.assignments.values()
            )
        ):
            raise MarketAllocationError("training_symbol_occupied")

        self.release(trader_id)
        self.registry.assign(
            trader_id,
            symbol=opportunity.symbol,
            direction=opportunity.direction,
            strategy_id=strategy_id,
        )
        assignment = MarketAssignment(
            trader_id=trader_id,
            opportunity_id=opportunity.id,
            symbol=opportunity.symbol,
            direction=opportunity.direction,
            mode=trader.mode,
        )
        self.assignments[trader_id] = assignment

        if trader.mode == TraderMode.PRODUCTION:
            opportunity.status = OpportunityStatus.ACTIVE
            opportunity.reserved_by = trader_id
        return assignment

    def assign_best(
        self,
        trader_id: str,
        *,
        strategy_id: str | None = None,
        now: int | None = None,
    ) -> MarketAssignment:
        opportunity = self.peek_best(trader_id, now=now)
        if opportunity is None:
            raise MarketAllocationError("no_available_opportunity")
        return self.assign(
            trader_id,
            opportunity.id,
            strategy_id=strategy_id,
            now=now,
        )

    def release(self, trader_id: str) -> MarketAssignment | None:
        assignment = self.assignments.pop(trader_id, None)
        if assignment is None:
            return None
        opportunity = self.opportunities.get(assignment.opportunity_id)
        if (
            assignment.mode == TraderMode.PRODUCTION
            and opportunity.reserved_by == trader_id
        ):
            opportunity.reserved_by = None
            if opportunity.status != OpportunityStatus.EXPIRED:
                opportunity.status = OpportunityStatus.AVAILABLE
        trader = self.registry.get(trader_id)
        trader.market = None
        trader.direction = None
        trader.strategy_id = None
        if trader.status == TraderStatus.ACTIVE:
            trader.status = TraderStatus.WAITING_ASSIGNMENT
        return assignment

    def snapshot(self) -> dict:
        return {
            trader_id: assignment.to_dict()
            for trader_id, assignment in self.assignments.items()
        }
