import tempfile
import unittest
from pathlib import Path

from caos.cli import synthetic_bars
from caos.domain import Mandate, StrategySpec
from caos.llm import StaticLLM
from caos.marketdata import BybitPublicClient
from caos.orchestrator import CAOS
from caos.portfolio import build_portfolio
from caos.quant import backtest, current_signal, robustness
from caos.runner import PaperRunner
from caos.store import Store


class FakeBybit(BybitPublicClient):
    def _get_json(self, path, params):
        return {
            "retCode": 0,
            "result": {
                "list": [
                    ["2000", "11", "12", "10", "11.5", "20", "0"],
                    ["1000", "10", "11", "9", "10.5", "10", "0"],
                ]
            },
        }


class ExtendedTests(unittest.TestCase):
    def test_bybit_parser_sorts_bars(self):
        bars = FakeBybit().klines("BTCUSDT", limit=2)
        self.assertEqual([b.ts for b in bars], [1000, 2000])
        self.assertEqual(bars[-1].close, 11.5)

    def test_store_round_trip_and_events(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "x.db")
            s.set_json("mandate", {"capital": 10})
            self.assertEqual(s.get_json("mandate")["capital"], 10)
            s.event("test", {"ok": True})
            self.assertEqual(s.recent_events(1)[0]["kind"], "test")
            s.close()

    def test_portfolio_and_runner(self):
        bars = synthetic_bars(500)
        mandate = Mandate(1000, 50, max_position_pct=20)
        approved = []
        for fast, slow in [(3, 21), (5, 34), (8, 55)]:
            spec = StrategySpec(f"s{fast}", "trend", fast, slow)
            bt = backtest(spec, bars)
            rb = robustness(spec, bars, mandate)
            if rb.passed:
                approved.append((spec, bt, rb))
        self.assertTrue(approved)
        portfolio = build_portfolio({"DEMOUSDT": approved}, max_entries=3)
        self.assertEqual(len(portfolio), 1)
        self.assertAlmostEqual(portfolio[0].weight, 1.0)

        c = CAOS(StaticLLM('{"tool":"status","args":{}}'))
        c.set_mandate(mandate)
        c.load_bars("DEMOUSDT", bars)
        result = PaperRunner(c).cycle(portfolio)
        self.assertEqual(len(result.actions) + len(result.skipped), 1)

    def test_current_signal_shape(self):
        sig = current_signal(
            StrategySpec("x", "trend", 3, 21),
            synthetic_bars(100),
        )
        self.assertIn(sig, {"long", "flat"})


class OrchestratorExtendedTests(unittest.TestCase):
    def test_orchestrator_public_data_to_portfolio_flow(self):
        c = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            market_client=FakeBybit(),
        )
        c.set_mandate(Mandate(1000, 50))
        fetched = c.tool_fetch_market("BTCUSDT", limit=2)
        self.assertEqual(fetched["bars"], 2)
        self.assertIn("BTCUSDT", c.market_data)

    def test_build_portfolio_empty_is_valid(self):
        c = CAOS(StaticLLM('{"tool":"status","args":{}}'))
        c.set_mandate(Mandate(1000, 20))
        out = c.tool_build_portfolio()
        self.assertEqual(out["entries"], 0)
        cycle = c.tool_paper_cycle()
        self.assertEqual(cycle["actions"], [])


if __name__ == "__main__":
    unittest.main()


from caos.desks import DeskCouncil
from caos.daemon import PaperDaemon


class SequenceLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, system, user):
        return self.responses.pop(0)


class AgentAndGoalTests(unittest.TestCase):
    def test_desk_tool_boundary(self):
        good = StaticLLM(
            '{"assessment":"ok","risks":[],"recommendations":[],"suggested_tool":"status"}'
        )
        out = DeskCouncil(good).consult(
            "risk",
            {"x": 1},
            "audit",
        )
        self.assertEqual(out["desk"], "RISK")

        bad = StaticLLM(
            '{"assessment":"x","risks":[],"recommendations":[],"suggested_tool":"paper_order"}'
        )
        with self.assertRaises(ValueError):
            DeskCouncil(bad).consult(
                "risk",
                {},
                "trade",
            )

    def test_goal_loop_finishes(self):
        llm = SequenceLLM(
            [
                '{"tool":"status","args":{}}',
                '{"finish":{"summary":"status inspected"}}',
            ]
        )
        c = CAOS(llm)
        c.set_mandate(Mandate(1000, 20))
        out = c.run_goal(
            "inspect system",
            max_steps=3,
        )
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["steps"], 1)

    def test_daemon_refreshes_portfolio_symbols(self):
        bars = synthetic_bars(500)
        mandate = Mandate(1000, 50)
        spec = StrategySpec(
            "s",
            "trend",
            3,
            21,
        )
        bt = backtest(spec, bars)
        rb = robustness(
            spec,
            bars,
            mandate,
        )
        self.assertTrue(rb.passed)

        c = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            market_client=FakeBybit(),
        )
        c.set_mandate(mandate)
        c.candidate_bank = {
            "BTCUSDT": [(spec, bt, rb)]
        }
        c.tool_build_portfolio()
        cycle = PaperDaemon(
            c,
            candle_limit=2,
        ).run_once()
        self.assertEqual(
            cycle.refreshed["BTCUSDT"],
            2,
        )


from caos.cli import parser


class CLITests(unittest.TestCase):
    def test_goal_and_desk_commands_parse(self):
        a = parser().parse_args(
            [
                "--provider",
                "static",
                "goal",
                "inspect",
                "system",
            ]
        )
        self.assertEqual(a.cmd, "goal")
        self.assertEqual(a.max_steps, 8)

        b = parser().parse_args(
            [
                "--provider",
                "static",
                "desk",
                "risk",
                "audit",
            ]
        )
        self.assertEqual(b.cmd, "desk")
        self.assertEqual(b.name, "risk")



class GoalV2CLITests(unittest.TestCase):
    def test_models_command_parses(self):
        args = parser().parse_args(
            ["--provider", "static", "models"]
        )
        self.assertEqual(args.cmd, "models")

    def test_testnet_command_parses_without_secrets(self):
        args = parser().parse_args(
            [
                "--provider",
                "static",
                "testnet-order",
                "--confirm",
                "ARM TESTNET",
                "BTCUSDT",
                "Buy",
                "Limit",
                "0.001",
                "--price",
                "50000",
            ]
        )
        self.assertEqual(args.cmd, "testnet-order")
        self.assertEqual(args.confirm, "ARM TESTNET")
        self.assertFalse(hasattr(args, "api_secret"))

    def test_expert_commands_parse(self):
        args = parser().parse_args(
            [
                "--provider",
                "static",
                "--experts",
                "kronos,chronos2",
                "evaluate-expert",
                "BTCUSDT",
                "--expert",
                "kronos",
                "--horizon",
                "6",
            ]
        )
        self.assertEqual(args.cmd, "evaluate-expert")
        self.assertEqual(args.expert, "kronos")
