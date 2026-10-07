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
    """Moves Company-owned capital between Treasury and Trader buckets.

    Trader count is constrained only by the configurable operational safety cap,
    while funding is constrained by Treasury capital.
    """

    def __init__(
        self,
        policy: CompanyPolicy,
        treasury: Treasury,
        registry: TraderRegistry,
    ):
        self.policy = policy
        self.treasury = treasury
        self.registry = registry

    def _check_operational_capacity(self) -> None:
        if self.registry.slot_count() >= self.policy.operational_trader_cap:
            raise CapitalAllocationError("operational_trader_cap")

    def treasury_can_fund_new_trader(self) -> bool:
        return (
            self.treasury.reserve + 1e-9
            >= self.policy.trader_initial_bucket
        )

    def bootstrap_first_trader(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
        max_trade_exposure_pct: float | None = None,
        trade_exposure_pct: float | None = None,
    ) -> Trader:
        if self.registry.slot_count() != 0:
            raise CapitalAllocationError("company_already_bootstrapped")
        self._check_operational_capacity()
        trader = self.registry.create(
            mode=mode,
            max_trade_exposure_pct=(
                self.policy.default_trader_max_exposure_pct
                if max_trade_exposure_pct is None
                else max_trade_exposure_pct
            ),
            trade_exposure_pct=trade_exposure_pct,
        )
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
        """Whether Company capital can be assembled for one new Trader.

        Treasury is the preferred funding source. If Treasury is short, only the
        amount above the trigger Trader's minimum operating bucket may be
        harvested to complete the new Trader's initial allocation.
        """
        trader = self.registry.get(trader_id)
        if trader.status not in {TraderStatus.ACTIVE, TraderStatus.PAUSED}:
            return ExpansionDecision(
                False,
                "trigger_trader_not_operational",
                trader_id,
            )
        if self.registry.slot_count() >= self.policy.operational_trader_cap:
            return ExpansionDecision(
                False,
                "operational_trader_cap",
                trader_id,
            )

        required = self.policy.trader_initial_bucket
        treasury_available = self.treasury.reserve
        needed_from_trigger = max(0.0, required - treasury_available)

        trader_equity = self.treasury.balance(trader_id)
        releasable = max(
            0.0,
            trader_equity - self.policy.trader_initial_bucket,
        )
        if releasable + 1e-9 < needed_from_trigger:
            return ExpansionDecision(
                False,
                "insufficient_company_growth_capital",
                trader_id,
            )

        return ExpansionDecision(
            True,
            "eligible",
            trader_id,
            released_capital=needed_from_trigger,
        )

    def release_expansion_capital(self, trader_id: str) -> float:
        decision = self.can_expand_from(trader_id)
        if not decision.allowed:
            raise CapitalAllocationError(decision.reason)
        amount = float(decision.released_capital)
        if amount > 1e-9:
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
        max_trade_exposure_pct: float | None = None,
        trade_exposure_pct: float | None = None,
        note: str = "fund_new_trader",
    ) -> Trader:
        self._check_operational_capacity()
        if not self.treasury_can_fund_new_trader():
            raise CapitalAllocationError("insufficient_treasury_reserve")
        trader = self.registry.create(
            mode=mode,
            spawned_from=spawned_from,
            max_trade_exposure_pct=(
                self.policy.default_trader_max_exposure_pct
                if max_trade_exposure_pct is None
                else max_trade_exposure_pct
            ),
            trade_exposure_pct=trade_exposure_pct,
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
            raise CapitalAllocationError(
                "positions_must_be_flat_before_settlement"
            )
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
        return (
            self.treasury.balance(trader_id)
            < self.policy.trader_stop_floor
        )

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
