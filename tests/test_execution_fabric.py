import tempfile
import unittest
from pathlib import Path

from caos.company import CAOSAdapter, TradeCompany
from caos.company.domain import Opportunity
from caos.company.standalone import build_policy
from caos.domain import Mandate, MarketBar, StrategySpec
from caos.execution_fabric import (
    EXECUTION_FABRIC_VERSION,
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.quant import (
    backtest_execution_trace,
    current_decision,
    execution_plan_series,
    target_position_series,
)
from caos.store import Store
from caos.testnet import (
    BinanceSpotClient,
    HumanTestnetExecutor,
    execution_plan_to_binance_order,
)


def rising_bars(n=90):
    bars = []
    price = 100.0
    for i in range(n):
        close = price + 1.0
        bars.append(
            MarketBar(
                i,
                price,
                close + 0.5,
                price - 0.5,
                close,
                1000.0,
            )
        )
        price = close
    return bars


class ExecutionFabricDomainTests(unittest.TestCase):
    def test_version_and_deterministic_decision_ids(self):
        self.assertEqual(
            EXECUTION_FABRIC_VERSION,
            "execution-fabric/v1",
        )
        a = decision_from_signal(
            symbol="btcusdt",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
            as_of=100,
        )
        b = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
            as_of=100,
        )
        self.assertEqual(a.decision_id, b.decision_id)
        self.assertEqual(a.symbol, "BTCUSDT")

    def test_plan_id_is_deterministic(self):
        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
            as_of=42,
        )
        target = resolve_target_position(
            decision,
            equity=10.0,
            max_notional=2.0,
        )
        a = plan_execution(
            target,
            current_notional=0.0,
            reference_price=100.0,
        )
        b = plan_execution(
            target,
            current_notional=0.0,
            reference_price=100.0,
        )
        self.assertEqual(a.plan_id, b.plan_id)

    def test_target_respects_requested_weight_and_hard_ceiling(self):
        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.20,
        )
        target = resolve_target_position(
            decision,
            equity=10.0,
            max_notional=1.5,
        )
        self.assertAlmostEqual(target.target_notional, 1.5)
        self.assertAlmostEqual(target.target_weight, 0.15)

    def test_planner_handles_increase_reduce_close_and_pause(self):
        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
        )
        target = resolve_target_position(
            decision,
            equity=10.0,
            max_notional=2.0,
        )
        inc = plan_execution(
            target,
            current_notional=0.0,
            reference_price=100.0,
        )
        self.assertEqual(inc.action, "increase")
        self.assertEqual(inc.side, "buy")
        self.assertAlmostEqual(inc.order_notional, 2.0)

        paused = plan_execution(
            target,
            current_notional=0.0,
            reference_price=100.0,
            allow_new_risk=False,
        )
        self.assertEqual(paused.action, "hold")
        self.assertFalse(paused.executable)

        reduce = plan_execution(
            target,
            current_notional=3.0,
            reference_price=100.0,
        )
        self.assertEqual(reduce.action, "reduce")
        self.assertTrue(reduce.risk_reducing)
        self.assertAlmostEqual(reduce.order_notional, 1.0)

        flat_decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="flat",
            requested_weight=0.0,
        )
        flat = resolve_target_position(
            flat_decision,
            equity=10.0,
            max_notional=2.0,
        )
        close = plan_execution(
            flat,
            current_notional=2.0,
            reference_price=100.0,
        )
        self.assertEqual(close.action, "close")
        self.assertEqual(close.side, "sell")

    def test_research_target_series_uses_same_target_schema(self):
        spec = StrategySpec(
            "mom",
            "momentum",
            3,
            21,
            threshold=0.5,
        )
        bars = rising_bars()
        targets = target_position_series(
            spec,
            bars,
            symbol="BTCUSDT",
            requested_weight=0.2,
            equity=10.0,
            max_notional=2.0,
        )
        decision = current_decision(
            spec,
            bars,
            symbol="BTCUSDT",
            requested_weight=0.2,
        )
        self.assertEqual(len(targets), len(bars))
        self.assertEqual(
            targets[-1].side,
            decision.signal,
        )
        self.assertAlmostEqual(
            targets[-1].target_notional,
            2.0 if decision.signal == "long" else 0.0,
        )

    def test_research_execution_trace_uses_same_planner(self):
        spec = StrategySpec(
            "mom",
            "momentum",
            3,
            21,
            threshold=0.5,
        )
        bars = rising_bars()
        plans = execution_plan_series(
            spec,
            bars,
            symbol="BTCUSDT",
            requested_weight=0.2,
            equity=10.0,
            max_notional=2.0,
        )
        self.assertEqual(len(plans), len(bars))
        self.assertTrue(
            any(plan.action == "increase" for plan in plans)
        )
        self.assertTrue(
            all(
                plan.symbol == "BTCUSDT"
                and plan.strategy_id == "mom"
                for plan in plans
            )
        )


    def test_exact_backtest_trace_maps_entries_and_exits(self):
        spec = StrategySpec(
            "mom",
            "momentum",
            3,
            21,
            threshold=0.5,
            take_profit_pct=2.0,
        )
        trace = backtest_execution_trace(
            spec,
            rising_bars(),
            symbol="BTCUSDT",
            requested_weight=0.2,
            equity=10.0,
            max_notional=2.0,
            cost_bps=0.0,
        )
        trades = trace["backtest"]["trades"]
        self.assertGreater(trades, 0)
        self.assertEqual(len(trace["events"]), trades * 2)
        for i in range(0, len(trace["events"]), 2):
            self.assertEqual(
                trace["events"][i]["plan"]["action"],
                "increase",
            )
            self.assertEqual(
                trace["events"][i + 1]["plan"]["action"],
                "close",
            )
            self.assertTrue(
                trace["events"][i + 1]["plan"][
                    "risk_reducing"
                ]
            )



class CompanyExecutionFabricTests(unittest.TestCase):
    def make_company(self, directory):
        store = Store(Path(directory) / "fabric.db")
        caos = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            store=store,
        )
        caos.set_mandate(
            Mandate(1000, 50, max_position_pct=20)
        )
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
                "mom",
                "momentum",
                3,
                21,
                threshold=0.5,
            )
        )
        company.publish_opportunity(
            Opportunity(
                "btc",
                "BTCUSDT",
                "long",
                100,
                strategy_candidates=("mom",),
            )
        )
        company.bootstrap(
            assign_best=True,
            max_trade_exposure_pct=20,
            trade_exposure_pct=20,
        )
        company.engine.load_bars("BTCUSDT", rising_bars())
        return store, company

    def test_company_cycle_records_decision_target_and_plan(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            cycle = company.paper.cycle_trader("A")
            self.assertEqual(cycle.action, "open_long")
            self.assertEqual(cycle.decision["signal"], "long")
            self.assertEqual(cycle.target["side"], "long")
            self.assertEqual(cycle.plan["action"], "increase")
            self.assertTrue(cycle.plan["executable"])
            self.assertEqual(
                company.paper.last_plans["A"]["plan_id"],
                cycle.plan["plan_id"],
            )
            store.close()

    def test_company_rebalances_by_delta_without_close_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            opened = company.paper.cycle_trader("A")
            self.assertEqual(opened.action, "open_long")
            fills_before = len(
                company.paper.accounts["A"].fills
            )

            company.configure_trader_exposure(
                "A",
                max_trade_exposure_pct=20,
                trade_exposure_pct=10,
            )
            reduced = company.paper.cycle_trader("A")
            self.assertEqual(reduced.action, "reduce_long")
            self.assertEqual(reduced.plan["action"], "reduce")
            self.assertTrue(reduced.plan["risk_reducing"])
            self.assertEqual(
                len(company.paper.accounts["A"].fills),
                fills_before + 1,
            )
            self.assertFalse(
                company.paper.positions_flat("A")
            )
            store.close()

    def test_paused_trader_can_be_force_flattened(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            opened = company.paper.cycle_trader("A")
            self.assertEqual(opened.action, "open_long")
            company.pause_trader("A")
            flattened = company.paper.force_flatten("A")
            self.assertEqual(flattened.action, "forced_flatten")
            self.assertTrue(
                flattened.plan["risk_reducing"]
            )
            self.assertTrue(
                company.paper.positions_flat("A")
            )
            store.close()


    def test_execution_plans_survive_checkpoint_restore(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            cycle = company.paper.cycle_trader("A")
            plan_id = cycle.plan["plan_id"]
            company.checkpoint()

            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.paper.last_plans["A"]["plan_id"],
                plan_id,
            )
            store.close()

    def test_old_checkpoint_without_last_plans_restores(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            company.paper.cycle_trader("A")
            company.checkpoint()
            payload = store.get_json(
                "trade_company_checkpoint_v1"
            )
            payload["paper"].pop("last_plans", None)
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
            self.assertEqual(restored.paper.last_plans, {})
            store.close()

    def test_halted_trader_can_be_force_flattened(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = self.make_company(d)
            opened = company.paper.cycle_trader("A")
            self.assertEqual(opened.action, "open_long")
            company.registry.halt("A")
            flattened = company.paper.force_flatten("A")
            self.assertEqual(flattened.action, "forced_flatten")
            self.assertTrue(flattened.plan["risk_reducing"])
            self.assertTrue(company.paper.positions_flat("A"))
            store.close()



class TestnetExecutionFabricTests(unittest.TestCase):
    def test_plan_maps_to_testnet_order_without_credentials(self):
        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
            as_of=1,
        )
        target = resolve_target_position(
            decision,
            equity=100.0,
            max_notional=20.0,
        )
        plan = plan_execution(
            target,
            current_notional=0.0,
            reference_price=50_000.0,
        )
        payload = execution_plan_to_binance_order(plan)
        self.assertEqual(payload["side"], "BUY")
        self.assertEqual(payload["symbol"], "BTCUSDT")
        self.assertEqual(
            payload["order_link_id"],
            plan.plan_id[:36],
        )

    def test_binance_spot_rejects_non_reducing_sell_plan(self):
        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="flat",
            requested_weight=0.0,
            as_of=1,
        )
        target = resolve_target_position(
            decision,
            equity=100.0,
            max_notional=20.0,
        )
        # A synthetic inconsistent current exposure can create a reducing
        # SELL, which is valid.
        reducing = plan_execution(
            target,
            current_notional=20.0,
            reference_price=50_000.0,
        )
        payload = execution_plan_to_binance_order(
            reducing
        )
        self.assertEqual(payload["side"], "SELL")

        from dataclasses import replace
        unsafe = replace(
            reducing,
            risk_reducing=False,
        )
        from caos.testnet import TestnetError
        with self.assertRaises(TestnetError):
            execution_plan_to_binance_order(unsafe)

    def test_human_gated_executor_can_execute_same_plan(self):
        captured = {}

        def transport(method, url, data, headers):
            import urllib.parse
            del headers
            captured["method"] = method
            captured["url"] = url
            captured["body"] = dict(
                urllib.parse.parse_qsl(
                    data.decode()
                )
            )
            return {
                "orderId": "plan-order",
                "clientOrderId": captured["body"].get(
                    "newClientOrderId",
                    "",
                ),
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "origQty": captured["body"].get(
                    "quantity",
                    "",
                ),
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
                "status": "NEW",
            }

        decision = decision_from_signal(
            symbol="BTCUSDT",
            strategy_id="mom",
            signal="long",
            requested_weight=0.2,
            as_of=1,
        )
        target = resolve_target_position(
            decision,
            equity=100.0,
            max_notional=20.0,
        )
        plan = plan_execution(
            target,
            current_notional=0.0,
            reference_price=50_000.0,
        )

        from caos.compliance import ComplianceEngine, ComplianceViolation
        compliance = ComplianceEngine()
        client = BinanceSpotClient(
            "key",
            "secret",
            transport=transport,
        )
        executor = HumanTestnetExecutor(compliance, client)

        with self.assertRaises(ComplianceViolation):
            executor.execute_plan(plan)

        compliance.human_arm_testnet(
            confirmation="ARM TESTNET"
        )
        ack = executor.execute_plan(plan)
        self.assertEqual(ack.order_id, "plan-order")
        self.assertEqual(
            captured["body"]["newClientOrderId"],
            plan.plan_id[:36],
        )


if __name__ == "__main__":
    unittest.main()
