from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .domain import Opportunity, TraderMode, TraderStatus


@dataclass(slots=True, frozen=True)
class ScanTarget:
    symbol: str
    direction: str = "long"
    strategy_candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol required")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")


@dataclass(slots=True)
class CompanyDaemonCycle:
    refreshed: dict[str, int]
    opportunities: list[str]
    expired: list[str]
    assignments: list[dict]
    paper_actions: list[dict]
    expansions: list[dict]
    retirements: list[dict]
    errors: dict[str, str]
    audit: dict
    exposure: dict
    rollout_events: list[dict]
    paused: bool = False
    news_intelligence: dict = field(
        default_factory=dict
    )

    def to_dict(self) -> dict:
        return {
            "refreshed": dict(self.refreshed),
            "opportunities": list(self.opportunities),
            "expired": list(self.expired),
            "assignments": list(self.assignments),
            "paper_actions": list(self.paper_actions),
            "expansions": list(self.expansions),
            "retirements": list(self.retirements),
            "errors": dict(self.errors),
            "audit": dict(self.audit),
            "exposure": dict(self.exposure),
            "rollout_events": list(self.rollout_events),
            "paused": self.paused,
            "news_intelligence": dict(
                self.news_intelligence
            ),
        }


class CompanyDaemon:
    """Deterministic Company operating loop.

    Market refresh failures are isolated by symbol. Trader failures are isolated
    by Trader. No local LLM call is required on every cycle.
    """

    def __init__(
        self,
        company,
        targets: list[ScanTarget],
        *,
        interval: str = "60",
        candle_limit: int = 500,
        opportunity_ttl_ms: int = 3_600_000,
    ):
        if candle_limit <= 0:
            raise ValueError("candle_limit must be positive")
        if opportunity_ttl_ms <= 0:
            raise ValueError("opportunity_ttl_ms must be positive")
        self.company = company
        self.targets = list(targets)
        self.interval = interval
        self.candle_limit = int(candle_limit)
        self.opportunity_ttl_ms = int(opportunity_ttl_ms)

    def _symbols_to_refresh(self) -> list[str]:
        symbols = {target.symbol.upper() for target in self.targets}
        symbols.update(
            assignment.symbol
            for assignment in self.company.market.assignments.values()
        )
        symbols.update(
            release.symbol
            for release in self.company.rollout.releases.values()
            if release.stage in {"shadow", "paper_canary"}
        )
        return sorted(symbols)

    def _registered_strategy(
        self,
        opportunity: Opportunity,
    ) -> str | None:
        for strategy_id in opportunity.strategy_candidates:
            if (
                strategy_id in self.company.strategies.strategies
                and self.company.rollout.is_strategy_assignable(
                    opportunity.symbol,
                    strategy_id,
                )
            ):
                return strategy_id
        return None

    def _best_assignable(
        self,
        trader_id: str,
        *,
        now: int,
    ) -> tuple[Opportunity, str] | None:
        for opportunity in self.company.market.candidates(
            trader_id,
            now=now,
        ):
            strategy_id = self._registered_strategy(opportunity)
            if strategy_id is not None:
                return opportunity, strategy_id
        return None

    def _best_assignable_for_mode(
        self,
        mode: TraderMode,
        *,
        now: int,
    ) -> tuple[Opportunity, str] | None:
        for opportunity in self.company.market.candidates_for_mode(
            mode,
            now=now,
        ):
            strategy_id = self._registered_strategy(opportunity)
            if strategy_id is not None:
                return opportunity, strategy_id
        return None

    def _scan(
        self,
        *,
        now: int,
        refreshed: dict[str, int],
        errors: dict[str, str],
    ) -> list[str]:
        created: list[str] = []
        for index, target in enumerate(self.targets):
            symbol = target.symbol.upper()
            if symbol not in refreshed:
                continue
            oid = (
                f"scan:{symbol}:{target.direction}:"
                f"{now}:{index}"
            )
            try:
                news_context = (
                    self.company.news_intelligence
                    .context_for(symbol)
                )
                if news_context.get("block_new_risk"):
                    continue
                opportunity = self.company.scout.discover_and_publish(
                    symbol,
                    direction=target.direction,
                    expires_at=now + self.opportunity_ttl_ms,
                    opportunity_id=oid,
                    strategy_candidates=(
                        self.company.rollout.production_candidates(
                            symbol,
                            target.strategy_candidates,
                        )
                    ),
                )
                penalty = float(
                    news_context.get(
                        "score_penalty",
                        0.0,
                    )
                )
                opportunity.score = max(
                    0.0,
                    opportunity.score - penalty,
                )
                opportunity.metadata[
                    "news_context"
                ] = news_context
                created.append(opportunity.id)
            except Exception as exc:
                errors[f"scan:{symbol}:{target.direction}"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        return created

    def _assign_waiting(
        self,
        *,
        now: int,
        errors: dict[str, str],
    ) -> list[dict]:
        assigned: list[dict] = []
        for trader in list(self.company.registry.traders.values()):
            if trader.status != TraderStatus.WAITING_ASSIGNMENT:
                continue
            choice = self._best_assignable(trader.id, now=now)
            if choice is None:
                continue
            opportunity, strategy_id = choice
            try:
                assignment = self.company.market.assign(
                    trader.id,
                    opportunity.id,
                    strategy_id=strategy_id,
                    now=now,
                )
                assigned.append(assignment.to_dict())
            except Exception as exc:
                errors[f"assign:{trader.id}"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        return assigned

    def _paper_cycles(
        self,
        *,
        refreshed: dict[str, int],
        errors: dict[str, str],
        allow_new_risk: bool = True,
    ) -> tuple[list[dict], list[dict]]:
        actions: list[dict] = []
        retirements: list[dict] = []

        if self.company.engine.health().get("kill_switch"):
            self.company.risk.kill()

        for trader in list(self.company.registry.traders.values()):
            if trader.status != TraderStatus.ACTIVE:
                continue
            if not trader.market or trader.market not in refreshed:
                errors.setdefault(
                    f"paper:{trader.id}",
                    "market_refresh_required",
                )
                continue

            try:
                strategy_assignable = (
                    True
                    if not trader.strategy_id
                    else self.company.rollout.is_strategy_assignable(
                        trader.market,
                        trader.strategy_id,
                    )
                )
                news_context = (
                    self.company.news_intelligence
                    .context_for(trader.market)
                )
                result = self.company.paper.cycle_trader(
                    trader.id,
                    allow_new_risk=(
                        allow_new_risk
                        and strategy_assignable
                        and not news_context.get(
                            "block_new_risk",
                            False,
                        )
                    ),
                )
                actions.append(result.to_dict())

                if (
                    not strategy_assignable
                    and self.company.paper.positions_flat(
                        trader.id
                    )
                ):
                    released = self.company.market.release(
                        trader.id
                    )
                    actions.append(
                        {
                            "trader_id": trader.id,
                            "action": (
                                "release_inactive_strategy"
                            ),
                            "assignment": (
                                released.to_dict()
                                if released is not None
                                else None
                            ),
                        }
                    )
                    continue

                marked = self.company.paper.marked_equity(trader.id)
                if marked < self.company.policy.trader_stop_floor:
                    if not self.company.paper.positions_flat(trader.id):
                        flattened = self.company.paper.force_flatten(
                            trader.id
                        )
                        actions.append(flattened.to_dict())
                    residual = self.company.enforce_stop_floor(
                        trader.id,
                        positions_flat=True,
                    )
                    retirements.append(
                        {
                            "trader_id": trader.id,
                            "reason": "stop_floor",
                            "residual_to_treasury": residual,
                        }
                    )
            except Exception as exc:
                errors[f"paper:{trader.id}"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        return actions, retirements

    def _expand(
        self,
        *,
        now: int,
        errors: dict[str, str],
    ) -> list[dict]:
        expansions: list[dict] = []
        for trader in list(self.company.registry.traders.values()):
            if trader.status != TraderStatus.ACTIVE:
                continue
            decision = self.company.capital.can_expand_from(trader.id)
            if not decision.allowed:
                continue
            if (
                self.company.registry.slot_count()
                >= self.company.effective_trader_limit
            ):
                break
            if (
                decision.released_capital > 1e-9
                and trader.id in self.company.paper.accounts
                and not self.company.paper.positions_flat(trader.id)
            ):
                continue

            choice = self._best_assignable_for_mode(
                trader.mode,
                now=now,
            )
            if choice is None:
                continue
            opportunity, strategy_id = choice
            try:
                released = self.company.capital.release_expansion_capital(
                    trader.id
                )
                if (
                    released > 1e-9
                    and trader.id in self.company.paper.accounts
                ):
                    self.company.paper.withdraw_flat(
                        trader.id,
                        released,
                    )

                new_trader = self.company.capital.create_funded_trader(
                    mode=trader.mode,
                    spawned_from=(
                        trader.id
                        if released > 1e-9
                        else None
                    ),
                    note="daemon_company_expansion",
                )
                try:
                    assignment = self.company.market.assign(
                        new_trader.id,
                        opportunity.id,
                        strategy_id=strategy_id,
                        now=now,
                    )
                except Exception:
                    self.company.capital.settle_retired_trader(
                        new_trader.id,
                        positions_flat=True,
                        reason="daemon_assignment_rollback",
                    )
                    if released > 1e-9:
                        self.company.treasury.allocate(
                            trader.id,
                            released,
                            note="daemon_expansion_rollback",
                        )
                        if trader.id in self.company.paper.accounts:
                            self.company.paper.deposit_flat(
                                trader.id,
                                released,
                            )
                    raise

                expansions.append(
                    {
                        "trigger_trader_id": trader.id,
                        "new_trader_id": new_trader.id,
                        "released_capital": released,
                        "assignment": assignment.to_dict(),
                    }
                )
            except Exception as exc:
                errors[f"expand:{trader.id}"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        return expansions

    def run_once(self, *, now: int) -> CompanyDaemonCycle:
        refreshed: dict[str, int] = {}
        errors: dict[str, str] = {}

        expired = self.company.opportunities.expire_due(now)

        for symbol in self._symbols_to_refresh():
            try:
                result = self.company.engine.fetch_market(
                    symbol,
                    interval=self.interval,
                    limit=self.candle_limit,
                )
                refreshed[symbol] = int(result["bars"])
            except Exception as exc:
                errors[f"market:{symbol}"] = (
                    f"{type(exc).__name__}: {exc}"
                )

        try:
            news_snapshot = (
                self.company.news_intelligence.refresh(
                    self._symbols_to_refresh(),
                    now=now,
                )
            )
        except Exception as exc:
            errors["news:intelligence"] = (
                f"{type(exc).__name__}: {exc}"
            )
            news_snapshot = (
                self.company.news_intelligence.snapshot()
            )

        rollout_events: list[dict] = []
        if not self.company.operations_paused:
            for symbol in refreshed:
                try:
                    rollout_events.extend(
                        self.company.rollout.process_market(
                            symbol,
                            self.company.engine.bars(symbol),
                        )
                    )
                except Exception as exc:
                    errors[f"rollout:{symbol}"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

        if self.company.operations_paused:
            opportunities: list[str] = []
            assignments: list[dict] = []
            paper_actions, retirements = self._paper_cycles(
                refreshed=refreshed,
                errors=errors,
                allow_new_risk=False,
            )
            expansions: list[dict] = []
        else:
            opportunities = self._scan(
                now=now,
                refreshed=refreshed,
                errors=errors,
            )
            assignments = self._assign_waiting(
                now=now,
                errors=errors,
            )
            paper_actions, retirements = self._paper_cycles(
                refreshed=refreshed,
                errors=errors,
            )
            expansions = self._expand(
                now=now,
                errors=errors,
            )

        audit = self.company.audit()
        exposure = self.company.paper.exposure()
        self.company.checkpoint()

        if self.company.store is not None:
            self.company.store.event(
                "trade_company_daemon_cycle",
                {
                    "refreshed": refreshed,
                    "opportunities": len(opportunities),
                    "expired": len(expired),
                    "assignments": len(assignments),
                    "paper_actions": len(paper_actions),
                    "expansions": len(expansions),
                    "retirements": len(retirements),
                    "errors": errors,
                    "audit_status": audit["status"],
                    "gross_exposure": exposure["gross_notional"],
                    "operations_paused": self.company.operations_paused,
                    "rollout_events": len(rollout_events),
                    "news_blocked_symbols": [
                        symbol
                        for symbol, context in (
                            news_snapshot.get(
                                "contexts",
                                {},
                            ).items()
                        )
                        if context.get(
                            "block_new_risk"
                        )
                    ],
                    "news_errors": len(
                        news_snapshot.get(
                            "errors",
                            [],
                        )
                    ),
                },
            )

        return CompanyDaemonCycle(
            refreshed=refreshed,
            opportunities=opportunities,
            expired=expired,
            assignments=assignments,
            paper_actions=paper_actions,
            expansions=expansions,
            retirements=retirements,
            errors=errors,
            audit=audit,
            exposure=exposure,
            rollout_events=rollout_events,
            paused=self.company.operations_paused,
            news_intelligence=news_snapshot,
        )

    def serve(
        self,
        *,
        every_seconds: float = 60.0,
        clock_ms: Callable[[], int] | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> None:
        if every_seconds < 1:
            raise ValueError("every_seconds must be >= 1")
        clock = clock_ms or (lambda: int(time.time() * 1000))
        while True:
            if stop and stop():
                return
            self.run_once(now=int(clock()))
            time.sleep(every_seconds)
