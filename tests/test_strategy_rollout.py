import tempfile
import unittest
from pathlib import Path

from caos.company import (
    CAOSAdapter,
    StrategyRolloutPolicy,
    TradeCompany,
)
from caos.company.daemon import CompanyDaemon, ScanTarget
from caos.company.research import PromotionDecision
from caos.company.state import CompanyCheckpointError
from caos.company.standalone import build_policy
from caos.domain import Mandate, MarketBar, StrategySpec
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.store import Store


def bars_up(n=40, start=100.0, step=1.0):
    bars = []
    price = start
    for i in range(n):
        close = price + step
        bars.append(
            MarketBar(
                i,
                price,
                max(price, close) + 0.2,
                min(price, close) - 0.2,
                close,
                1000.0,
            )
        )
        price = close
    return bars


def make_company(directory, *, bootstrap=False):
    store = Store(Path(directory) / "rollout.db")
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    company = TradeCompany(
        CAOSAdapter(caos),
        build_policy(
            initial_company_capital=10,
            trader_initial_bucket=10,
            trader_stop_floor=3,
            default_trader_max_exposure_pct=20,
            operational_trader_cap=6,
            company_max_drawdown_pct=30,
        ),
        store=store,
    )
    company.register_strategy(
        StrategySpec(
            "momentum",
            "momentum",
            2,
            3,
            threshold=0.1,
        ),
        strategy_id="momentum",
    )
    if bootstrap:
        company.bootstrap()
    return store, company


def install_promoted_research_strategy(company):
    strategy_id = "research:candidate-rollout"
    company.register_strategy(
        StrategySpec(
            "rf_rollout_momentum",
            "momentum",
            2,
            3,
            threshold=0.1,
        ),
        strategy_id=strategy_id,
    )
    decision = PromotionDecision(
        id="promotion-rollout-1",
        symbol="BTCUSDT",
        candidate_id="candidate-rollout",
        candidate_strategy_id=strategy_id,
        prior_champion_strategy_id=None,
        status="promoted",
        reason="test_promotion",
    )
    company.research.decisions.append(decision)
    company.research.champions["BTCUSDT"] = strategy_id
    return strategy_id, decision


class StrategyRolloutDomainTests(unittest.TestCase):
    def test_promoted_champion_syncs_into_shadow_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            strategy_id, _ = install_promoted_research_strategy(
                company
            )
            rows = company.sync_strategy_rollouts()
            self.assertEqual(len(rows), 1)
            release = next(iter(company.rollout.releases.values()))
            self.assertEqual(release.stage, "shadow")
            self.assertFalse(
                company.rollout.is_strategy_assignable(
                    "BTCUSDT",
                    strategy_id,
                )
            )
            self.assertEqual(
                company.sync_strategy_rollouts(),
                [],
            )
            store.close()

    def test_shadow_canary_eligible_active_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            strategy_id, _ = install_promoted_research_strategy(
                company
            )
            company.rollout.policy = StrategyRolloutPolicy(
                min_shadow_observations=4,
                min_canary_observations=5,
                min_canary_trades=1,
                canary_starting_capital=10,
                canary_exposure_pct=20,
                canary_fee_bps=0,
                max_canary_drawdown_pct=20,
                min_canary_pnl_pct=-100,
            )
            release = company.rollout.sync_research(
                company.research
            )[0]

            company.rollout.process_market(
                "BTCUSDT",
                bars_up(4),
            )
            self.assertEqual(release.stage, "paper_canary")
            self.assertEqual(release.canary.last_ts, 3)

            company.rollout.process_market(
                "BTCUSDT",
                bars_up(16),
            )
            self.assertEqual(release.stage, "eligible")
            self.assertGreaterEqual(release.canary.trades, 1)
            self.assertGreaterEqual(
                release.canary.observations,
                5,
            )

            active = company.activate_strategy_release(
                release.id
            )
            self.assertEqual(active["stage"], "active")
            self.assertEqual(
                company.rollout.production_catalog["BTCUSDT"],
                strategy_id,
            )
            self.assertTrue(
                company.rollout.is_strategy_assignable(
                    "BTCUSDT",
                    strategy_id,
                )
            )

            rolled = company.rollback_strategy_release(
                release.id,
                reason="test_rollback",
            )
            self.assertEqual(
                rolled["release"]["stage"],
                "rolled_back",
            )
            self.assertNotIn(
                "BTCUSDT",
                company.rollout.production_catalog,
            )
            self.assertFalse(
                company.rollout.is_strategy_assignable(
                    "BTCUSDT",
                    strategy_id,
                )
            )
            store.close()

    def test_canary_drawdown_breach_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            install_promoted_research_strategy(company)
            company.rollout.policy = StrategyRolloutPolicy(
                min_shadow_observations=4,
                min_canary_observations=100,
                min_canary_trades=1,
                canary_starting_capital=10,
                canary_exposure_pct=50,
                canary_fee_bps=0,
                max_canary_drawdown_pct=0.5,
                min_canary_pnl_pct=-100,
            )
            release = company.rollout.sync_research(
                company.research
            )[0]
            company.rollout.process_market(
                "BTCUSDT",
                bars_up(4),
            )
            bars = bars_up(7)
            bars.extend(
                [
                    MarketBar(7, 107, 108, 89, 90, 1000),
                    MarketBar(8, 90, 91, 79, 80, 1000),
                ]
            )
            company.rollout.process_market(
                "BTCUSDT",
                bars,
            )
            self.assertEqual(release.stage, "rolled_back")
            self.assertEqual(
                release.rollback_reason,
                "canary_drawdown_gate_failed",
            )
            store.close()


class StrategyRolloutDaemonTests(unittest.TestCase):
    def _active_rollout_company(self, directory):
        store, company = make_company(
            directory,
            bootstrap=True,
        )
        strategy_id, _ = install_promoted_research_strategy(
            company
        )
        release = company.rollout.sync_research(
            company.research
        )[0]
        release.stage = "eligible"
        company.activate_strategy_release(release.id)
        bars = bars_up(50)
        company.engine.load_bars("BTCUSDT", bars)

        def fake_fetch(symbol, interval="60", limit=500):
            del interval, limit
            return {
                "symbol": symbol,
                "bars": len(company.engine.bars(symbol)),
            }

        company.engine.fetch_market = fake_fetch
        return store, company, strategy_id, release

    def test_inactive_research_strategy_cannot_be_assigned_manually(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(
                d,
                bootstrap=True,
            )
            strategy_id, _ = install_promoted_research_strategy(
                company
            )
            release = company.rollout.sync_research(
                company.research
            )[0]
            self.assertEqual(release.stage, "shadow")
            bars = bars_up(30)
            company.engine.load_bars("BTCUSDT", bars)

            def fake_fetch(symbol, interval="60", limit=500):
                del interval, limit
                return {"symbol": symbol, "bars": len(bars)}

            company.engine.fetch_market = fake_fetch
            daemon = CompanyDaemon(
                company,
                [
                    ScanTarget(
                        "BTCUSDT",
                        "long",
                        (strategy_id,),
                    )
                ],
            )
            cycle = daemon.run_once(now=1_000)
            self.assertEqual(cycle.assignments, [])
            self.assertIsNone(
                company.registry.get("A").strategy_id
            )
            store.close()

    def test_company_pause_freezes_rollout_progression(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            install_promoted_research_strategy(company)
            release = company.rollout.sync_research(
                company.research
            )[0]
            bars = bars_up(30)
            company.engine.load_bars("BTCUSDT", bars)

            def fake_fetch(symbol, interval="60", limit=500):
                del interval, limit
                return {"symbol": symbol, "bars": len(bars)}

            company.engine.fetch_market = fake_fetch
            company.pause_operations()
            daemon = CompanyDaemon(
                company,
                [ScanTarget("BTCUSDT", "long", ("momentum",))],
            )
            cycle = daemon.run_once(now=1_000)
            self.assertTrue(cycle.paused)
            self.assertEqual(cycle.rollout_events, [])
            self.assertEqual(release.shadow_observations, 0)
            self.assertEqual(release.stage, "shadow")
            store.close()
    def test_active_release_is_prioritized_for_new_opportunity(self):
        with tempfile.TemporaryDirectory() as d:
            store, company, strategy_id, release = (
                self._active_rollout_company(d)
            )
            daemon = CompanyDaemon(
                company,
                [
                    ScanTarget(
                        "BTCUSDT",
                        "long",
                        ("momentum",),
                    )
                ],
            )
            cycle = daemon.run_once(now=1_000)
            self.assertEqual(
                company.registry.get("A").strategy_id,
                strategy_id,
            )
            self.assertTrue(cycle.assignments)
            opportunity = next(
                row
                for row in company.opportunities.opportunities.values()
                if row.symbol == "BTCUSDT"
            )
            self.assertEqual(
                opportunity.strategy_candidates[0],
                strategy_id,
            )
            self.assertEqual(
                company.rollout.production_catalog["BTCUSDT"],
                strategy_id,
            )
            self.assertEqual(release.stage, "active")
            store.close()

    def test_rollback_does_not_force_close_and_releases_when_flat(self):
        with tempfile.TemporaryDirectory() as d:
            store, company, strategy_id, release = (
                self._active_rollout_company(d)
            )
            daemon = CompanyDaemon(
                company,
                [
                    ScanTarget(
                        "BTCUSDT",
                        "long",
                        ("momentum",),
                    )
                ],
            )
            daemon.run_once(now=1_000)
            self.assertEqual(
                company.registry.get("A").strategy_id,
                strategy_id,
            )
            self.assertFalse(
                company.paper.positions_flat("A")
            )

            rolled = company.rollback_strategy_release(
                release.id,
                reason="operator_rollback",
            )
            self.assertEqual(
                rolled["impacted_traders"],
                ["A"],
            )
            self.assertFalse(
                company.paper.positions_flat("A")
            )

            company.paper.force_flatten("A")
            self.assertTrue(
                company.paper.positions_flat("A")
            )
            daemon.run_once(now=2_000)
            trader = company.registry.get("A")
            self.assertIsNone(trader.strategy_id)
            self.assertIsNone(trader.market)
            self.assertEqual(
                trader.status.value,
                "waiting_assignment",
            )
            store.close()


class StrategyRolloutPersistenceTests(unittest.TestCase):
    def test_rollout_survives_checkpoint_restore(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            strategy_id, _ = install_promoted_research_strategy(
                company
            )
            release = company.rollout.sync_research(
                company.research
            )[0]
            release.stage = "eligible"
            company.activate_strategy_release(release.id)
            company.checkpoint()

            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.rollout.production_catalog["BTCUSDT"],
                strategy_id,
            )
            self.assertEqual(
                restored.rollout.get(release.id).stage,
                "active",
            )
            store.close()

    def test_old_checkpoint_without_rollout_restores_empty(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            company.checkpoint()
            payload = store.get_json(
                "trade_company_checkpoint_v1"
            )
            payload.pop("rollout", None)
            store.set_json(
                "trade_company_checkpoint_v1",
                payload,
            )
            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.rollout.summary()["releases"],
                0,
            )
            store.close()

    def test_corrupt_active_catalog_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            install_promoted_research_strategy(company)
            release = company.rollout.sync_research(
                company.research
            )[0]
            company.checkpoint()
            payload = store.get_json(
                "trade_company_checkpoint_v1"
            )
            payload["rollout"]["production_catalog"][
                "BTCUSDT"
            ] = release.strategy_id
            store.set_json(
                "trade_company_checkpoint_v1",
                payload,
            )
            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            with self.assertRaises(CompanyCheckpointError):
                restored.restore_checkpoint()
            store.close()


if __name__ == "__main__":
    unittest.main()
