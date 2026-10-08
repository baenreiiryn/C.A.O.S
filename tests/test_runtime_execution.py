import tempfile
import urllib.parse
import unittest
from pathlib import Path

from caos.app_settings import MemoryCredentialVault
from caos.company import CAOSAdapter, Opportunity, TradeCompany
from caos.company.company import TradeCompanyError
from caos.company.standalone import (
    build_policy,
    initialize_company,
    parse_scan_targets,
)
from caos.domain import Mandate, MarketBar
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.runtime_execution import (
    RuntimeExecutionError,
    RuntimeExecutionService,
)
from caos.store import Store
from caos.testnet import BinanceSpotClient


def rising_bars(n=120):
    rows = []
    price = 100.0
    for i in range(n):
        close = price + 0.5
        rows.append(
            MarketBar(
                1_700_000_000_000 + i * 60_000,
                price,
                close + 0.2,
                price - 0.2,
                close,
                1000.0,
            )
        )
        price = close
    return rows


def build_company(tmpdir):
    store = Store(Path(tmpdir) / "runtime-exec.db")
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
    initialize_company(
        company,
        parse_scan_targets(
            "BTCUSDT:long:momentum"
        ),
    )
    company.publish_opportunity(
        Opportunity(
            "real-proposal",
            "BTCUSDT",
            "long",
            100,
            strategy_candidates=("momentum",),
        )
    )
    company.assign_best("A")
    caos.load_bars("BTCUSDT", rising_bars())
    company.stop_operations()
    return store, caos, company


class RuntimeExecutionTests(unittest.TestCase):
    def test_real_mode_is_runtime_only_and_requires_explicit_arm(self):
        with tempfile.TemporaryDirectory() as d:
            store, _caos, company = build_company(d)
            config = {
                "broker_profiles": [
                    {
                        "id": "real",
                        "label": "Binance Real",
                        "provider": "binance",
                        "environment": "production-manual",
                    }
                ],
                "active_broker_profile": "real",
            }
            vault = MemoryCredentialVault()
            vault.set("broker:real:api_key", "key")
            vault.set("broker:real:api_secret", "secret")
            service = RuntimeExecutionService(
                company,
                config,
                vault,
            )
            self.assertEqual(service.status()["mode"], "paper")
            with self.assertRaises(RuntimeExecutionError):
                service.set_mode("real-manual")
            armed = service.set_mode(
                "real-manual",
                confirmation="ENABLE REAL",
            )
            self.assertEqual(armed["mode"], "real-manual")

            restarted = RuntimeExecutionService(
                company,
                config,
                vault,
            )
            self.assertEqual(
                restarted.status()["mode"],
                "paper",
            )
            store.close()

    def test_real_agent_proposal_does_not_move_money_until_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            store, _caos, company = build_company(d)
            config = {
                "broker_profiles": [
                    {
                        "id": "real",
                        "label": "Binance Real",
                        "provider": "binance",
                        "environment": "production-manual",
                    }
                ],
                "active_broker_profile": "real",
            }
            vault = MemoryCredentialVault()
            vault.set("broker:real:api_key", "key")
            vault.set("broker:real:api_secret", "secret")
            service = RuntimeExecutionService(
                company,
                config,
                vault,
            )

            def transport(method, url, data, headers):
                del method, url, headers
                body = dict(
                    urllib.parse.parse_qsl(
                        data.decode()
                    )
                )
                qty = float(body["quantity"])
                fill_price = 160.0
                return {
                    "symbol": body["symbol"],
                    "orderId": 7,
                    "clientOrderId": body[
                        "newClientOrderId"
                    ],
                    "origQty": body["quantity"],
                    "executedQty": body["quantity"],
                    "cummulativeQuoteQty": str(
                        qty * fill_price
                    ),
                    "status": "FILLED",
                    "type": body["type"],
                    "side": body["side"],
                }

            def fake_client(
                *,
                environment,
                manual_production=False,
            ):
                return BinanceSpotClient(
                    "key",
                    "secret",
                    environment=environment,
                    transport=transport,
                    allow_manual_production_orders=(
                        manual_production
                    ),
                )

            service._client = fake_client
            service.set_mode(
                "real-manual",
                confirmation="ENABLE REAL",
            )
            company.start_operations()

            proposed = service.cycle_trader("A")
            self.assertEqual(
                proposed.action,
                "awaiting_human_confirmation",
            )
            self.assertTrue(
                company.paper.positions_flat("A")
            )
            rows = service.list_proposals(
                statuses=("prepared",)
            )
            self.assertEqual(len(rows), 1)
            intent_id = rows[0]["intent_id"]
            self.assertEqual(
                rows[0]["payload"]["side"],
                "BUY",
            )

            service.confirm_real(
                intent_id,
                confirmation="CONFIRM " + intent_id,
            )
            self.assertFalse(
                company.paper.positions_flat("A")
            )
            proposal = service.proposal(intent_id)
            self.assertEqual(
                proposal["status"],
                "acknowledged",
            )
            self.assertTrue(
                proposal["meta"]["mirrored"],
            )

            company.stop_operations()
            restarted = RuntimeExecutionService(
                company,
                config,
                vault,
            )
            restarted._client = fake_client
            company.set_resume_guard(
                restarted.resume_guard_reason
            )
            self.assertEqual(
                restarted.status()["mode"],
                "paper",
            )
            self.assertIn(
                "A",
                restarted.status()[
                    "real_open_positions"
                ],
            )
            with self.assertRaises(TradeCompanyError):
                company.start_operations()

            restarted.set_mode(
                "real-manual",
                confirmation="ENABLE REAL",
            )
            company.start_operations()
            self.assertEqual(
                company.operational_state(),
                "running",
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
