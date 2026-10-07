from __future__ import annotations

from dataclasses import asdict

from .adapter import CAOSAdapter
from .capital import CapitalAllocator, ExpansionDecision
from .diversity import StrategyDiversity
from .domain import (
    CompanyPolicy,
    Opportunity,
    TraderMode,
    TraderStatus,
)
from .improvement import ImprovementManager
from .market import MarketAllocator, MarketAllocationError, OpportunityRegistry
from .registry import TraderRegistry
from .risk import CompanyRiskGovernor
from .scout import MarketScout
from .supervisor import CompanySupervisor
from .training import TrainingArena
from .treasury import Treasury


class TradeCompanyError(RuntimeError):
    pass


class TradeCompany:
    """Standalone Company layer backed by one shared C.A.O.S engine."""

    def __init__(
        self,
        engine: CAOSAdapter,
        policy: CompanyPolicy | None = None,
    ):
        self.engine = engine
        self.policy = policy or CompanyPolicy()
        self.effective_trader_limit = self.policy.hard_max_active_traders

        self.treasury = Treasury(self.policy.initial_company_capital)
        self.registry = TraderRegistry()
        self.opportunities = OpportunityRegistry()
        self.capital = CapitalAllocator(
            self.policy,
            self.treasury,
            self.registry,
        )
        self.market = MarketAllocator(
            self.policy,
            self.registry,
            self.opportunities,
        )
        self.risk = CompanyRiskGovernor(
            self.policy,
            self.treasury,
            self.registry,
            self.market,
        )
        self.diversity = StrategyDiversity(self.registry)
        self.scout = MarketScout(self.engine, self.opportunities)
        self.training = TrainingArena()
        self.supervisor = CompanySupervisor(
            self.policy,
            self.treasury,
            self.registry,
            self.capital,
            self.opportunities,
            self.market,
            self.risk,
            self.diversity,
            self.engine,
        )
        self.improvement = ImprovementManager()

    def set_effective_trader_limit(self, limit: int) -> int:
        if not 1 <= int(limit) <= self.policy.hard_max_active_traders:
            raise TradeCompanyError("effective_limit_outside_user_policy")
        if int(limit) < self.registry.slot_count():
            raise TradeCompanyError("effective_limit_below_current_slots")
        self.effective_trader_limit = int(limit)
        return self.effective_trader_limit

    def bootstrap(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
        assign_best: bool = False,
        now: int | None = None,
    ):
        trader = self.capital.bootstrap_first_trader(mode=mode)
        if assign_best:
            self.market.assign_best(trader.id, now=now)
        return trader

    def publish_opportunity(self, opportunity: Opportunity) -> Opportunity:
        self.opportunities.add(opportunity)
        self.opportunities.validate(opportunity.id)
        return self.opportunities.make_available(opportunity.id)

    def assign_best(
        self,
        trader_id: str,
        *,
        now: int | None = None,
    ):
        trader = self.registry.get(trader_id)
        opportunity = self.market.peek_best(trader_id, now=now)
        if opportunity is None:
            raise MarketAllocationError("no_available_opportunity")
        strategy_id = (
            opportunity.strategy_candidates[0]
            if opportunity.strategy_candidates
            else None
        )
        return self.market.assign(
            trader_id,
            opportunity.id,
            strategy_id=strategy_id,
            now=now,
        )

    def maybe_expand(
        self,
        trigger_trader_id: str,
        *,
        now: int | None = None,
    ) -> ExpansionDecision:
        decision = self.capital.can_expand_from(trigger_trader_id)
        if not decision.allowed:
            return decision
        if self.registry.slot_count() >= self.effective_trader_limit:
            return ExpansionDecision(
                False,
                "effective_trader_limit",
                trigger_trader_id,
            )

        trigger = self.registry.get(trigger_trader_id)
        opportunity = self.market.peek_best_for_mode(
            trigger.mode,
            now=now,
        )
        if opportunity is None:
            return ExpansionDecision(
                False,
                "no_available_opportunity",
                trigger_trader_id,
            )

        released = self.capital.release_expansion_capital(trigger_trader_id)
        new_trader = self.capital.create_funded_trader(
            mode=trigger.mode,
            spawned_from=trigger_trader_id,
            note="company_expansion",
        )
        try:
            strategy_id = (
                opportunity.strategy_candidates[0]
                if opportunity.strategy_candidates
                else None
            )
            self.market.assign(
                new_trader.id,
                opportunity.id,
                strategy_id=strategy_id,
                now=now,
            )
        except Exception:
            self.capital.settle_retired_trader(
                new_trader.id,
                positions_flat=True,
                reason="failed_market_assignment",
            )
            raise

        return ExpansionDecision(
            True,
            "expanded",
            trigger_trader_id,
            released_capital=released,
            new_trader_id=new_trader.id,
        )

    def record_realized_pnl(self, trader_id: str, pnl: float) -> dict:
        entry = self.treasury.record_pnl(trader_id, pnl)
        return {
            "ledger": entry.to_dict(),
            "trader_equity": self.treasury.balance(trader_id),
            "stop_floor_breached": self.capital.stop_floor_breached(trader_id),
            "spawn_eligible": self.capital.can_expand_from(trader_id).allowed,
        }

    def record_fee(self, trader_id: str, fee: float) -> dict:
        entry = self.treasury.record_fee(trader_id, fee)
        return {
            "ledger": entry.to_dict(),
            "trader_equity": self.treasury.balance(trader_id),
            "stop_floor_breached": self.capital.stop_floor_breached(trader_id),
        }

    def retire_trader(
        self,
        trader_id: str,
        *,
        positions_flat: bool,
        reason: str = "manual_retirement",
    ) -> float:
        if not positions_flat:
            # Keep the market reservation while positions still exist. Releasing
            # it first could let another Trader enter the same production market
            # before the old exposure is reconciled.
            return self.capital.settle_retired_trader(
                trader_id,
                positions_flat=False,
                reason=reason,
            )
        self.market.release(trader_id)
        return self.capital.settle_retired_trader(
            trader_id,
            positions_flat=True,
            reason=reason,
        )

    def enforce_stop_floor(
        self,
        trader_id: str,
        *,
        positions_flat: bool,
    ) -> float | None:
        if not self.capital.stop_floor_breached(trader_id):
            return None
        if not positions_flat:
            return self.capital.apply_stop_floor(
                trader_id,
                positions_flat=False,
            )
        self.market.release(trader_id)
        return self.capital.apply_stop_floor(
            trader_id,
            positions_flat=True,
        )

    def pause_trader(self, trader_id: str) -> dict:
        return self.registry.pause(trader_id).to_dict()

    def resume_trader(self, trader_id: str) -> dict:
        return self.registry.resume(trader_id).to_dict()

    def emergency_stop(self) -> dict:
        self.risk.kill()
        engine_result = None
        try:
            engine_result = self.engine.emergency_kill()
        except Exception as exc:
            engine_result = {
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "company_kill_switch": True,
            "caos": engine_result,
        }

    def audit(self) -> dict:
        return self.supervisor.audit().to_dict()

    def improvement_proposals(self) -> list[dict]:
        audit = self.supervisor.audit()
        return [
            proposal.to_dict()
            for proposal in self.improvement.propose(audit)
        ]

    def status(self) -> dict:
        audit = self.supervisor.audit()
        return {
            "policy": self.policy.to_dict(),
            "effective_trader_limit": self.effective_trader_limit,
            "treasury": self.treasury.snapshot(),
            "traders": self.registry.snapshot(),
            "opportunities": self.opportunities.snapshot(),
            "assignments": self.market.snapshot(),
            "risk": self.risk.snapshot(),
            "diversity": self.diversity.audit().to_dict(),
            "training": self.training.snapshot(),
            "audit": audit.to_dict(),
            "caos": self.engine.health(),
        }
