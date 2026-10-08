import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from caos.cell_protocol import (
    CELL_PROTOCOL_VERSION,
    CellProtocolError,
    CompanyCell,
)
from caos.company import CAOSAdapter, TradeCompany, TradeCompanyCell
from caos.company.domain import Opportunity
from caos.company.control import CompanyControlPort
from caos.company.daemon import CompanyDaemon, ScanTarget
from caos.company.dashboard import serve_company
from caos.company.standalone import (
    build_policy,
    initialize_company,
    parse_scan_targets,
)
from caos.domain import Mandate, MarketBar
from caos.execution_fabric import (
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from caos.testnet import execution_plan_to_binance_order
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.store import Store


def rising_bars(n=80):
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


def flat_bars(n=80, price=100.0):
    return [
        MarketBar(
            i,
            price,
            price + 0.1,
            price - 0.1,
            price,
            1000.0,
        )
        for i in range(n)
    ]


def create_uncertain_intent(company):
    decision = decision_from_signal(
        symbol="BTCUSDT",
        strategy_id="cell-reliability",
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
        error="simulated_crash_window",
    )
    return row["intent_id"]


def make_company(tmpdir, *, capital=10.0):
    store = Store(Path(tmpdir) / "cell.db")
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    policy = build_policy(
        initial_company_capital=capital,
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
    return store, caos, company


class CompanyCellProtocolTests(unittest.TestCase):
    def test_trade_company_implements_generic_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            cell = TradeCompanyCell(CompanyControlPort(company))
            self.assertIsInstance(cell, CompanyCell)

            manifest = cell.get_manifest()
            self.assertEqual(
                manifest["protocol_version"],
                CELL_PROTOCOL_VERSION,
            )
            self.assertEqual(manifest["cell_id"], "trade-company")
            self.assertEqual(manifest["cell_type"], "trading")
            self.assertEqual(
                manifest["commands"],
                ["pause", "resume", "emergency_stop"],
            )
            self.assertEqual(
                manifest["ui"]["kind"],
                "themed_city",
            )
            self.assertNotIn("place_order", manifest["commands"])
            self.assertNotIn("arm_live", manifest["commands"])
            self.assertNotIn(
                "set_broker_credentials",
                manifest["commands"],
            )
            store.close()

    def test_generic_status_health_metrics_alerts_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            cell = TradeCompanyCell(CompanyControlPort(company))

            status = cell.get_status()
            health = cell.get_health()
            metrics = cell.get_metrics()
            alerts = cell.get_alerts()
            report = cell.get_report()

            self.assertEqual(status["cell_id"], "trade-company")
            self.assertEqual(status["operational_state"], "running")
            self.assertIn(
                health["state"],
                {"healthy", "attention", "critical", "emergency"},
            )
            self.assertIn("company_equity", metrics["values"])
            self.assertTrue(
                any(
                    item["id"] == "company_equity"
                    and item["unit"] == "USD"
                    for item in metrics["items"]
                )
            )
            self.assertIsInstance(alerts, list)
            if alerts:
                self.assertIn("code", alerts[0])
                self.assertIn("message", alerts[0])
                self.assertIn("data", alerts[0])
            self.assertEqual(report["cell_id"], "trade-company")
            self.assertIn("headline", report)
            self.assertIn("highlights", report)
            self.assertEqual(
                report["ui"]["path"],
                "/",
            )
            store.close()

    def test_execution_reliability_surfaces_as_cell_attention(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            create_uncertain_intent(company)
            cell = TradeCompanyCell(
                CompanyControlPort(company)
            )

            health = cell.get_health()
            metrics = cell.get_metrics()["values"]
            alerts = cell.get_alerts()
            report = cell.get_report()

            self.assertEqual(health["state"], "attention")
            self.assertEqual(
                metrics["execution_intents"],
                1,
            )
            self.assertEqual(
                metrics["execution_recovery_required"],
                1,
            )
            self.assertTrue(
                any(
                    row["code"]
                    == "execution_reconciliation_required"
                    for row in alerts
                )
            )
            self.assertTrue(
                any(
                    "Execution reliability:" in row
                    for row in report["highlights"]
                )
            )
            store.close()

    def test_pause_is_persistent_and_daemon_stops_new_actions(self):
        with tempfile.TemporaryDirectory() as d:
            store, caos, company = make_company(d)
            cell = TradeCompanyCell(CompanyControlPort(company))

            paused = cell.execute_command("pause")
            self.assertTrue(
                paused["result"]["operations_paused"]
            )
            self.assertTrue(company.operations_paused)

            company.engine.fetch_market = (
                lambda symbol, interval="60", limit=500: {
                    "symbol": symbol,
                    "bars": 100,
                }
            )
            daemon = CompanyDaemon(
                company,
                [ScanTarget("BTCUSDT", "long", ("momentum",))],
            )
            cycle = daemon.run_once(now=1_000)
            self.assertTrue(cycle.paused)
            self.assertEqual(cycle.opportunities, [])
            self.assertEqual(cycle.assignments, [])
            self.assertEqual(cycle.paper_actions, [])
            self.assertEqual(cycle.expansions, [])

            restored = TradeCompany(
                CAOSAdapter(caos),
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertTrue(restored.operations_paused)

            resumed = TradeCompanyCell(
                CompanyControlPort(restored)
            ).execute_command("resume")
            self.assertFalse(
                resumed["result"]["operations_paused"]
            )
            self.assertFalse(restored.operations_paused)
            store.close()

    def test_paused_cell_allows_risk_reducing_exit(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            company.publish_opportunity(
                Opportunity(
                    "btc",
                    "BTCUSDT",
                    "long",
                    100,
                    strategy_candidates=("momentum",),
                )
            )
            company.assign_best("A")
            company.engine.load_bars("BTCUSDT", rising_bars())
            opened = company.paper.cycle_trader("A")
            self.assertEqual(opened.action, "open_long")

            TradeCompanyCell(
                CompanyControlPort(company)
            ).execute_command("pause")
            company.engine.load_bars(
                "BTCUSDT",
                flat_bars(price=180.0),
            )
            company.engine.fetch_market = (
                lambda symbol, interval="60", limit=500: {
                    "symbol": symbol,
                    "bars": 80,
                }
            )
            daemon = CompanyDaemon(
                company,
                [ScanTarget("BTCUSDT", "long", ("momentum",))],
            )
            cycle = daemon.run_once(now=2_000)
            self.assertTrue(cycle.paused)
            self.assertTrue(
                any(
                    row["action"] == "close_long"
                    for row in cycle.paper_actions
                )
            )
            self.assertTrue(
                company.paper.positions_flat("A")
            )
            self.assertEqual(cycle.opportunities, [])
            self.assertEqual(cycle.expansions, [])
            store.close()

    def test_resume_cannot_bypass_emergency_kill(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            cell = TradeCompanyCell(CompanyControlPort(company))
            cell.execute_command("pause")
            cell.execute_command("emergency_stop")

            with self.assertRaises(Exception):
                cell.execute_command("resume")
            self.assertTrue(company.operations_paused)
            self.assertTrue(company.risk.state.kill_switch)
            store.close()

    def test_unknown_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
            cell = TradeCompanyCell(CompanyControlPort(company))
            with self.assertRaises(CellProtocolError):
                cell.execute_command("place_order")
            store.close()


class CompanyCellHTTPTests(unittest.TestCase):
    def test_versioned_cell_http_contract(self):
        with tempfile.TemporaryDirectory() as d:
            store, _, company = make_company(d)
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
            base = f"http://{host}:{port}"
            try:
                endpoints = {
                    "manifest",
                    "status",
                    "health",
                    "metrics",
                    "alerts",
                    "events",
                    "report",
                }
                payloads = {}
                for endpoint in endpoints:
                    with urllib.request.urlopen(
                        f"{base}/api/cell/v1/{endpoint}",
                        timeout=2,
                    ) as response:
                        payloads[endpoint] = json.loads(
                            response.read().decode("utf-8")
                        )
                self.assertEqual(
                    payloads["manifest"]["protocol_version"],
                    CELL_PROTOCOL_VERSION,
                )
                self.assertEqual(
                    payloads["status"]["cell_type"],
                    "trading",
                )
                self.assertEqual(
                    payloads["report"]["ui"]["kind"],
                    "themed_city",
                )

                pause_request = urllib.request.Request(
                    base + "/api/cell/v1/command",
                    data=json.dumps({"name": "pause"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(
                    pause_request,
                    timeout=2,
                ) as response:
                    paused = json.loads(
                        response.read().decode("utf-8")
                    )
                self.assertTrue(
                    paused["result"]["operations_paused"]
                )

                bad_request = urllib.request.Request(
                    base + "/api/cell/v1/command",
                    data=json.dumps({"name": "place_order"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(
                    urllib.error.HTTPError
                ) as ctx:
                    urllib.request.urlopen(
                        bad_request,
                        timeout=2,
                    )
                self.assertEqual(ctx.exception.code, 400)

                with self.assertRaises(
                    urllib.error.HTTPError
                ) as ctx:
                    urllib.request.urlopen(
                        base + "/api/cell/v1/broker",
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
