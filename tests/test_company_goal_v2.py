import tempfile
import unittest
from pathlib import Path

from caos.company import (
    CAOSAdapter,
    CompanyDaemon,
    CompanyPolicy,
    Opportunity,
    ScanTarget,
    TradeCompany,
)
from caos.company.capital import CapitalAllocationError
from caos.company.paper import CompanyPaperError
from caos.domain import Mandate, MarketBar, StrategySpec
from caos.llm import StaticLLM
from caos.marketdata import BybitPublicClient
from caos.orchestrator import CAOS
from caos.store import Store


def bars_up(n=160, start=100.0, step=0.5):
    out = []
    price = start
    for i in range(n):
        nxt = price + step
        out.append(
            MarketBar(
                ts=1_700_000_000_000 + i * 60_000,
                open=price,
                high=max(price, nxt) + 0.1,
                low=min(price, nxt) - 0.1,
                close=nxt,
                volume=1000,
            )
        )
        price = nxt
    return out


class FakeMarket(BybitPublicClient):
    def __init__(self, bad=None):
        super().__init__()
        self.bad = set(bad or [])
        self.data = {
            "BTCUSDT": bars_up(),
            "ETHUSDT": bars_up(start=50, step=0.2),
            "SOLUSDT": bars_up(start=20, step=0.1),
        }

    def klines(self, symbol, interval="60", limit=500, category="linear"):
        symbol = symbol.upper()
        if symbol in self.bad:
            raise RuntimeError("market_down")
        return list(self.data.get(symbol, bars_up()))[-int(limit):]


def make_company(
    *,
    capital=10.0,
    store=None,
    bad_markets=None,
):
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        market_client=FakeMarket(bad_markets),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    policy = CompanyPolicy(initial_company_capital=capital)
    return caos, TradeCompany(CAOSAdapter(caos), policy, store=store)


def publish(company, oid, symbol, score=100, strategies=("trend",), direction="long", expires_at=None):
    return company.publish_opportunity(
        Opportunity(
            id=oid,
            symbol=symbol,
            direction=direction,
            score=score,
            strategy_candidates=tuple(strategies),
            expires_at=expires_at,
        )
    )


class CompanyPersistenceGoalTests(unittest.TestCase):
    def test_checkpoint_restores_open_paper_position(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            caos, company = make_company(store=store)
            company.register_strategy(
                StrategySpec(
                    "mom",
                    "momentum",
                    3,
                    21,
                    threshold=0.5,
                )
            )
            publish(
                company,
                "btc",
                "BTCUSDT",
                strategies=("mom",),
            )
            company.bootstrap(assign_best=True)
            company.engine.load_bars("BTCUSDT", bars_up())

            cycle = company.paper.cycle_trader("A")
            self.assertEqual(cycle.action, "open_long")
            self.assertTrue(company.paper.has_open_position("A"))
            company.checkpoint()
            before_qty = (
                company.paper.accounts["A"]
                .positions["BTCUSDT"]
                .quantity
            )
            before_treasury = company.treasury.balance("A")

            caos2 = CAOS(
                StaticLLM('{"tool":"status","args":{}}'),
                market_client=FakeMarket(),
                store=store,
            )
            caos2.set_mandate(Mandate(1000, 50, max_position_pct=20))
            restored = TradeCompany(
                CAOSAdapter(caos2),
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertTrue(restored.paper.has_open_position("A"))
            self.assertAlmostEqual(
                restored.paper.accounts["A"]
                .positions["BTCUSDT"]
                .quantity,
                before_qty,
            )
            self.assertAlmostEqual(
                restored.treasury.balance("A"),
                before_treasury,
            )
            self.assertEqual(
                restored.paper.audit_reconciliation(),
                [],
            )

            restored.engine.load_bars("BTCUSDT", bars_up())
            self.assertGreater(
                restored.paper.marked_equity("A"),
                0,
            )
            store.close()

    def test_restore_fails_on_corrupt_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            _, company = make_company(store=store)
            company.register_strategy(
                StrategySpec("trend", "trend", 3, 21)
            )
            publish(company, "btc", "BTCUSDT")
            company.bootstrap(assign_best=True)
            company.engine.load_bars("BTCUSDT", bars_up())
            company.paper.cycle_trader("A")
            company.checkpoint()

            payload = store.get_json("trade_company_checkpoint_v1")
            payload["treasury"]["balances"]["TRADER:A"] += 1.0
            payload["treasury"]["company_equity"] += 1.0
            store.set_json("trade_company_checkpoint_v1", payload)

            _, restored = make_company(store=store)
            with self.assertRaises(Exception):
                restored.restore_checkpoint()
            store.close()


class CompanyRiskGoalTests(unittest.TestCase):
    def test_risk_uses_marked_equity_not_only_treasury(self):
        _, company = make_company()
        company.register_strategy(
            StrategySpec(
                "mom",
                "momentum",
                3,
                21,
                threshold=0.5,
            )
        )
        publish(
            company,
            "btc",
            "BTCUSDT",
            strategies=("mom",),
        )
        company.bootstrap(assign_best=True)
        company.engine.load_bars("BTCUSDT", bars_up())
        company.paper.cycle_trader("A")

        account = company.paper.accounts["A"]
        qty = account.positions["BTCUSDT"].quantity
        company.engine.load_bars(
            "BTCUSDT",
            [
                MarketBar(
                    ts=2_000_000_000_000,
                    open=50,
                    high=50,
                    low=50,
                    close=50,
                    volume=1000,
                )
            ],
        )
        marked = account.cash + qty * 50
        self.assertAlmostEqual(
            company.risk.max_trade_notional("A"),
            marked * 0.20,
        )
        self.assertGreater(company.risk.drawdown_pct(), 0)

    def test_exposure_reports_per_trader_and_symbol(self):
        _, company = make_company()
        company.register_strategy(
            StrategySpec(
                "mom",
                "momentum",
                3,
                21,
                threshold=0.5,
            )
        )
        publish(
            company,
            "btc",
            "BTCUSDT",
            strategies=("mom",),
        )
        company.bootstrap(assign_best=True)
        company.engine.load_bars("BTCUSDT", bars_up())
        company.paper.cycle_trader("A")

        exposure = company.paper.exposure()
        self.assertGreater(exposure["gross_notional"], 0)
        self.assertGreater(exposure["by_trader"]["A"], 0)
        self.assertGreater(exposure["by_symbol"]["BTCUSDT"], 0)
        audit = company.audit()
        self.assertIn("exposure", audit["metrics"])


class CompanyDaemonGoalTests(unittest.TestCase):
    def test_daemon_scans_assigns_and_runs_trader(self):
        _, company = make_company()
        company.register_strategy(
            StrategySpec("trend", "trend", 3, 21)
        )
        company.bootstrap()
        daemon = CompanyDaemon(
            company,
            [ScanTarget("BTCUSDT", "long", ("trend",))],
            candle_limit=160,
            opportunity_ttl_ms=100,
        )
        cycle = daemon.run_once(now=1000)

        self.assertEqual(cycle.refreshed["BTCUSDT"], 160)
        self.assertTrue(cycle.opportunities)
        self.assertTrue(cycle.assignments)
        self.assertEqual(company.registry.get("A").market, "BTCUSDT")
        self.assertTrue(
            any(row["trader_id"] == "A" for row in cycle.paper_actions)
        )

    def test_daemon_does_not_assign_unregistered_strategy(self):
        _, company = make_company()
        company.bootstrap()
        daemon = CompanyDaemon(
            company,
            [ScanTarget("BTCUSDT", "long", ("missing",))],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1000)
        self.assertEqual(cycle.assignments, [])
        self.assertEqual(
            company.registry.get("A").status.value,
            "waiting_assignment",
        )

    def test_daemon_expires_stale_unreserved_opportunity(self):
        _, company = make_company()
        daemon = CompanyDaemon(
            company,
            [ScanTarget("BTCUSDT", "long", ("trend",))],
            candle_limit=160,
            opportunity_ttl_ms=10,
        )
        first = daemon.run_once(now=100)
        old_id = first.opportunities[0]
        second = daemon.run_once(now=111)
        self.assertIn(old_id, second.expired)
        self.assertEqual(
            company.opportunities.get(old_id).status.value,
            "expired",
        )

    def test_market_failure_is_isolated(self):
        _, company = make_company(bad_markets={"ETHUSDT"})
        company.register_strategy(
            StrategySpec("trend", "trend", 3, 21)
        )
        company.bootstrap()
        daemon = CompanyDaemon(
            company,
            [
                ScanTarget("BTCUSDT", "long", ("trend",)),
                ScanTarget("ETHUSDT", "long", ("trend",)),
            ],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1000)
        self.assertIn("BTCUSDT", cycle.refreshed)
        self.assertIn("market:ETHUSDT", cycle.errors)
        self.assertEqual(company.registry.get("A").market, "BTCUSDT")

    def test_trader_failure_is_isolated(self):
        _, company = make_company(capital=20)
        company.register_strategy(
            StrategySpec("trend", "trend", 3, 21)
        )
        publish(company, "btc", "BTCUSDT", 100, ("trend",), "long")
        publish(company, "eth", "ETHUSDT", 90, ("trend",), "short")
        a = company.bootstrap()
        b = company.capital.create_funded_trader()
        company.market.assign(a.id, "btc", strategy_id="trend")
        company.market.assign(b.id, "eth", strategy_id="trend")

        daemon = CompanyDaemon(
            company,
            [
                ScanTarget("BTCUSDT", "long", ("trend",)),
                ScanTarget("ETHUSDT", "short", ("trend",)),
            ],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1000)
        self.assertIn("paper:B", cycle.errors)
        self.assertTrue(
            any(row["trader_id"] == "A" for row in cycle.paper_actions)
        )

    def test_stop_floor_flattens_and_retires(self):
        _, company = make_company()
        company.register_strategy(
            StrategySpec("trend", "trend", 3, 21)
        )
        publish(company, "btc", "BTCUSDT")
        company.bootstrap(assign_best=True)
        company.record_realized_pnl("A", -7.5)

        daemon = CompanyDaemon(
            company,
            [ScanTarget("BTCUSDT", "long", ("trend",))],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1000)
        self.assertTrue(
            any(row["trader_id"] == "A" for row in cycle.retirements)
        )
        self.assertEqual(
            company.registry.get("A").status.value,
            "retired",
        )
        self.assertGreater(company.treasury.reserve, 0)


class CompanyExpansionGoalTests(unittest.TestCase):
    def test_expansion_is_blocked_while_trigger_has_open_position(self):
        _, company = make_company()
        company.register_strategy(
            StrategySpec(
                "mom",
                "momentum",
                3,
                21,
                threshold=0.5,
            )
        )
        publish(
            company,
            "btc",
            "BTCUSDT",
            100,
            strategies=("mom",),
        )
        publish(
            company,
            "eth",
            "ETHUSDT",
            90,
            strategies=("mom",),
        )
        company.bootstrap(assign_best=True)
        company.record_realized_pnl("A", 10)
        company.engine.load_bars("BTCUSDT", bars_up())
        company.paper.cycle_trader("A")

        decision = company.maybe_expand("A")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "trigger_trader_not_flat")
        self.assertEqual(company.registry.slot_count(), 1)

    def test_expansion_rollback_preserves_company_equity(self):
        _, company = make_company()
        publish(company, "btc", "BTCUSDT", 100)
        publish(company, "eth", "ETHUSDT", 90)
        company.bootstrap(assign_best=True)
        company.record_realized_pnl("A", 10)
        before = company.treasury.company_equity

        original_assign = company.market.assign

        def fail_for_b(trader_id, *args, **kwargs):
            if trader_id == "B":
                raise RuntimeError("forced_assignment_failure")
            return original_assign(trader_id, *args, **kwargs)

        company.market.assign = fail_for_b
        with self.assertRaises(RuntimeError):
            company.maybe_expand("A")

        self.assertAlmostEqual(company.treasury.company_equity, before)
        self.assertAlmostEqual(company.treasury.balance("A"), 20)
        self.assertEqual(company.registry.get("B").status.value, "retired")

    def test_hard_six_slot_limit_cannot_be_exceeded(self):
        _, company = make_company(capital=70)
        company.bootstrap()
        for _ in range(5):
            company.capital.create_funded_trader()
        self.assertEqual(company.registry.slot_count(), 6)
        with self.assertRaises(CapitalAllocationError):
            company.capital.create_funded_trader()


if __name__ == "__main__":
    unittest.main()
