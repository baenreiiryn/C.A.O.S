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
from caos.company.research import PromotionDecision
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
from caos.domain import Mandate, StrategySpec
from caos.execution_fabric import (
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from caos.testnet import execution_plan_to_binance_order
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.store import Store


def add_uncertain_execution_intent(company):
    decision = decision_from_signal(
        symbol="BTCUSDT",
        strategy_id="city-reliability",
        signal="long",
        requested_weight=0.1,
        as_of=1,
    )
    target = resolve_target_position(
        decision,
        equity=10.0,
        max_notional=1.0,
    )
    plan = plan_execution(
        target,
        current_notional=0.0,
        reference_price=100.0,
    )
    journal = company.execution_reliability
    row = journal.prepare(
        plan,
        execution_plan_to_binance_order(plan),
    )
    journal.claim_for_submit(row["intent_id"])
    journal.mark_uncertain(
        row["intent_id"],
        error="simulated_network_ambiguity",
    )
    return row["intent_id"]


def make_runtime(store):
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    return caos


class FakeSettingsService:
    def __init__(self):
        self.saved_llm = None
        self.saved_news = None
        self.saved_ollama_import = None
        self.ollama_running = False

    def get_settings(self):
        return {
            "version": "settings/v1",
            "llm": {
                "provider": "ollama",
                "model": "qwen3:8b",
                "base_url": "http://127.0.0.1:11434",
                "api_key_configured": False,
            },
            "ollama_runtime": {
                "enabled": True,
                "installed": True,
                "running": self.ollama_running,
                "managed_process": self.ollama_running,
                "base_url": "http://127.0.0.1:11435",
                "runtime_dir": "C:/CAOS/ollama",
                "models_dir": "C:/CAOS/models",
                "version": (
                    "0.test"
                    if self.ollama_running
                    else None
                ),
            },
            "brokers": {
                "supported": {
                    "binance": {
                        "label": "Binance Japan / Spot",
                        "environments": [
                            "spot-testnet",
                            "production-readonly",
                        ],
                        "activatable": True,
                    }
                },
                "profiles": [
                    {
                        "id": "binance-testnet",
                        "label": "Binance Spot TESTNET",
                        "provider": "binance",
                        "environment": "spot-testnet",
                        "api_key_configured": True,
                        "api_secret_configured": True,
                    }
                ],
                "active_profile_id": "binance-testnet",
            },
            "news": {
                "sources": [
                    {
                        "id": "coindesk",
                        "name": "CoinDesk",
                        "category": "crypto",
                        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
                        "kind": "editorial",
                        "enabled": True,
                        "built_in": True,
                    }
                ],
                "defaults": [],
                "enabled_count": 1,
                "analyzer_active": True,
            },
        }

    def start_managed_ollama(self):
        self.ollama_running = True
        return self.get_settings()["ollama_runtime"]

    def stop_managed_ollama(self):
        self.ollama_running = False
        return self.get_settings()["ollama_runtime"]

    def pick_managed_ollama_model(self):
        return {
            "selected": True,
            "path": "C:/models/test.gguf",
            "suggested_name": "caos-test",
        }

    def import_managed_ollama_model(
        self,
        *,
        source_path,
        model_name="",
    ):
        self.saved_ollama_import = {
            "source_path": source_path,
            "model_name": model_name,
        }
        return {
            "imported": {
                "model": model_name or "caos-test",
                "source_file": source_path,
                "base_url": "http://127.0.0.1:11435",
                "runtime": self.get_settings()[
                    "ollama_runtime"
                ],
            },
            "llm": {
                "provider": "ollama",
                "model": model_name or "caos-test",
                "base_url": "http://127.0.0.1:11435",
                "api_key_configured": False,
            },
            "ollama_runtime": self.get_settings()[
                "ollama_runtime"
            ],
        }

    def discover_models(self, **kwargs):
        return {
            "provider": kwargs["provider"],
            "models": ["qwen3:8b", "qwen3:14b"],
        }

    def test_llm(self, **kwargs):
        return {
            "ok": True,
            "message": "Connection succeeded.",
            "models": [kwargs["model"]],
        }

    def save_llm(self, **kwargs):
        self.saved_llm = dict(kwargs)
        return {
            "provider": kwargs["provider"],
            "model": kwargs["model"],
            "base_url": kwargs["base_url"],
            "api_key_configured": bool(
                kwargs.get("api_key")
            ),
        }

    def save_news_sources(self, sources):
        self.saved_news = list(sources)
        return {
            "sources": list(sources),
            "defaults": [],
            "enabled_count": sum(
                bool(row.get("enabled", True))
                for row in sources
            ),
            "analyzer_active": any(
                bool(row.get("enabled", True))
                for row in sources
            ),
        }

    def discover_news_feed(self, url):
        return {
            "ok": True,
            "site_url": url,
            "feed_url": "https://example.com/rss.xml",
            "method": "discovered",
            "sample": [],
        }

    def test_news_source(self, url):
        return {
            "ok": True,
            "url": url,
            "count": 2,
            "sample": [],
            "error": None,
        }

    def restore_default_news_sources(self):
        return self.get_settings()["news"]

    def preview_news(self, *, limit=20, query=None):
        del query
        return {
            "items": [
                {
                    "title": "Test headline",
                    "source": "https://example.com/rss.xml",
                }
            ][:limit],
            "count": 1,
            "aggregate_sentiment": None,
            "errors": [],
        }

    def save_broker_profile(self, **kwargs):
        return {
            "id": kwargs.get("profile_id")
            or "binance-testnet",
            "label": kwargs["label"],
            "provider": kwargs["provider"],
            "environment": kwargs["environment"],
            "api_key_configured": bool(
                kwargs.get("api_key")
            ),
            "api_secret_configured": bool(
                kwargs.get("api_secret")
            ),
        }

    def test_broker(self, profile_id, **kwargs):
        return {
            "ok": True,
            "profile_id": profile_id,
            "message": "Broker credentials authenticated.",
        }

    def set_active_broker(self, profile_id):
        return {
            "active_profile_id": profile_id,
        }

    def delete_broker_profile(self, profile_id):
        return {
            "active_profile_id": None,
            "profiles": [],
        }


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


    def test_cli_parser_exposes_reliability_commands(self):
        company_args = parser().parse_args(
            [
                "--provider",
                "static",
                "company",
                "reliability",
            ]
        )
        self.assertEqual(
            company_args.company_cmd,
            "reliability",
        )
        recovery_args = parser().parse_args(
            [
                "--provider",
                "static",
                "testnet-recover",
            ]
        )
        self.assertEqual(
            recovery_args.cmd,
            "testnet-recover",
        )
        abandon_args = parser().parse_args(
            [
                "--provider",
                "static",
                "testnet-abandon-missing",
                "intent-123",
                "--confirm",
                "ABANDON MISSING TESTNET INTENT",
            ]
        )
        self.assertEqual(
            abandon_args.cmd,
            "testnet-abandon-missing",
        )
        intents_args = parser().parse_args(
            [
                "--provider",
                "static",
                "execution-intents",
                "--limit",
                "25",
            ]
        )
        self.assertEqual(
            intents_args.limit,
            25,
        )


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
                "News / Sentiment / NewsIntelligence",
            )
            self.assertEqual(
                city["locations"]["risk"]["technical_name"],
                "CompanyRiskGovernor + StrategyDiversity",
            )
            store.close()

    def test_mapper_flags_execution_reconciliation_in_chronicle(self):
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
                parse_scan_targets(
                    "BTCUSDT:long:momentum"
                ),
            )
            add_uncertain_execution_intent(company)
            city = CityPresentationMapper().build(
                company.status(),
                improvements=company.improvement_proposals(),
                recent_events=store.recent_events(20),
            )
            self.assertEqual(
                city["city"]["mood"],
                "attention",
            )
            self.assertEqual(
                city["locations"]["chronicle"]["state"],
                "attention",
            )
            self.assertEqual(
                city["execution_reliability"][
                    "recovery_required"
                ],
                1,
            )
            store.close()

    def test_mapper_emergency_state_seals_the_city(self):
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
            company.emergency_stop()
            city = CityPresentationMapper().build(
                company.status(),
                improvements=company.improvement_proposals(),
                recent_events=store.recent_events(20),
            )
            self.assertEqual(city["city"]["mood"], "emergency")
            self.assertTrue(city["city"]["emergency"])
            self.assertEqual(
                city["locations"]["risk"]["state"],
                "emergency",
            )
            store.close()


    def test_execution_reliability_survives_company_checkpoint_restore(self):
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
                parse_scan_targets(
                    "BTCUSDT:long:momentum"
                ),
            )
            add_uncertain_execution_intent(company)
            company.checkpoint()

            restored = TradeCompany(
                CAOSAdapter(caos),
                policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.execution_reliability.summary()[
                    "recovery_required"
                ],
                1,
            )
            self.assertEqual(
                len(
                    restored.execution_reliability.list(
                        limit=10
                    )
                ),
                1,
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
            settings_service = FakeSettingsService()
            server = serve_company(
                control,
                host="127.0.0.1",
                port=0,
                open_browser=False,
                settings_service=settings_service,
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

                with urllib.request.urlopen(
                    base + "/api/company/reliability",
                    timeout=2,
                ) as response:
                    reliability = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertTrue(reliability["enabled"])
                self.assertIn(
                    "recovery_required",
                    reliability["summary"],
                )
                self.assertEqual(
                    city["city"]["subtitle"],
                    "Arcane Trading City",
                )

                with urllib.request.urlopen(
                    base + "/api/settings",
                    timeout=2,
                ) as response:
                    settings = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertTrue(settings["enabled"])
                self.assertEqual(
                    settings["llm"]["provider"],
                    "ollama",
                )
                serialized_settings = json.dumps(settings)
                self.assertNotIn(
                    '"api_secret":',
                    serialized_settings,
                )
                self.assertNotIn(
                    '"api_key":',
                    serialized_settings,
                )
                self.assertTrue(
                    settings["ollama_runtime"]["installed"]
                )
                self.assertFalse(
                    settings["ollama_runtime"]["running"]
                )

                start_ollama = urllib.request.Request(
                    base + "/api/settings/ollama/start",
                    data=b"{}",
                    headers={
                        "Content-Type": "application/json"
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    start_ollama,
                    timeout=2,
                ) as response:
                    started_ollama = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertTrue(started_ollama["running"])

                import_ollama = urllib.request.Request(
                    base + "/api/settings/ollama/import",
                    data=json.dumps(
                        {
                            "source_path": "C:/models/test.gguf",
                            "model_name": "caos-test",
                        }
                    ).encode(),
                    headers={
                        "Content-Type": "application/json"
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    import_ollama,
                    timeout=2,
                ) as response:
                    imported_ollama = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    imported_ollama["imported"]["model"],
                    "caos-test",
                )
                self.assertEqual(
                    settings_service.saved_ollama_import[
                        "source_path"
                    ],
                    "C:/models/test.gguf",
                )

                save_llm = urllib.request.Request(
                    base + "/api/settings/llm/save",
                    data=json.dumps(
                        {
                            "provider": "static",
                            "model": "static",
                            "base_url": "",
                        }
                    ).encode(),
                    headers={
                        "Content-Type": "application/json"
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    save_llm,
                    timeout=2,
                ) as response:
                    saved_llm = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    saved_llm["provider"],
                    "static",
                )
                self.assertEqual(
                    settings_service.saved_llm["model"],
                    "static",
                )

                save_news = urllib.request.Request(
                    base + "/api/settings/news/save",
                    data=json.dumps(
                        {
                            "sources": [
                                {
                                    "id": "custom",
                                    "name": "Custom",
                                    "category": "crypto",
                                    "url": "https://example.com/rss.xml",
                                    "kind": "custom",
                                    "enabled": True,
                                    "built_in": False,
                                }
                            ]
                        }
                    ).encode(),
                    headers={
                        "Content-Type": "application/json"
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    save_news,
                    timeout=2,
                ) as response:
                    saved_news = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    saved_news["enabled_count"],
                    1,
                )
                self.assertEqual(
                    settings_service.saved_news[0]["id"],
                    "custom",
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
                self.assertIn(
                    "Arcane Nexus · Managed Ollama",
                    html,
                )
                self.assertIn(
                    "pickLocalOllamaModel",
                    html,
                )
                self.assertIn("Execution Reliability", html)
                self.assertIn("settingsBtn", html)
                self.assertIn("Broker Embassy", html)
                self.assertIn(
                    "Whispering Tankard · News Sources",
                    html,
                )
                self.assertIn(
                    "discoverAndAddNewsSource",
                    html,
                )
                self.assertIn("guildAdventurers", html)
                self.assertNotIn('data-tab="overview"', html)
                self.assertNotIn("King Drizzt", html)

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

    def test_dashboard_strategy_rollout_controls_are_safe(self):
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
            strategy_id = "research:http-rollout"
            company.register_strategy(
                StrategySpec(
                    "http_rollout",
                    "momentum",
                    2,
                    3,
                    threshold=0.1,
                ),
                strategy_id=strategy_id,
            )
            company.research.decisions.append(
                PromotionDecision(
                    id="http-promotion",
                    symbol="BTCUSDT",
                    candidate_id="http-candidate",
                    candidate_strategy_id=strategy_id,
                    prior_champion_strategy_id=None,
                    status="promoted",
                    reason="http_test",
                )
            )
            company.research.champions["BTCUSDT"] = strategy_id
            release = company.rollout.sync_research(
                company.research
            )[0]
            release.stage = "eligible"
            company.checkpoint()

            server = serve_company(
                CompanyControlPort(company),
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
            base = "http://%s:%s" % (host, port)
            try:
                with urllib.request.urlopen(
                    base + "/api/company/rollout",
                    timeout=2,
                ) as response:
                    rollout = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    rollout["releases"][release.id]["stage"],
                    "eligible",
                )

                activate = urllib.request.Request(
                    (
                        base
                        + "/api/company/rollout/"
                        + release.id
                        + "/activate"
                    ),
                    data=b"",
                    method="POST",
                )
                with urllib.request.urlopen(
                    activate,
                    timeout=2,
                ) as response:
                    active = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(active["stage"], "active")

                rollback = urllib.request.Request(
                    (
                        base
                        + "/api/company/rollout/"
                        + release.id
                        + "/rollback"
                    ),
                    data=json.dumps(
                        {"reason": "http_test_rollback"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(
                    rollback,
                    timeout=2,
                ) as response:
                    rolled = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertEqual(
                    rolled["release"]["stage"],
                    "rolled_back",
                )

                with urllib.request.urlopen(
                    base + "/",
                    timeout=2,
                ) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Rollout Gate", html)
                self.assertIn("activateRelease", html)
                self.assertIn("rollbackRelease", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                store.close()


if __name__ == "__main__":
    unittest.main()
