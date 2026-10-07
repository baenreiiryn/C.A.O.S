import unittest

from caos.cli import synthetic_bars
from caos.company import (
    CAOSAdapter,
    CompanyPolicy,
    CompanyRiskViolation,
    Opportunity,
    TradeCompany,
    TraderMode,
    TrainingVariant,
)
from caos.company.capital import CapitalAllocationError
from caos.company.control import CompanyControlPort
from caos.company.market import MarketAllocationError
from caos.company.treasury import Treasury, TreasuryError
from caos.domain import Mandate, StrategySpec
from caos.llm import StaticLLM
from caos.orchestrator import CAOS


def engine():
    caos = CAOS(StaticLLM('{"tool":"status","args":{}}'))
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    return caos, CAOSAdapter(caos)


def opportunity(
    oid,
    symbol,
    score,
    *,
    direction="long",
    strategies=(),
    expires_at=None,
):
    return Opportunity(
        id=oid,
        symbol=symbol,
        direction=direction,
        score=score,
        strategy_candidates=tuple(strategies),
        expires_at=expires_at,
    )


class TreasuryTests(unittest.TestCase):
    def test_ledger_conserves_internal_transfer(self):
        t = Treasury(10)
        self.assertEqual(t.company_equity, 10)
        t.allocate("A", 10)
        self.assertEqual(t.reserve, 0)
        self.assertEqual(t.balance("A"), 10)
        self.assertEqual(t.company_equity, 10)

        t.record_pnl("A", 2.5)
        self.assertEqual(t.company_equity, 12.5)
        t.harvest("A", 5)
        self.assertEqual(t.reserve, 5)
        self.assertEqual(t.balance("A"), 7.5)
        self.assertEqual(t.company_equity, 12.5)

    def test_account_cannot_be_spent_below_zero(self):
        t = Treasury(10)
        t.allocate("A", 10)
        with self.assertRaises(TreasuryError):
            t.record_pnl("A", -10.01)


class CompanyLifecycleTests(unittest.TestCase):
    def setUp(self):
        _, adapter = engine()
        self.company = TradeCompany(adapter)

    def test_parent_genealogy_never_owns_child_capital(self):
        c = self.company
        c.publish_opportunity(
            opportunity("btc", "BTCUSDT", 100, strategies=("momentum",))
        )
        c.publish_opportunity(
            opportunity("eth", "ETHUSDT", 90, strategies=("breakout",))
        )

        a = c.bootstrap(assign_best=True)
        self.assertEqual(a.id, "A")
        self.assertEqual(a.market, "BTCUSDT")
        self.assertEqual(c.treasury.balance("A"), 10)

        c.record_realized_pnl("A", 10)
        decision = c.maybe_expand("A")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.new_trader_id, "B")

        b = c.registry.get("B")
        self.assertEqual(b.spawned_from, "A")
        self.assertEqual(b.market, "ETHUSDT")
        self.assertEqual(c.treasury.balance("A"), 10)
        self.assertEqual(c.treasury.balance("B"), 10)
        self.assertEqual(c.treasury.company_equity, 20)

        settled = c.retire_trader(
            "A",
            positions_flat=True,
            reason="test_A_exits_before_B",
        )
        self.assertEqual(settled, 10)
        self.assertEqual(c.treasury.balance("A"), 0)
        self.assertEqual(c.treasury.reserve, 10)
        self.assertEqual(c.treasury.balance("B"), 10)
        self.assertEqual(c.registry.get("B").market, "ETHUSDT")
        self.assertEqual(c.registry.get("B").status.value, "active")
        self.assertEqual(c.treasury.company_equity, 20)

    def test_no_market_means_no_forced_spawn_or_harvest(self):
        c = self.company
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.bootstrap(assign_best=True)
        c.record_realized_pnl("A", 10)
        decision = c.maybe_expand("A")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no_available_opportunity")
        self.assertEqual(c.treasury.balance("A"), 20)
        self.assertEqual(c.treasury.reserve, 0)
        self.assertEqual(c.registry.slot_count(), 1)

    def test_stop_floor_returns_residual_to_treasury_not_parent(self):
        c = self.company
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.publish_opportunity(opportunity("eth", "ETHUSDT", 90))
        c.bootstrap(assign_best=True)
        c.record_realized_pnl("A", 10)
        c.maybe_expand("A")

        c.record_realized_pnl("B", -7.5)
        self.assertAlmostEqual(c.treasury.balance("B"), 2.5)
        returned = c.enforce_stop_floor("B", positions_flat=True)
        self.assertAlmostEqual(returned, 2.5)
        self.assertEqual(c.registry.get("B").status.value, "retired")
        self.assertAlmostEqual(c.treasury.reserve, 2.5)
        self.assertAlmostEqual(c.treasury.balance("A"), 10)
        self.assertAlmostEqual(c.treasury.company_equity, 12.5)

    def test_settlement_refuses_open_positions(self):
        c = self.company
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.bootstrap(assign_best=True)
        with self.assertRaises(CapitalAllocationError):
            c.retire_trader("A", positions_flat=False)
        self.assertEqual(c.treasury.balance("A"), 10)
        self.assertIn("A", c.market.assignments)
        self.assertEqual(
            c.opportunities.get("btc").reserved_by,
            "A",
        )

    def test_effective_limit_cannot_exceed_operational_cap(self):
        c = self.company
        control = CompanyControlPort(c)
        self.assertEqual(
            control.set_effective_trader_limit(3)["effective_trader_limit"],
            3,
        )
        with self.assertRaises(Exception):
            control.set_effective_trader_limit(7)


class MarketAllocationTests(unittest.TestCase):
    def test_production_reserves_whole_symbol(self):
        _, adapter = engine()
        policy = CompanyPolicy(initial_company_capital=30)
        c = TradeCompany(adapter, policy)
        c.publish_opportunity(opportunity("btc-long", "BTCUSDT", 100))
        c.publish_opportunity(
            opportunity("btc-short", "BTCUSDT", 99, direction="short")
        )
        c.publish_opportunity(opportunity("eth-long", "ETHUSDT", 90))

        a = c.bootstrap()
        b = c.capital.create_funded_trader()
        c.assign_best(a.id)
        c.assign_best(b.id)

        self.assertEqual(a.market, "BTCUSDT")
        self.assertEqual(b.market, "ETHUSDT")
        self.assertNotEqual(a.market, b.market)

    def test_training_can_share_market_and_opportunity(self):
        _, adapter = engine()
        policy = CompanyPolicy(initial_company_capital=20)
        c = TradeCompany(adapter, policy)
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))

        a = c.bootstrap(mode=TraderMode.TRAINING)
        b = c.capital.create_funded_trader(mode=TraderMode.TRAINING)
        c.assign_best(a.id)
        c.assign_best(b.id)

        self.assertEqual(a.market, "BTCUSDT")
        self.assertEqual(b.market, "BTCUSDT")
        self.assertEqual(
            c.market.assignments["A"].opportunity_id,
            c.market.assignments["B"].opportunity_id,
        )

    def test_expired_opportunity_is_not_assignable(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        c.publish_opportunity(
            opportunity("btc", "BTCUSDT", 100, expires_at=10)
        )
        a = c.bootstrap()
        with self.assertRaises(MarketAllocationError):
            c.assign_best(a.id, now=10)


class CompanyRiskTests(unittest.TestCase):
    def test_trade_cap_tracks_current_trader_equity(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.bootstrap(assign_best=True)

        self.assertAlmostEqual(c.risk.max_trade_notional("A"), 2.0)
        c.risk.validate("A", symbol="BTCUSDT", notional=2.0)
        with self.assertRaises(CompanyRiskViolation):
            c.risk.validate("A", symbol="BTCUSDT", notional=2.01)

        c.record_realized_pnl("A", 10.0)
        self.assertAlmostEqual(c.treasury.balance("A"), 20.0)
        self.assertAlmostEqual(c.risk.max_trade_notional("A"), 4.0)

        c.record_realized_pnl("A", -10.0)
        self.assertAlmostEqual(c.treasury.balance("A"), 10.0)
        self.assertAlmostEqual(c.risk.max_trade_notional("A"), 2.0)

    def test_trader_can_request_less_than_its_exposure_ceiling(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.bootstrap(assign_best=True)

        out = c.configure_trader_exposure(
            "A",
            max_trade_exposure_pct=20,
            trade_exposure_pct=8,
        )
        self.assertAlmostEqual(out["max_trade_notional"], 2.0)
        self.assertAlmostEqual(out["requested_trade_notional"], 0.8)

        c.record_realized_pnl("A", 10)
        self.assertAlmostEqual(c.risk.max_trade_notional("A"), 4.0)
        self.assertAlmostEqual(c.risk.requested_trade_notional("A"), 1.6)

    def test_company_kill_allows_risk_reducing_action_only(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        c.publish_opportunity(opportunity("btc", "BTCUSDT", 100))
        c.bootstrap(assign_best=True)
        c.risk.kill()
        with self.assertRaises(CompanyRiskViolation):
            c.risk.validate("A", symbol="BTCUSDT", notional=1)
        c.risk.validate(
            "A",
            symbol="BTCUSDT",
            notional=1,
            risk_reducing=True,
        )


class CAOSIntegrationTests(unittest.TestCase):
    def test_market_scout_uses_shared_caos_market_regime(self):
        caos, adapter = engine()
        bars = synthetic_bars(200)
        adapter.load_bars("BTCUSDT", bars)
        c = TradeCompany(adapter)

        found = c.scout.discover_and_publish(
            "BTCUSDT",
            direction="long",
            opportunity_id="scan-btc",
        )
        self.assertEqual(found.symbol, "BTCUSDT")
        self.assertEqual(found.status.value, "available")
        self.assertIn(found.regime, {"trend_up", "trend_down", "range"})
        self.assertGreaterEqual(found.score, 0)
        self.assertLessEqual(found.score, 100)
        self.assertIn("BTCUSDT", caos.market_data)

    def test_training_arena_reuses_caos_quant_stack(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        bars = synthetic_bars(500)
        experiment = c.training.run(
            "BTCUSDT",
            bars,
            [
                TrainingVariant(
                    "trend",
                    StrategySpec("trend", "trend", 5, 34),
                ),
                TrainingVariant(
                    "momentum",
                    StrategySpec(
                        "mom",
                        "momentum",
                        5,
                        34,
                        threshold=0.5,
                    ),
                ),
            ],
            starting_capital=10,
            cost_bps=8,
        )
        self.assertEqual(experiment.symbol, "BTCUSDT")
        self.assertEqual(len(experiment.results), 2)
        self.assertEqual(
            {r["variant"] for r in experiment.results},
            {"trend", "momentum"},
        )

    def test_supervisor_and_improvement_surface_unassigned_trader(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        c.bootstrap()
        audit = c.audit()
        kinds = {row["kind"] for row in audit["alerts"]}
        self.assertIn("funded_trader_unassigned", kinds)
        proposals = c.improvement_proposals()
        self.assertTrue(
            any(p["kind"] == "assign_market" for p in proposals)
        )

    def test_control_port_has_no_broker_execution_surface(self):
        _, adapter = engine()
        c = TradeCompany(adapter)
        control = CompanyControlPort(c)
        self.assertFalse(hasattr(control, "place_order"))
        self.assertFalse(hasattr(control, "set_broker_credentials"))
        self.assertFalse(hasattr(control, "arm_live"))


if __name__ == "__main__":
    unittest.main()
