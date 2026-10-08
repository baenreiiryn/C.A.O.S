import hashlib
import hmac
import urllib.parse
import unittest

from caos.compliance import ComplianceEngine, ComplianceViolation
from caos.testnet import (
    BinanceSpotClient,
    HumanTestnetExecutor,
    TestnetError,
)


class BinanceSpotTestnetTests(unittest.TestCase):
    def test_unknown_or_cross_environment_host_is_forbidden(self):
        with self.assertRaises(TestnetError):
            BinanceSpotClient(
                "key",
                "secret",
                environment="spot-testnet",
                base_url="https://api.binance.com",
            )
        with self.assertRaises(TestnetError):
            BinanceSpotClient(
                "key",
                "secret",
                environment="production-readonly",
                base_url="https://testnet.binance.vision",
            )

    def test_signature_matches_binance_hmac_formula(self):
        client = BinanceSpotClient(
            "abc",
            "xyz",
            time_ms=lambda: 123456,
            transport=lambda *args: {},
        )
        query = (
            "recvWindow=5000&symbol=BTCUSDT&"
            "timestamp=123456"
        )
        expected = hmac.new(
            b"xyz",
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            client.signature(query),
            expected,
        )

    def test_order_headers_and_form_body(self):
        captured = {}

        def transport(method, url, data, headers):
            captured["method"] = method
            captured["url"] = url
            captured["body"] = dict(
                urllib.parse.parse_qsl(
                    data.decode()
                )
            )
            captured["headers"] = dict(headers)
            return {
                "symbol": "BTCUSDT",
                "orderId": 42,
                "clientOrderId": "caos-plan",
                "transactTime": 123456,
                "price": "50000",
                "origQty": "0.001",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
                "status": "NEW",
                "type": "LIMIT",
                "side": "BUY",
            }

        client = BinanceSpotClient(
            "key",
            "secret",
            time_ms=lambda: 123456,
            transport=transport,
        )
        ack = client.place_order(
            symbol="btcusdt",
            side="BUY",
            order_type="LIMIT",
            qty="0.001",
            price="50000",
            order_link_id="caos-plan",
        )
        self.assertEqual(
            captured["url"],
            "https://testnet.binance.vision/api/v3/order",
        )
        self.assertEqual(
            captured["method"],
            "POST",
        )
        self.assertEqual(
            captured["body"]["symbol"],
            "BTCUSDT",
        )
        self.assertEqual(
            captured["body"]["type"],
            "LIMIT",
        )
        self.assertEqual(
            captured["body"]["newClientOrderId"],
            "caos-plan",
        )
        self.assertEqual(ack.order_id, "42")
        self.assertEqual(
            captured["headers"]["X-MBX-APIKEY"],
            "key",
        )
        self.assertIn(
            "signature",
            captured["body"],
        )

    def test_account_info_authentication(self):
        captured = {}

        def transport(method, url, data, headers):
            del data
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = dict(headers)
            return {
                "canTrade": True,
                "canWithdraw": False,
                "canDeposit": True,
                "accountType": "SPOT",
                "permissions": ["SPOT"],
                "balances": [
                    {
                        "asset": "JPY",
                        "free": "1000",
                        "locked": "0",
                    },
                    {
                        "asset": "BTC",
                        "free": "0",
                        "locked": "0",
                    },
                ],
            }

        client = BinanceSpotClient(
            "key",
            "secret",
            environment="production-readonly",
            time_ms=lambda: 123456,
            transport=transport,
        )
        info = client.get_account_info()
        self.assertTrue(info["can_trade"])
        self.assertEqual(
            info["account_type"],
            "SPOT",
        )
        self.assertEqual(
            info["balances_nonzero"][0]["asset"],
            "JPY",
        )
        self.assertIn(
            "/api/v3/account?",
            captured["url"],
        )
        self.assertEqual(
            captured["headers"]["X-MBX-APIKEY"],
            "key",
        )

    def test_production_profile_cannot_submit_orders(self):
        client = BinanceSpotClient(
            "key",
            "secret",
            environment="production-readonly",
            transport=lambda *args: {},
        )
        with self.assertRaises(TestnetError):
            client.place_order(
                symbol="BTCJPY",
                side="BUY",
                order_type="MARKET",
                qty="0.001",
            )

    def test_human_gate_required_for_testnet_order(self):
        compliance = ComplianceEngine()
        calls = {"count": 0}

        def transport(method, url, data, headers):
            del method, url, headers
            calls["count"] += 1
            body = dict(
                urllib.parse.parse_qsl(
                    data.decode()
                )
            )
            return {
                "symbol": "BTCUSDT",
                "orderId": 1,
                "clientOrderId": body.get(
                    "newClientOrderId",
                    "",
                ),
                "origQty": body["quantity"],
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
                "status": "NEW",
                "type": body["type"],
                "side": body["side"],
            }

        client = BinanceSpotClient(
            "key",
            "secret",
            transport=transport,
        )
        executor = HumanTestnetExecutor(
            compliance,
            client,
        )
        with self.assertRaises(ComplianceViolation):
            executor.place_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty="0.001",
            )
        self.assertEqual(calls["count"], 0)

        compliance.human_arm_testnet(
            confirmation="ARM TESTNET"
        )
        ack = executor.place_order(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty="0.001",
        )
        self.assertEqual(ack.order_id, "1")
        self.assertEqual(calls["count"], 1)


if __name__ == "__main__":
    unittest.main()
