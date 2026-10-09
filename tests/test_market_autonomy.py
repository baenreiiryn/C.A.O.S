import tempfile
import unittest
from pathlib import Path

from caos.company import CAOSAdapter, TradeCompany
from caos.company.autonomy import AutonomousMarketScanner
from caos.company.standalone import (
    build_policy,
    initialize_company,
    parse_scan_targets,
    register_all_builtin_strategies,
)
from caos.domain import Mandate, MarketBar
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.store import Store


def rising_bars(multiplier=1.0, count=180):
    rows = []
    price = 100.0 * multiplier
    for i in range(count):
        close = price * 1.0015
        rows.append(
            MarketBar(
                1_700_000_000_000 + i * 60_000,
                price,
                close * 1.001,
                price * 0.999,
                close,
                1000.0 + i,
            )
        )
        price = close
    return rows


class FakeAutoMarketClient:
    def __init__(self):
        self.calls = []

    def liquid_usdt_candidates(
        self,
        *,
        limit=10,
        min_quote_volume=5_000_000.0,
    ):
        del min_quote_volume
        rows = [
            {
                "symbol": "BTCUSDT",
                "last_price": 100.0,
                "price_change_pct": 2.0,
                "quote_volume": 900_000_000.0,
                "count": 100_000,
            },
            {
                "symbol": "ETHUSDT",
                "last_price": 50.0,
                "price_change_pct": 1.5,
                "quote_volume": 500_000_000.0,
                "count": 80_000,
            },
        ]
        return rows[:limit]

    def klines(self, symbol, interval, limit, category="spot"):
        del category
        self.calls.append((symbol, interval, limit))
        multiplier = 1.0 if symbol == "BTCUSDT" else 0.5
        return rising_bars(multiplier, count=limit)


class AutonomousMarketScannerTests(unittest.TestCase):
    def build_company(self, root):
        store = Store(Path(root) / "auto.db")
        client = FakeAutoMarketClient()
        caos = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            market_client=client,
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
        initialize_company(
            company,
            parse_scan_targets(
                "BTCUSDT:long:momentum"
            ),
        )
        register_all_builtin_strategies(company)
        return store, client, company

    def test_auto_scan_evaluates_market_timeframe_and_strategy(self):
        with tempfile.TemporaryDirectory() as d:
            store, client, company = self.build_company(d)
            scanner = AutonomousMarketScanner(
                company,
                timeframes=("1m", "5m", "15m"),
                candidate_limit=2,
                publish_limit=2,
                bars_limit=120,
            )
            created = scanner.scan(
                now=1_800_000_000_000,
                opportunity_ttl_ms=300_000,
            )
            self.assertEqual(len(created), 2)
            self.assertGreaterEqual(len(client.calls), 6)
            self.assertTrue(scanner.latest_rankings)
            first = company.opportunities.get(created[0])
            self.assertEqual(
                first.metadata["selection_mode"],
                "auto",
            )
            self.assertIn(
                first.metadata["timeframe"],
                {"1m", "5m", "15m"},
            )
            self.assertIn(
                first.metadata["strategy_id"],
                company.strategies.strategies,
            )
            self.assertEqual(
                first.strategy_candidates,
                (first.metadata["strategy_id"],),
            )
            store.close()

    def test_assignment_persists_autonomous_timeframe_on_trader(self):
        with tempfile.TemporaryDirectory() as d:
            store, _client, company = self.build_company(d)
            scanner = AutonomousMarketScanner(
                company,
                timeframes=("5m",),
                candidate_limit=1,
                publish_limit=1,
                bars_limit=120,
            )
            created = scanner.scan(
                now=1_800_000_000_000,
                opportunity_ttl_ms=300_000,
            )
            opportunity = company.opportunities.get(
                created[0]
            )
            company.market.assign(
                "A",
                opportunity.id,
                strategy_id=(
                    opportunity.strategy_candidates[0]
                ),
                now=1_800_000_000_001,
            )
            trader = company.registry.get("A")
            self.assertEqual(
                trader.metadata["selection_mode"],
                "auto",
            )
            self.assertEqual(
                trader.metadata["timeframe"],
                "5m",
            )
            store.close()

    def test_rescan_expires_stale_unclaimed_auto_opportunities(self):
        with tempfile.TemporaryDirectory() as d:
            store, _client, company = self.build_company(d)
            scanner = AutonomousMarketScanner(
                company,
                timeframes=("1m",),
                candidate_limit=1,
                publish_limit=1,
                bars_limit=120,
            )
            first = scanner.scan(
                now=1_800_000_000_000,
                opportunity_ttl_ms=600_000,
            )
            first_row = company.opportunities.get(first[0])
            self.assertEqual(
                first_row.status.value,
                "available",
            )
            second = scanner.scan(
                now=1_800_000_300_000,
                opportunity_ttl_ms=600_000,
            )
            self.assertEqual(
                first_row.status.value,
                "expired",
            )
            self.assertNotEqual(first[0], second[0])
            store.close()


if __name__ == "__main__":
    unittest.main()
