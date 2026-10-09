from __future__ import annotations

import threading
import time

from .company import TradeCompany


class CompanyControlPort:
    """Safe external control surface for CLI/UI and a future Drizzt adapter.

    This interface deliberately contains no direct broker or credential access.
    """

    def __init__(self, company: TradeCompany):
        self.company = company
        self._live_chart_cache: dict[
            tuple[str, int],
            tuple[float, list],
        ] = {}
        self._live_chart_lock = threading.RLock()

    def get_company_status(self) -> dict:
        return self.company.status()

    def get_treasury(self) -> dict:
        return self.company.treasury.snapshot()

    def list_traders(self) -> list[dict]:
        return [
            trader.to_dict()
            for trader in self.company.registry.traders.values()
        ]

    def list_opportunities(self) -> list[dict]:
        return [
            opportunity.to_dict()
            for opportunity in self.company.opportunities.opportunities.values()
        ]

    def list_experiments(self) -> list[dict]:
        return [
            experiment.to_dict()
            for experiment in self.company.training.experiments.values()
        ]

    def get_strategy_rollouts(self) -> dict:
        return self.company.rollout.snapshot()

    def get_strategy_rollout_summary(self) -> dict:
        return self.company.rollout.summary()

    def sync_strategy_rollouts(self) -> list[dict]:
        return self.company.sync_strategy_rollouts()

    def process_strategy_rollouts(
        self,
        symbol: str,
    ) -> list[dict]:
        return self.company.process_strategy_rollouts(symbol)

    def activate_strategy_release(
        self,
        release_id: str,
    ) -> dict:
        return self.company.activate_strategy_release(release_id)

    def rollback_strategy_release(
        self,
        release_id: str,
        *,
        reason: str = "manual_rollback",
    ) -> dict:
        return self.company.rollback_strategy_release(
            release_id,
            reason=reason,
        )

    def get_research(self) -> dict:
        return self.company.research.snapshot()

    def get_research_summary(self) -> dict:
        return self.company.research.summary()

    def submit_research_hypothesis(
        self,
        *,
        symbol: str,
        family: str,
        thesis: str,
        source: str = "manual",
        parent_strategy_id: str | None = None,
    ) -> dict:
        return self.company.submit_research_hypothesis(
            symbol=symbol,
            family=family,
            thesis=thesis,
            source=source,
            parent_strategy_id=parent_strategy_id,
        )

    def seed_research_from_improvements(
        self,
        *,
        symbol: str,
        family: str,
    ) -> list[dict]:
        return self.company.seed_research_from_improvements(
            symbol=symbol,
            family=family,
        )

    def run_research_cycle(
        self,
        hypothesis_id: str,
        *,
        generator_id: str = "builtin_grid",
        candidate_limit: int = 12,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
    ) -> dict:
        return self.company.run_research_cycle(
            hypothesis_id,
            generator_id=generator_id,
            candidate_limit=candidate_limit,
            starting_capital=starting_capital,
            cost_bps=cost_bps,
        )

    def get_execution_reliability(self) -> dict:
        reliability = self.company.execution_reliability
        if reliability is None:
            return {
                "enabled": False,
                "summary": {
                    "total": 0,
                    "recovery_required": 0,
                    "counts": {},
                },
                "intents": [],
            }
        return {
            "enabled": True,
            "summary": reliability.summary(),
            "intents": reliability.list(limit=100),
        }

    def get_execution_plans(self) -> dict:
        return {
            "version": self.company.status()[
                "execution_fabric"
            ]["version"],
            "last_plans": dict(
                self.company.paper.last_plans
            ),
        }

    def get_trader_chart(
        self,
        trader_id: str,
        *,
        limit: int = 160,
    ) -> dict:
        trader = self.company.registry.get(trader_id)
        symbol = trader.market
        if not symbol:
            return self.company.paper.chart_snapshot(
                trader_id,
                limit=limit,
                chart_interval="1m",
                live=True,
            )

        limit = max(30, min(int(limit), 500))
        key = (symbol.upper(), limit)
        now = time.monotonic()
        bars = None
        with self._live_chart_lock:
            cached = self._live_chart_cache.get(key)
            if cached and now - cached[0] < 5.0:
                bars = cached[1]

        live_error = None
        if bars is None:
            try:
                bars = (
                    self.company.engine.caos.market_client.klines(
                        symbol,
                        "1m",
                        limit,
                    )
                )
                with self._live_chart_lock:
                    self._live_chart_cache[key] = (
                        now,
                        list(bars),
                    )
            except Exception as exc:
                live_error = (
                    f"{type(exc).__name__}: {exc}"
                )

        snapshot = self.company.paper.chart_snapshot(
            trader_id,
            limit=limit,
            bars_override=bars,
            chart_interval="1m",
            live=bars is not None,
        )
        if live_error:
            snapshot["live_error"] = live_error
        snapshot["live_refresh_seconds"] = 5
        return snapshot

    def get_recent_events(self, limit: int = 30) -> list[dict]:
        if self.company.store is None:
            return []
        return self.company.store.recent_events(
            max(1, min(int(limit), 100))
        )

    def start_operations(self) -> dict:
        return self.company.start_operations()

    def stop_operations(self) -> dict:
        return self.company.stop_operations()

    def pause_operations(self) -> dict:
        return self.company.pause_operations()

    def resume_operations(self) -> dict:
        return self.company.resume_operations()

    def pause_trader(self, trader_id: str) -> dict:
        return self.company.pause_trader(trader_id)

    def resume_trader(self, trader_id: str) -> dict:
        return self.company.resume_trader(trader_id)

    def set_effective_trader_limit(self, limit: int) -> dict:
        return {
            "effective_trader_limit": self.company.set_effective_trader_limit(limit)
        }

    def set_operational_trader_limit(self, limit: int) -> dict:
        return self.set_effective_trader_limit(limit)

    def configure_trader_exposure(
        self,
        trader_id: str,
        *,
        max_trade_exposure_pct: float,
        trade_exposure_pct: float | None = None,
    ) -> dict:
        return self.company.configure_trader_exposure(
            trader_id,
            max_trade_exposure_pct=max_trade_exposure_pct,
            trade_exposure_pct=trade_exposure_pct,
        )

    def request_improvement(self) -> list[dict]:
        return self.company.improvement_proposals()

    def emergency_stop(self) -> dict:
        return self.company.emergency_stop()
