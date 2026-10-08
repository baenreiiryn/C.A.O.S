from __future__ import annotations

from ..execution_fabric import EXECUTION_FABRIC_VERSION
from .adapter import CAOSAdapter
from .capital import CapitalAllocator, ExpansionDecision
from .diversity import StrategyDiversity
from .domain import CompanyPolicy, Opportunity, TraderMode, TraderStatus
from .improvement import ImprovementManager
from .market import MarketAllocator, MarketAllocationError, OpportunityRegistry
from .paper import CompanyPaperBook, CompanyPaperError
from .registry import TraderRegistry
from .research import ResearchFactory
from .risk import CompanyRiskGovernor
from .rollout import StrategyRolloutManager
from .scout import MarketScout
from .state import CompanyCheckpoint
from .strategy import CompanyStrategyRegistry
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
        *,
        store=None,
    ):
        self.engine = engine
        self.policy = policy or CompanyPolicy()
        self.store = store if store is not None else engine.store
        self.effective_trader_limit = self.policy.operational_trader_cap
        self.operations_paused = False

        self.treasury = Treasury(self.policy.initial_company_capital)
        self.registry = TraderRegistry()
        self.opportunities = OpportunityRegistry()
        self.strategies = CompanyStrategyRegistry()
        self.capital = CapitalAllocator(
            self.policy,
            self.treasury,
            self.registry,
        )
        self.capital.set_operational_limit_provider(
            lambda: self.effective_trader_limit
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
        self.research = ResearchFactory(
            self.strategies,
            self.training,
        )
        self.rollout = StrategyRolloutManager(
            self.strategies,
        )
        self.paper = CompanyPaperBook(
            self.engine,
            self.policy,
            self.treasury,
            self.registry,
            self.market,
            self.risk,
            self.strategies,
        )
        self.risk.set_equity_providers(
            trader_equity=self.paper.marked_equity,
            company_equity=self.marked_company_equity,
        )
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
            paper=self.paper,
        )
        self.improvement = ImprovementManager()

    def _save(self) -> None:
        if self.store is not None:
            CompanyCheckpoint.save(self, self.store)

    def checkpoint(self) -> dict | None:
        if self.store is None:
            return None
        return CompanyCheckpoint.save(self, self.store)

    def restore_checkpoint(self) -> bool:
        if self.store is None:
            return False
        return CompanyCheckpoint.restore(self, self.store)

    def marked_company_equity(self) -> float:
        equity = self.treasury.reserve
        for trader in self.registry.traders.values():
            if trader.status == TraderStatus.RETIRED:
                continue
            equity += self.paper.marked_equity(trader.id)
        return equity

    def register_strategy(self, spec, *, strategy_id: str | None = None) -> str:
        key = self.strategies.register(spec, strategy_id=strategy_id)
        self._save()
        return key

    def set_effective_trader_limit(self, limit: int) -> int:
        if not 1 <= int(limit) <= self.policy.operational_trader_cap:
            raise TradeCompanyError("effective_limit_outside_operational_cap")
        if int(limit) < self.registry.slot_count():
            raise TradeCompanyError("effective_limit_below_current_slots")
        self.effective_trader_limit = int(limit)
        self._save()
        return self.effective_trader_limit

    def bootstrap(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
        assign_best: bool = False,
        now: int | None = None,
        max_trade_exposure_pct: float | None = None,
        trade_exposure_pct: float | None = None,
    ):
        trader = self.capital.bootstrap_first_trader(
            mode=mode,
            max_trade_exposure_pct=max_trade_exposure_pct,
            trade_exposure_pct=trade_exposure_pct,
        )
        if assign_best:
            self.assign_best(trader.id, now=now)
        self._save()
        return trader

    def publish_opportunity(self, opportunity: Opportunity) -> Opportunity:
        self.opportunities.add(opportunity)
        self.opportunities.validate(opportunity.id)
        result = self.opportunities.make_available(opportunity.id)
        self._save()
        return result

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
        result = self.market.assign(
            trader_id,
            opportunity.id,
            strategy_id=strategy_id,
            now=now,
        )
        self._save()
        return result

    def maybe_expand(
        self,
        trigger_trader_id: str,
        *,
        now: int | None = None,
    ) -> ExpansionDecision:
        trigger = self.registry.get(trigger_trader_id)
        treasury_shortfall = max(
            0.0,
            self.policy.trader_initial_bucket - self.treasury.reserve,
        )
        if (
            treasury_shortfall > 1e-9
            and trigger_trader_id in self.paper.accounts
            and not self.paper.positions_flat(trigger_trader_id)
        ):
            return ExpansionDecision(
                False,
                "trigger_trader_not_flat",
                trigger_trader_id,
            )

        decision = self.capital.can_expand_from(trigger_trader_id)
        if not decision.allowed:
            return decision
        if self.registry.slot_count() >= self.effective_trader_limit:
            return ExpansionDecision(
                False,
                "effective_trader_limit",
                trigger_trader_id,
            )

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

        if (
            decision.released_capital > 1e-9
            and trigger_trader_id in self.paper.accounts
        ):
            paper_equity = self.paper.realized_equity(trigger_trader_id)
            treasury_equity = self.treasury.balance(trigger_trader_id)
            if abs(paper_equity - treasury_equity) > 1e-8:
                return ExpansionDecision(
                    False,
                    "reconciliation_required",
                    trigger_trader_id,
                )
            if (
                self.paper.accounts[trigger_trader_id].cash + 1e-9
                < decision.released_capital
            ):
                return ExpansionDecision(
                    False,
                    "paper_cash_insufficient_for_expansion",
                    trigger_trader_id,
                )

        released = self.capital.release_expansion_capital(trigger_trader_id)
        if (
            released > 1e-9
            and trigger_trader_id in self.paper.accounts
        ):
            self.paper.withdraw_flat(trigger_trader_id, released)

        new_trader = self.capital.create_funded_trader(
            mode=trigger.mode,
            spawned_from=(
                trigger_trader_id
                if released > 1e-9
                else None
            ),
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
            if released > 1e-9:
                self.treasury.allocate(
                    trigger_trader_id,
                    released,
                    note="expansion_rollback",
                )
                if trigger_trader_id in self.paper.accounts:
                    self.paper.deposit_flat(
                        trigger_trader_id,
                        released,
                    )
            raise

        self._save()
        return ExpansionDecision(
            True,
            "expanded",
            trigger_trader_id,
            released_capital=released,
            new_trader_id=new_trader.id,
        )

    def record_realized_pnl(self, trader_id: str, pnl: float) -> dict:
        if trader_id in self.paper.accounts:
            self.paper.adjust_flat_cash(trader_id, float(pnl))
        entry = self.treasury.record_pnl(trader_id, pnl)
        self._save()
        return {
            "ledger": entry.to_dict(),
            "trader_equity": self.treasury.balance(trader_id),
            "stop_floor_breached": self.capital.stop_floor_breached(trader_id),
            "spawn_eligible": self.capital.can_expand_from(trader_id).allowed,
        }

    def record_fee(self, trader_id: str, fee: float) -> dict:
        if trader_id in self.paper.accounts:
            self.paper.adjust_flat_cash(trader_id, -float(fee))
        entry = self.treasury.record_fee(trader_id, fee)
        self._save()
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
            return self.capital.settle_retired_trader(
                trader_id,
                positions_flat=False,
                reason=reason,
            )
        if (
            trader_id in self.paper.accounts
            and not self.paper.positions_flat(trader_id)
        ):
            raise CompanyPaperError("positions_not_actually_flat")
        if trader_id in self.paper.accounts:
            self.paper.reconcile_trader(trader_id)
        self.market.release(trader_id)
        settled = self.capital.settle_retired_trader(
            trader_id,
            positions_flat=True,
            reason=reason,
        )
        self.paper.remove_account_if_flat(trader_id)
        self._save()
        return settled

    def enforce_stop_floor(
        self,
        trader_id: str,
        *,
        positions_flat: bool,
    ) -> float | None:
        current_equity = self.paper.marked_equity(trader_id)
        if current_equity >= self.policy.trader_stop_floor:
            return None
        if not positions_flat:
            self.registry.halt(trader_id)
            self._save()
            raise CompanyPaperError("positions_must_be_flat_before_stop_settlement")
        if (
            trader_id in self.paper.accounts
            and not self.paper.positions_flat(trader_id)
        ):
            raise CompanyPaperError("positions_not_actually_flat")
        if trader_id in self.paper.accounts:
            self.paper.reconcile_trader(trader_id)
        self.market.release(trader_id)
        settled = self.capital.settle_retired_trader(
            trader_id,
            positions_flat=True,
            reason="stop_floor",
        )
        self.paper.remove_account_if_flat(trader_id)
        self._save()
        return settled

    def configure_trader_exposure(
        self,
        trader_id: str,
        *,
        max_trade_exposure_pct: float,
        trade_exposure_pct: float | None = None,
    ) -> dict:
        trader = self.registry.get(trader_id)
        max_pct = float(max_trade_exposure_pct)
        requested = (
            float(trade_exposure_pct)
            if trade_exposure_pct is not None
            else None
        )
        if not 0 < max_pct <= 100:
            raise TradeCompanyError("invalid_trader_exposure_ceiling")
        if requested is not None and not 0 < requested <= max_pct:
            raise TradeCompanyError("invalid_trader_requested_exposure")
        trader.max_trade_exposure_pct = max_pct
        trader.trade_exposure_pct = requested
        account = self.paper.accounts.get(trader_id)
        if account is not None:
            account.risk.mandate.max_position_pct = max_pct
        self._save()
        return {
            "trader_id": trader_id,
            "max_trade_exposure_pct": max_pct,
            "trade_exposure_pct": requested,
            "current_equity": self.paper.marked_equity(trader_id),
            "max_trade_notional": self.risk.max_trade_notional(trader_id),
            "requested_trade_notional": self.risk.requested_trade_notional(
                trader_id
            ),
        }

    def pause_operations(self) -> dict:
        self.operations_paused = True
        self._save()
        if self.store is not None:
            self.store.event(
                "trade_company_operations_paused",
                {"operations_paused": True},
            )
        return {
            "operations_paused": True,
            "risk_kill_switch": self.risk.state.kill_switch,
        }

    def resume_operations(self) -> dict:
        if self.risk.state.kill_switch:
            raise TradeCompanyError(
                "company_kill_switch_active_cannot_resume"
            )
        if self.engine.health().get("kill_switch"):
            raise TradeCompanyError(
                "caos_kill_switch_active_cannot_resume"
            )
        self.operations_paused = False
        self._save()
        if self.store is not None:
            self.store.event(
                "trade_company_operations_resumed",
                {"operations_paused": False},
            )
        return {
            "operations_paused": False,
            "risk_kill_switch": False,
        }

    def pause_trader(self, trader_id: str) -> dict:
        result = self.registry.pause(trader_id).to_dict()
        self._save()
        return result

    def resume_trader(self, trader_id: str) -> dict:
        result = self.registry.resume(trader_id).to_dict()
        self._save()
        return result

    def emergency_stop(self) -> dict:
        self.risk.kill()
        engine_result = None
        try:
            engine_result = self.engine.emergency_kill()
        except Exception as exc:
            engine_result = {
                "error": f"{type(exc).__name__}: {exc}",
            }
        self._save()
        return {
            "company_kill_switch": True,
            "caos": engine_result,
        }

    def submit_research_hypothesis(
        self,
        *,
        symbol: str,
        family: str,
        thesis: str,
        source: str = "manual",
        parent_strategy_id: str | None = None,
    ) -> dict:
        hypothesis = self.research.submit_hypothesis(
            symbol=symbol,
            family=family,
            thesis=thesis,
            source=source,
            parent_strategy_id=parent_strategy_id,
        )
        self._save()
        return hypothesis.to_dict()

    def seed_research_from_improvements(
        self,
        *,
        symbol: str,
        family: str,
    ) -> list[dict]:
        rows = self.research.seed_from_improvement_proposals(
            self.improvement_proposals(),
            symbol=symbol,
            family=family,
        )
        if rows:
            self._save()
        return [row.to_dict() for row in rows]

    def run_research_cycle(
        self,
        hypothesis_id: str,
        *,
        generator_id: str = "builtin_grid",
        candidate_limit: int = 12,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
    ) -> dict:
        hypothesis = self.research.hypotheses[hypothesis_id]
        bars = self.engine.bars(hypothesis.symbol)
        if not bars:
            try:
                self.engine.fetch_market(
                    hypothesis.symbol,
                    limit=500,
                )
            except Exception as exc:
                raise TradeCompanyError(
                    "research_market_data_required"
                ) from exc
            bars = self.engine.bars(hypothesis.symbol)
        if not bars:
            raise TradeCompanyError("research_market_data_required")
        result = self.research.run_cycle(
            hypothesis_id,
            bars,
            generator_id=generator_id,
            candidate_limit=candidate_limit,
            starting_capital=starting_capital,
            cost_bps=cost_bps,
            max_drawdown_pct=self.policy.company_max_drawdown_pct,
            max_position_pct=(
                self.policy.default_trader_max_exposure_pct
            ),
        )
        created_releases = self.rollout.sync_research(
            self.research
        )
        result["rollout_releases"] = [
            row.to_dict()
            for row in created_releases
        ]
        self._save()
        if self.store is not None:
            self.store.event(
                "trade_company_research_cycle",
                {
                    "hypothesis_id": hypothesis_id,
                    "promotion": result["promotion"],
                    "rollout_releases": [
                        row.id
                        for row in created_releases
                    ],
                },
            )
        return result

    def sync_strategy_rollouts(self) -> list[dict]:
        rows = self.rollout.sync_research(self.research)
        if rows:
            self._save()
        return [row.to_dict() for row in rows]

    def process_strategy_rollouts(
        self,
        symbol: str,
    ) -> list[dict]:
        bars = self.engine.bars(symbol)
        if not bars:
            try:
                self.engine.fetch_market(
                    symbol,
                    limit=500,
                )
            except Exception as exc:
                raise TradeCompanyError(
                    "rollout_market_data_required"
                ) from exc
            bars = self.engine.bars(symbol)
        if not bars:
            raise TradeCompanyError("rollout_market_data_required")
        events = self.rollout.process_market(
            symbol,
            bars,
        )
        if events:
            self._save()
        return events

    def activate_strategy_release(
        self,
        release_id: str,
    ) -> dict:
        release = self.rollout.activate(release_id)
        self._save()
        if self.store is not None:
            self.store.event(
                "trade_company_strategy_release_activated",
                release.to_dict(),
            )
        return release.to_dict()

    def rollback_strategy_release(
        self,
        release_id: str,
        *,
        reason: str = "manual_rollback",
    ) -> dict:
        release = self.rollout.rollback(
            release_id,
            reason=reason,
        )
        impacted = [
            trader.id
            for trader in self.registry.traders.values()
            if (
                trader.status != TraderStatus.RETIRED
                and trader.strategy_id == release.strategy_id
            )
        ]
        self._save()
        if self.store is not None:
            self.store.event(
                "trade_company_strategy_release_rolled_back",
                {
                    "release": release.to_dict(),
                    "impacted_traders": impacted,
                },
            )
        return {
            "release": release.to_dict(),
            "impacted_traders": impacted,
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
            "operations_paused": self.operations_paused,
            "effective_trader_limit": self.effective_trader_limit,
            "treasury": self.treasury.snapshot(),
            "treasury_spawn_capacity": int(
                self.treasury.reserve
                / self.policy.trader_initial_bucket
            ),
            "marked_company_equity": self.marked_company_equity(),
            "traders": self.registry.snapshot(),
            "opportunities": self.opportunities.snapshot(),
            "assignments": self.market.snapshot(),
            "risk": self.risk.snapshot(),
            "diversity": self.diversity.audit().to_dict(),
            "strategies": self.strategies.snapshot(),
            "paper": self.paper.snapshot(),
            "execution_fabric": {
                "version": EXECUTION_FABRIC_VERSION,
                "last_plans": dict(self.paper.last_plans),
            },
            "exposure": self.paper.exposure(),
            "reconciliation_mismatches": self.paper.audit_reconciliation(),
            "training": self.training.snapshot(),
            "research": self.research.snapshot(),
            "research_summary": self.research.summary(),
            "rollout": self.rollout.snapshot(),
            "rollout_summary": self.rollout.summary(),
            "audit": audit.to_dict(),
            "caos": self.engine.health(),
        }
