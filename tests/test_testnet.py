import hashlib
import hmac
import json
import unittest

from caos.compliance import ComplianceEngine, ComplianceViolation
from caos.testnet import (
    BybitTestnetClient,
    HumanTestnetExecutor,
    TestnetError,
)


class TestnetTests(unittest.TestCase):
    def test_production_host_is_impossible(self):
        with self.assertRaises(TestnetError):
            BybitTestnetClient(
                "key",
                "secret",
                base_url="https://api.bybit.com",
            )

    def test_signature_matches_documented_formula(self):
        timestamp = 1658385589135
        key = "abc"
        secret = "xyz"
        body = '{"category":"linear"}'
        client = BybitTestnetClient(
            key,
            secret,
            time_ms=lambda: timestamp,
            transport=lambda u, d, h: {},
        )
        expected = hmac.new(
            secret.encode(),
            f"{timestamp}{key}5000{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            client.signature(timestamp, body),
            expected,
        )

    def test_order_headers_and_body(self):
        captured = {}

        def transport(url, data, headers):
            captured["url"] = url
            captured["body"] = data.decode()
            captured["headers"] = headers
            return {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "orderId": "id-1",
                    "orderLinkId": "caos-1",
                },
            }

        client = BybitTestnetClient(
            "key",
            "secret",
            time_ms=lambda: 123456,
            transport=transport,
        )
        ack = client.place_order(
            category="linear",
            symbol="btcusdt",
            side="Buy",
            order_type="Limit",
            qty="0.001",
            price="50000",
            order_link_id="caos-1",
        )
        self.assertEqual(
            captured["url"],
            "https://api-testnet.bybit.com/v5/order/create",
        )
        body = json.loads(captured["body"])
        self.assertEqual(body["symbol"], "BTCUSDT")
        self.assertEqual(body["orderType"], "Limit")
        self.assertEqual(ack.order_id, "id-1")
        self.assertIn("X-BAPI-SIGN", captured["headers"])
        self.assertEqual(
            captured["headers"]["X-BAPI-TIMESTAMP"],
            "123456",
        )

    def test_human_gate_required(self):
        compliance = ComplianceEngine()
        client = BybitTestnetClient(
            "key",
            "secret",
            transport=lambda u, d, h: {
                "retCode": 0,
                "result": {"orderId": "1", "orderLinkId": ""},
            },
        )
        executor = HumanTestnetExecutor(compliance, client)
        with self.assertRaises(ComplianceViolation):
            executor.place_order(
                category="linear",
                symbol="BTCUSDT",
                side="Buy",
                order_type="Market",
                qty="0.001",
            )

        compliance.human_arm_testnet(
            confirmation="ARM TESTNET"
        )
        ack = executor.place_order(
            category="linear",
            symbol="BTCUSDT",
            side="Buy",
            order_type="Market",
            qty="0.001",
        )
        self.assertEqual(ack.order_id, "1")


if __name__ == "__main__":
    unittest.main()
