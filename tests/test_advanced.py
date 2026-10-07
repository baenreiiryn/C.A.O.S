import tempfile
import unittest
from pathlib import Path

from caos.broker import PaperBroker
from caos.daemon import PaperDaemon
from caos.domain import (
    BacktestResult,
    Mandate,
    MarketBar,
    OrderRequest,
    StrategySpec,
)
from caos.execution import estimate_execution_cost
from caos.llm import StaticLLM
from caos.marketdata import BybitPublicClient
from caos.news import NewsAnalyzer, RSSNewsClient
from caos.orchestrator import CAOS
from caos.portfolio import build_portfolio
from caos.quant import RobustnessResult, backtest, current_signal
from caos.risk import RiskEngine, RiskViolation
from caos.state import RuntimeCheckpoint
from caos.store import Store
from caos.supervisor import audit_portfolio


def bars_up(n=160, step=0.5):
    out = []
    p = 100.0
    for i in range(n):
        nxt = p + step
        out.append(
            MarketBar(
                ts=1_700_000_000_000 + i * 60_000,
                open=p,
                high=max(p, nxt) + 0.2,
                low=min(p, nxt) - 0.2,
                close=nxt,
                volume=1000,
            )
        )
        p = nxt
    return out


class CostBybit(BybitPublicClient):
    def _get_json(self, path, params):
        if path.endswith("orderbook"):
            return {
                "retCode": 0,
                "result": {
                    "s": "BTCUSDT",
                    "b": [["99", "2"], ["98", "10"]],
                    "a": [["101", "1"], ["102", "10"]],
                    "ts": 123,
                },
            }
        raise AssertionError(path)


class FlakyMarket:
    def klines(self, symbol, interval, limit, category):
        if symbol == "BADUSDT":
            raise RuntimeError("network")
        return bars_up(120)


class FakeRSS(RSSNewsClient):
    def _get(self, url):
        return b"""<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Bitcoin adoption rises</title>
            <link>https://example.test/a</link>
            <description>Institutional demand increased.</description>
            <pubDate>Wed, 07 Oct 2026 10:00:00 GMT</pubDate>
          </item>
          <item>
            <title>Bitcoin adoption rises</title>
            <link>https://example.test/a</link>
            <description>duplicate</description>
          </item>
        </channel></rss>"""


class FakeSentiment:
    name = "fake-finbert"

    def classify(self, text):
        class R:
            def to_dict(self):
                return {
                    "model": "fake-finbert",
                    "label": "POSITIVE",
                    "score": 0.9,
                    "signed_score": 0.9,
                }
        return R()


class AdvancedCoreTests(unittest.TestCase):
    def test_multiple_strategy_families_run(self):
        bars = bars_up(200)
        specs = [
            StrategySpec("trend", "trend", 5, 21),
            StrategySpec(
                "meanrev",
                "mean_reversion",
                5,
                20,
                threshold=1.5,
            ),
            StrategySpec(
                "breakout",
                "breakout",
                5,
                20,
                threshold=0,
            ),
            StrategySpec(
                "momentum",
                "momentum",
                5,
                20,
                threshold=0.5,
            ),
        ]
        for spec in specs:
            result = backtest(spec, bars, cost_bps=0)
            self.assertEqual(result.strategy, spec.name)
            self.assertIn(current_signal(spec, bars), {"long", "flat"})

    def test_correlation_gate_rejects_duplicate_return_stream(self):
        bars = bars_up(200)
        rb = RobustnessResult(True, 1.0, 2.0, 1.5, [])
        s1 = StrategySpec("a", "momentum", 5, 20, threshold=0.5)
        s2 = StrategySpec("b", "momentum", 5, 20, threshold=0.5)
        bt1 = BacktestResult("a", 10, 10, 60, 1.5, 5, 1, [1, 1.1], [])
        bt2 = BacktestResult("b", 10, 9, 60, 1.4, 5, 1, [1, 1.09], [])
        p = build_portfolio(
            {
                "AAA": [(s1, bt1, rb)],
                "BBB": [(s2, bt2, rb)],
            },
            max_entries=2,
            one_per_symbol=False,
            market_data={"AAA": bars, "BBB": bars},
            max_correlation=0.5,
            cost_bps=0,
        )
        self.assertEqual(len(p), 1)

    def test_orderbook_cost_uses_depth(self):
        c = estimate_execution_cost(
            bids=[[99, 2], [98, 10]],
            asks=[[101, 1], [102, 10]],
            side="buy",
            notional=202,
            fee_bps=5,
        )
        self.assertTrue(c.liquidity_sufficient)
        self.assertGreater(c.market_impact_bps, c.spread_bps / 2)
        self.assertGreater(c.roundtrip_cost_bps, 10)

    def test_public_orderbook_parser(self):
        book = CostBybit().orderbook("BTCUSDT", limit=2)
        self.assertEqual(book["bids"][0], [99.0, 2.0])
        self.assertEqual(book["asks"][0], [101.0, 1.0])

    def test_realized_pnl_accounting(self):
        risk = RiskEngine(Mandate(1000, 30, max_position_pct=50))
        broker = PaperBroker(risk, fee_bps=0)
        broker.execute(OrderRequest("BTC", "buy", 100, 50, "s"))
        self.assertAlmostEqual(broker.positions["BTC"].quantity, 2.0)
        broker.execute(OrderRequest("BTC", "sell", 110, 55, "s"))
        self.assertAlmostEqual(broker.cash, 1010.0)
        self.assertAlmostEqual(
            broker.realized_trades[-1]["pnl"],
            10.0,
        )
        self.assertAlmostEqual(
            broker.realized_trades[-1]["pnl_pct"],
            10.0,
        )

    def test_kill_switch_allows_exit_but_not_new_risk(self):
        risk = RiskEngine(Mandate(1000, 30, max_position_pct=50))
        broker = PaperBroker(risk, fee_bps=0)
        broker.execute(OrderRequest("BTC", "buy", 100, 50, "s"))
        risk.kill()
        with self.assertRaises(RiskViolation):
            broker.execute(OrderRequest("ETH", "buy", 10, 10, "s"))
        broker.execute(OrderRequest("BTC", "sell", 100, 50, "s"))
        self.assertEqual(broker.positions["BTC"].quantity, 0)

    def test_pending_limit_is_symbol_scoped(self):
        risk = RiskEngine(Mandate(1000, 30, max_position_pct=50))
        broker = PaperBroker(risk, fee_bps=0)
        order = broker.place_pending(
            "BTC",
            "buy",
            100,
            "limit",
            99,
            "s",
        )
        eth_bar = MarketBar(1, 100, 110, 90, 100, 1)
        self.assertEqual(broker.process_bar("ETH", eth_bar), [])
        self.assertEqual(order.status, "open")
        fills = broker.process_bar("BTC", eth_bar)
        self.assertEqual(len(fills), 1)
        self.assertEqual(order.status, "filled")

    def test_checkpoint_restores_portfolio_and_paper(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "state.db")
            c = CAOS(
                StaticLLM('{"tool":"status","args":{}}'),
                store=store,
            )
            c.set_mandate(Mandate(1000, 30, max_position_pct=50))
            c.paper.execute(OrderRequest("BTC", "buy", 100, 50, "s"))
            c.execution_costs["BTC"] = 12.0
            RuntimeCheckpoint.save(c, store)

            restored = CAOS(
                StaticLLM('{"tool":"status","args":{}}'),
                store=store,
            )
            self.assertTrue(RuntimeCheckpoint.restore(restored, store))
            self.assertAlmostEqual(restored.paper.cash, 899.95)
            self.assertAlmostEqual(
                restored.paper.positions["BTC"].quantity,
                2.0,
            )
            self.assertEqual(restored.execution_costs["BTC"], 12.0)
            store.close()

    def test_news_feed_dedup_and_sentiment(self):
        client = FakeRSS(["https://feed.test/rss"])
        analyzer = NewsAnalyzer(client, FakeSentiment())
        out = analyzer.latest(limit=10, query="Bitcoin")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["aggregate_sentiment"], 0.9)

    def test_supervisor_surfaces_divergence(self):
        c = CAOS(StaticLLM('{"tool":"status","args":{}}'))
        c.set_mandate(Mandate(1000, 30))
        spec = StrategySpec("s", "trend", 3, 21)
        rb = RobustnessResult(True, 1.0, 1.0, 1.5, [])
        expected = BacktestResult(
            "s",
            20,
            20,
            80,
            3.0,
            5,
            1,
            [1, 1.2],
            [],
        )
        from caos.portfolio import PortfolioEntry
        c.portfolio = [
            PortfolioEntry("BTC", spec, 1, 1, expected, rb)
        ]
        c.paper.realized_trades = [
            {
                "symbol": "BTC",
                "strategy": "s",
                "pnl_pct": x,
                "pnl": x,
            }
            for x in [-1, -1, -1, -1, 0.1, -1]
        ]
        out = audit_portfolio(c)
        self.assertIn(out["status"], {"watch", "alert"})
        self.assertTrue(out["reports"])


class FaultIsolationTests(unittest.TestCase):
    def test_daemon_skips_failed_symbol(self):
        c = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            market_client=FlakyMarket(),
        )
        c.set_mandate(Mandate(1000, 50))
        rb = RobustnessResult(True, 1.0, 1.0, 1.5, [])
        bt = BacktestResult("s", 5, 5, 60, 1.5, 2, 1, [1, 1.05], [])
        from caos.portfolio import PortfolioEntry
        c.portfolio = [
            PortfolioEntry(
                "GOODUSDT",
                StrategySpec("g", "trend", 3, 21),
                1,
                0.5,
                bt,
                rb,
            ),
            PortfolioEntry(
                "BADUSDT",
                StrategySpec("b", "trend", 3, 21),
                1,
                0.5,
                bt,
                rb,
            ),
        ]
        out = PaperDaemon(c, candle_limit=100).run_once()
        self.assertIn("GOODUSDT", out.refreshed)
        self.assertIn("BADUSDT", out.errors)


if __name__ == "__main__":
    unittest.main()
