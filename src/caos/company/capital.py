from __future__ import annotations

from dataclasses import dataclass

from .domain import CompanyPolicy, Trader, TraderMode, TraderStatus
from .registry import TraderRegistry
from .treasury import Treasury


class CapitalAllocationError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ExpansionDecision:
    allowed: bool
    reason: str
    trigger_trader_id: str
    released_capital: float = 0.0
    new_trader_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "trigger_trader_id": self.trigger_trader_id,
            "released_capital": self.released_capital,
            "new_trader_id": self.new_trader_id,
        }


class CapitalAllocator:
    def __init__(
        self,
        policy: CompanyPolicy,
        treasury: Treasury,
        registry: TraderRegistry,
    ):
        self.policy = policy
        self.treasury = treasury
        self.registry = registry

    def _check_slot(self) -> None:
        if self.registry.slot_count() >= self.policy.hard_max_active_traders:
            raise CapitalAllocationError("hard_trader_limit")

    def bootstrap_first_trader(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
    ) -> Trader:
        if self.registry.slot_count() != 0:
            raise CapitalAllocationError("company_already_bootstrapped")
        self._check_slot()
        trader = self.registry.create(mode=mode)
        try:
            self.treasury.allocate(
                trader.id,
                self.policy.trader_initial_bucket,
                note="bootstrap_first_trader",
            )
        except Exception:
            self.registry.halt(trader.id)
            self.registry.retire(trader.id)
            raise
        return trader

    def can_expand_from(self, trader_id: str) -> ExpansionDecision:
        trader = self.registry.get(trader_id)
        if trader.status not in {TraderStatus.ACTIVE, TraderStatus.PAUSED}:
            return ExpansionDecision(False, "trigger_trader_not_operational", trader_id)
        if self.registry.slot_count() >= self.policy.hard_max_active_traders:
            return ExpansionDecision(False, "hard_trader_limit", trader_id)
        equity = self.treasury.balance(trader_id)
        if equity + 1e-9 < self.policy.spawn_threshold:
            return ExpansionDecision(False, "spawn_threshold_not_reached", trader_id)
        releasable = equity - self.policy.trader_initial_bucket
        if releasable + 1e-9 < self.policy.trader_initial_bucket:
            return ExpansionDecision(False, "insufficient_releasable_growth", trader_id)
        return ExpansionDecision(
            True,
            "eligible",
            trader_id,
            released_capital=self.policy.trader_initial_bucket,
        )

    def release_expansion_capital(self, trader_id: str) -> float:
        decision = self.can_expand_from(trader_id)
        if not decision.allowed:
            raise CapitalAllocationError(decision.reason)
        amount = self.policy.trader_initial_bucket
        self.treasury.harvest(
            trader_id,
            amount,
            note="release_expansion_capital",
        )
        return amount

    def create_funded_trader(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
        spawned_from: str | None = None,
        note: str = "fund_new_trader",
    ) -> Trader:
        self._check_slot()
        if self.treasury.reserve + 1e-9 < self.policy.trader_initial_bucket:
            raise CapitalAllocationError("insufficient_treasury_reserve")
        trader = self.registry.create(
            mode=mode,
            spawned_from=spawned_from,
        )
        try:
            self.treasury.allocate(
                trader.id,
                self.policy.trader_initial_bucket,
                note=note,
            )
        except Exception:
            self.registry.halt(trader.id)
            self.registry.retire(trader.id)
            raise
        return trader

    def settle_retired_trader(
        self,
        trader_id: str,
        *,
        positions_flat: bool,
        reason: str = "retired",
    ) -> float:
        trader = self.registry.get(trader_id)
        if not positions_flat:
            if trader.status != TraderStatus.RETIRED:
                self.registry.halt(trader_id)
            raise CapitalAllocationError("positions_must_be_flat_before_settlement")
        if trader.status == TraderStatus.ACTIVE:
            self.registry.halt(trader_id)
        if trader.status != TraderStatus.RETIRED:
            if trader.status not in {
                TraderStatus.HALTED,
                TraderStatus.WAITING_ASSIGNMENT,
                TraderStatus.PAUSED,
                TraderStatus.EVALUATING,
            }:
                self.registry.halt(trader_id)
            self.registry.retire(trader_id)
        return self.treasury.harvest_all(
            trader_id,
            note=f"settlement:{reason}",
        )

    def stop_floor_breached(self, trader_id: str) -> bool:
        trader = self.registry.get(trader_id)
        if trader.status == TraderStatus.RETIRED:
            return False
        return self.treasury.balance(trader_id) < self.policy.trader_stop_floor

    def apply_stop_floor(
        self,
        trader_id: str,
        *,
        positions_flat: bool,
    ) -> float | None:
        if not self.stop_floor_breached(trader_id):
            return None
        self.registry.halt(trader_id)
        return self.settle_retired_trader(
            trader_id,
            positions_flat=positions_flat,
            reason="stop_floor",
        )
