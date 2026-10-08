import tempfile
import unittest
from pathlib import Path

from caos.company import (
    CAOSAdapter,
    CompanyDaemon,
    CompanyPolicy,
    ScanTarget,
    TradeCompany,
)
from caos.company.news_intelligence import (
    CompanyNewsIntelligence,
    NewsContext,
)
from caos.domain import Mandate, MarketBar, StrategySpec
from caos.llm import StaticLLM
from caos.marketdata import BinancePublicClient
from caos.news import (
    RSSNewsClient,
    default_news_sources,
    normalize_news_sources,
    validate_news_url,
)
from caos.orchestrator import CAOS
from caos.store import Store


def bars_up(n=160):
    price = 100.0
    rows = []
    for i in range(n):
        nxt = price + 0.5
        rows.append(
            MarketBar(
                1_700_000_000_000 + i * 60_000,
                price,
                nxt + 0.1,
                price - 0.1,
                nxt,
                1000,
            )
        )
        price = nxt
    return rows


class FakeMarket(BinancePublicClient):
    def klines(
        self,
        symbol,
        interval="60",
        limit=500,
        category="spot",
    ):
        del symbol, interval, category
        return bars_up()[-int(limit):]


class FakeAnalyzer:
    def __init__(self, items):
        self.items = list(items)
        self.calls = 0
        self.client = type(
            "Client",
            (),
            {"feed_urls": ["https://example.com/feed"]},
        )()

    def latest(
        self,
        limit=20,
        query=None,
        with_sentiment=True,
    ):
        del query, with_sentiment
        self.calls += 1
        return {
            "items": self.items[:limit],
            "count": min(limit, len(self.items)),
            "aggregate_sentiment": None,
            "errors": [],
        }


class FakeResponse:
    def __init__(
        self,
        url,
        body,
        content_type="text/html",
    ):
        self._url = url
        self._body = body
        self.headers = {
            "Content-Type": content_type
        }

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DiscoveringClient(RSSNewsClient):
    def __init__(self):
        super().__init__([])
        self.pages = {
            "https://example.com": FakeResponse(
                "https://example.com",
                (
                    b'<html><head><link rel="alternate" '
                    b'type="application/rss+xml" '
                    b'href="/rss.xml"></head></html>'
                ),
            ),
            "https://example.com/rss.xml": FakeResponse(
                "https://example.com/rss.xml",
                (
                    b"<rss><channel><item>"
                    b"<title>Market update</title>"
                    b"<link>https://example.com/a</link>"
                    b"</item></channel></rss>"
                ),
                "application/rss+xml",
            ),
        }

    def _request(self, url):
        if url not in self.pages:
            raise RuntimeError("missing")
        return self.pages[url]


class NewsCatalogTests(unittest.TestCase):
    def test_default_catalog_has_market_crypto_and_official_sources(self):
        sources = default_news_sources()
        self.assertGreaterEqual(len(sources), 8)
        categories = {
            row["category"]
            for row in sources
        }
        kinds = {row["kind"] for row in sources}
        self.assertIn("crypto", categories)
        self.assertIn("stocks", categories)
        self.assertIn("macro", categories)
        self.assertIn("official", kinds)
        self.assertTrue(
            all(
                row["url"].startswith("https://")
                for row in sources
            )
        )
        self.assertTrue(
            all(row["enabled"] for row in sources)
        )

    def test_news_urls_reject_private_and_non_https_targets(self):
        for url in (
            "http://example.com/feed",
            "https://localhost/feed",
            "https://127.0.0.1/feed",
            "https://10.0.0.2/feed",
            "https://169.254.10.1/feed",
        ):
            with self.assertRaises(ValueError):
                validate_news_url(url)

    def test_normalizer_deduplicates_urls(self):
        rows = normalize_news_sources(
            [
                {
                    "id": "a",
                    "name": "A",
                    "url": "https://example.com/feed",
                },
                {
                    "id": "b",
                    "name": "B",
                    "url": "https://example.com/feed",
                },
            ]
        )
        self.assertEqual(len(rows), 1)

    def test_discover_feed_from_normal_site_url(self):
        result = DiscoveringClient().discover_feed(
            "https://example.com"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["feed_url"],
            "https://example.com/rss.xml",
        )
        self.assertEqual(
            result["sample"][0]["title"],
            "Market update",
        )


class NewsIntelligenceTests(unittest.TestCase):
    def test_critical_negative_direct_news_blocks_only_new_risk(self):
        analyzer = FakeAnalyzer(
            [
                {
                    "title": (
                        "Bitcoin exchange hack suspends withdrawals"
                    ),
                    "summary": (
                        "BTC withdrawals suspended after breach"
                    ),
                    "link": "https://example.com/a",
                    "source": "https://www.coindesk.com/arc/outboundfeeds/rss/",
                    "published": "2026-10-09T10:00:00+00:00",
                    "sentiment": {
                        "signed_score": -0.9
                    },
                }
            ]
        )
        caos = type(
            "FakeCAOS",
            (),
            {"news_analyzer": analyzer},
        )()
        intel = CompanyNewsIntelligence(caos)
        snap = intel.refresh(
            ["BTCUSDT", "ETHUSDT"],
            now=1_000_000,
        )
        btc = snap["contexts"]["BTCUSDT"]
        eth = snap["contexts"]["ETHUSDT"]
        self.assertTrue(btc["block_new_risk"])
        self.assertEqual(btc["severity"], "high")
        self.assertGreaterEqual(
            btc["score_penalty"],
            40.0,
        )
        self.assertFalse(eth["block_new_risk"])

    def test_custom_source_cannot_hard_block_new_risk_alone(self):
        analyzer = FakeAnalyzer(
            [
                {
                    "title": (
                        "Bitcoin exchange hack suspends withdrawals"
                    ),
                    "summary": "BTC breach and trading halt",
                    "link": "https://custom.example/a",
                    "source": "https://custom.example/feed",
                    "published": "2026-10-09T10:30:00+00:00",
                    "sentiment": {
                        "signed_score": -0.95
                    },
                }
            ]
        )
        caos = type(
            "FakeCAOS",
            (),
            {"news_analyzer": analyzer},
        )()
        intel = CompanyNewsIntelligence(caos)
        ctx = intel.refresh(
            ["BTCUSDT"],
            now=1_000_000,
        )["contexts"]["BTCUSDT"]
        self.assertFalse(ctx["block_new_risk"])
        self.assertEqual(ctx["severity"], "medium")
        self.assertGreater(
            ctx["score_penalty"],
            0.0,
        )
        self.assertFalse(
            ctx["headlines"][0][
                "trusted_source"
            ]
        )

    def test_positive_news_never_adds_risk_or_score_bonus(self):
        analyzer = FakeAnalyzer(
            [
                {
                    "title": (
                        "Bitcoin adoption surges after approval"
                    ),
                    "summary": "BTC sees record inflows",
                    "link": "https://example.com/b",
                    "source": "https://www.coindesk.com/arc/outboundfeeds/rss/",
                    "published": "2026-10-09T11:00:00+00:00",
                    "sentiment": {
                        "signed_score": 0.95
                    },
                }
            ]
        )
        caos = type(
            "FakeCAOS",
            (),
            {"news_analyzer": analyzer},
        )()
        intel = CompanyNewsIntelligence(caos)
        ctx = intel.refresh(
            ["BTCUSDT"],
            now=1_000_000,
        )["contexts"]["BTCUSDT"]
        self.assertFalse(ctx["block_new_risk"])
        self.assertEqual(ctx["score_penalty"], 0.0)

    def test_news_polling_is_cached(self):
        analyzer = FakeAnalyzer([])
        caos = type(
            "FakeCAOS",
            (),
            {"news_analyzer": analyzer},
        )()
        intel = CompanyNewsIntelligence(
            caos,
            poll_interval_ms=300_000,
        )
        intel.refresh(["BTCUSDT"], now=1_000_000)
        intel.refresh(["BTCUSDT"], now=1_100_000)
        self.assertEqual(analyzer.calls, 1)


class CompanyNewsDaemonTests(unittest.TestCase):
    def _company(self):
        caos = CAOS(
            StaticLLM(
                '{"tool":"status","args":{}}'
            ),
            market_client=FakeMarket(),
        )
        caos.set_mandate(
            Mandate(
                1000,
                50,
                max_position_pct=20,
            )
        )
        company = TradeCompany(
            CAOSAdapter(caos),
            CompanyPolicy(),
        )
        company.register_strategy(
            StrategySpec(
                "trend",
                "trend",
                3,
                21,
            )
        )
        company.bootstrap()
        return caos, company

    def test_critical_news_prevents_new_opportunity_and_assignment(self):
        caos, company = self._company()
        caos.news_analyzer = FakeAnalyzer(
            [
                {
                    "title": (
                        "Bitcoin hack causes trading halt"
                    ),
                    "summary": "BTC market under attack",
                    "link": "https://example.com/c",
                    "source": "https://www.coindesk.com/arc/outboundfeeds/rss/",
                    "published": "2026-10-09T12:00:00+00:00",
                    "sentiment": {
                        "signed_score": -0.95
                    },
                }
            ]
        )
        daemon = CompanyDaemon(
            company,
            [
                ScanTarget(
                    "BTCUSDT",
                    "long",
                    ("trend",),
                )
            ],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1_000_000)
        self.assertEqual(cycle.opportunities, [])
        self.assertEqual(cycle.assignments, [])
        self.assertTrue(
            cycle.news_intelligence[
                "contexts"
            ]["BTCUSDT"]["block_new_risk"]
        )
        self.assertEqual(
            company.registry.get("A").status.value,
            "waiting_assignment",
        )

    def test_news_failure_does_not_invent_a_block(self):
        _, company = self._company()
        company.news_intelligence.contexts[
            "BTCUSDT"
        ] = NewsContext("BTCUSDT")
        company.news_intelligence.refresh = (
            lambda symbols, now: (_ for _ in ()).throw(
                RuntimeError("news_down")
            )
        )
        daemon = CompanyDaemon(
            company,
            [
                ScanTarget(
                    "BTCUSDT",
                    "long",
                    ("trend",),
                )
            ],
            candle_limit=160,
        )
        cycle = daemon.run_once(now=1_000_000)
        self.assertIn(
            "news:intelligence",
            cycle.errors,
        )
        self.assertTrue(cycle.opportunities)


if __name__ == "__main__":
    unittest.main()
