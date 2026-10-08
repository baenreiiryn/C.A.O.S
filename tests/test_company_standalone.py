import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from caos.cli import parser
from caos.company import CAOSAdapter, CityPresentationMapper, TradeCompany
from caos.company.control import CompanyControlPort
from caos.company.dashboard import serve_company
from caos.company.standalone import (
    build_policy,
    build_standalone_company,
    initialize_company,
    load_runtime_config,
    load_saved_policy,
    parse_scan_targets,
    save_runtime_config,
    targets_from_runtime_config,
)
from caos.domain import Mandate
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.store import Store


def make_runtime(store):
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    return caos


class StandaloneConfigTests(unittest.TestCase):
    def test_parse_scan_targets(self):
        targets = parse_scan_targets(
            "BTCUSDT:long:momentum+trend,"
            "ETHUSDT:short:breakout"
        )
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].symbol, "BTCUSDT")
        self.assertEqual(
            targets[0].strategy_candidates,
            ("momentum", "trend"),
        )
        self.assertEqual(targets[1].direction, "short")

    def test_runtime_config_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            targets = parse_scan_targets(
                "BTCUSDT:long:momentum,"
                "ETHUSDT:long:trend"
            )
            saved = save_runtime_config(
                store,
                targets,
                interval="15",
                candle_limit=240,
                opportunity_ttl_ms=90_000,
                every_seconds=30,
            )
            loaded = load_runtime_config(store)
            self.assertEqual(saved, loaded)
            restored = targets_from_runtime_config(loaded)
            self.assertEqual(
                [(t.symbol, t.direction) for t in restored],
                [("BTCUSDT", "long"), ("ETHUSDT", "long")],
            )
            store.close()

    def test_policy_is_loaded_from_company_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            caos = make_runtime(store)
            policy = build_policy(
                initial_company_capital=20,
                trader_initial_bucket=10,
                trader_stop_floor=3,
                default_trader_max_exposure_pct=17,
                operational_trader_cap=4,
                company_max_drawdown_pct=25,
            )
            company, restored = build_standalone_company(
                caos,
                policy,
                restore=False,
            )
            self.assertFalse(restored)
            targets = parse_scan_targets(
                "BTCUSDT:long:momentum"
            )
            initialize_company(company, targets)
            saved_policy = load_saved_policy(store)
            self.assertEqual(saved_policy, policy)
            store.close()

    def test_cli_parser_exposes_company_commands(self):
        args = parser().parse_args(
            [
                "--provider",
                "static",
                "company",
                "set-exposure",
                "A",
                "--max-exposure",
                "20",
                "--size",
                "8",
            ]
        )
        self.assertEqual(args.cmd, "company")
        self.assertEqual(args.company_cmd, "set-exposure")
        self.assertEqual(args.trader_id, "A")
        self.assertEqual(args.max_exposure, 20.0)
        self.assertEqual(args.requested_exposure, 8.0)


class FantasyCityPresentationTests(unittest.TestCase):
    def test_mapper_exposes_all_fantasy_city_locations(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            caos = make_runtime(store)
            policy = build_policy(
                initial_company_capital=10,
                trader_initial_bucket=10,
                trader_stop_floor=3,
                default_trader_max_exposure_pct=20,
                operational_trader_cap=6,
                company_max_drawdown_pct=30,
            )
            company = TradeCompany(
                CAOSAdapter(caos),
                policy,
                store=store,
            )
            initialize_company(
                company,
                parse_scan_targets("BTCUSDT:long:momentum"),
            )
            mapper = CityPresentationMapper()
            city = mapper.build(
                company.status(),
                improvements=company.improvement_proposals(),
                recent_events=store.recent_events(20),
            )
            self.assertEqual(city["city"]["mode"], "standalone")
            self.assertEqual(
                set(city["locations"]),
                {
                    "citadel",
                    "treasury",
                    "risk",
                    "guild",
                    "quests",
                    "scout",
                    "observatory",
                    "tavern",
                    "arena",
                    "workshop",
                    "nexus",
                    "chronicle",
                },
            )
            self.assertEqual(
                city["locations"]["tavern"]["technical_name"],
                "News / Sentiment",
            )
            self.assertEqual(
                city["locations"]["risk"]["technical_name"],
                "CompanyRiskGovernor + StrategyDiversity",
            )
            store.close()


class CompanyDashboardTests(unittest.TestCase):
    def test_dashboard_reads_only_safe_company_surface(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "company.db")
            caos = make_runtime(store)
            policy = build_policy(
                initial_company_capital=10,
                trader_initial_bucket=10,
                trader_stop_floor=3,
                default_trader_max_exposure_pct=20,
                operational_trader_cap=6,
                company_max_drawdown_pct=30,
            )
            company = TradeCompany(
                CAOSAdapter(caos),
                policy,
                store=store,
            )
            initialize_company(
                company,
                parse_scan_targets("BTCUSDT:long:momentum"),
            )
            control = CompanyControlPort(company)
            server = serve_company(
                control,
                host="127.0.0.1",
                port=0,
                open_browser=False,
            )
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            thread.start()
            host, port = server.server_address
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(
                    base + "/api/company/status",
                    timeout=2,
                ) as response:
                    payload = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    payload["traders"]["slot_count"],
                    1,
                )
                self.assertEqual(
                    payload["policy"]["operational_trader_cap"],
                    6,
                )

                with urllib.request.urlopen(
                    base + "/api/company/city",
                    timeout=2,
                ) as response:
                    city = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    city["city"]["subtitle"],
                    "Arcane Trading City",
                )
                self.assertEqual(
                    len(city["locations"]),
                    12,
                )

                with urllib.request.urlopen(
                    base + "/",
                    timeout=2,
                ) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("city-world", html)
                self.assertIn("Citadel of Oversight", html)
                self.assertIn("Tower of Wards", html)
                self.assertIn("Whispering Tankard", html)
                self.assertIn("Grand Trading Guild", html)
                self.assertIn("Arcane Nexus", html)
                self.assertNotIn('data-tab="overview"', html)

                exposure_request = urllib.request.Request(
                    base + "/api/company/traders/A/exposure",
                    data=json.dumps(
                        {
                            "max_trade_exposure_pct": 18,
                            "trade_exposure_pct": 7,
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(
                    exposure_request,
                    timeout=2,
                ) as response:
                    exposure = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    exposure["max_trade_exposure_pct"],
                    18.0,
                )
                self.assertEqual(
                    exposure["trade_exposure_pct"],
                    7.0,
                )

                request = urllib.request.Request(
                    base + "/api/company/limit",
                    data=json.dumps({"limit": 3}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(
                    request,
                    timeout=2,
                ) as response:
                    changed = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    changed["effective_trader_limit"],
                    3,
                )

                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(
                        base + "/api/company/broker",
                        timeout=2,
                    )
                self.assertEqual(ctx.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                store.close()


if __name__ == "__main__":
    unittest.main()
