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
