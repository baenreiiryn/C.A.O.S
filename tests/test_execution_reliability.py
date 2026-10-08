import hashlib
import hmac
import json
import tempfile
import urllib.parse
import unittest
from pathlib import Path

from caos.compliance import ComplianceEngine, ComplianceViolation
from caos.execution_fabric import (
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from caos.execution_reliability import (
    DurableExecutionJournal,
    ExecutionReliabilityError,
)
from caos.store import Store
from caos.testnet import (
    BinanceSpotClient,
    ReliableHumanTestnetExecutor,
    TestnetError,
    execution_plan_to_binance_order,
)


def sample_plan():
    decision = decision_from_signal(
        symbol="BTCUSDT",
        strategy_id="reliable-momentum",
        signal="long",
        requested_weight=0.2,
        as_of=123,
    )
    target = resolve_target_position(
        decision,
        equity=100.0,
        max_notional=20.0,
    )
    return plan_execution(
        target,
        current_notional=0.0,
        reference_price=50_000.0,
    )


def broker_row(plan, *, qty=None):
    payload = execution_plan_to_binance_order(plan)
    quantity = qty if qty is not None else payload["qty"]
    return {
        "symbol": payload["symbol"],
        "orderId": 77,
        "clientOrderId": payload["order_link_id"],
        "price": "0",
        "origQty": quantity,
        "executedQty": quantity,
        "cummulativeQuoteQty": "20",
        "status": "FILLED",
        "timeInForce": "GTC",
        "type": payload["order_type"],
        "side": payload["side"],
    }


class ExecutionReliabilityJournalTests(unittest.TestCase):
    def test_prepare_is_idempotent_and_payload_conflict_fails(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            journal = DurableExecutionJournal(store)
            plan = sample_plan()
            payload = execution_plan_to_binance_order(plan)

            first = journal.prepare(plan, payload)
            second = journal.prepare(plan, payload)
            self.assertEqual(
                first["intent_id"],
                second["intent_id"],
            )
            self.assertEqual(first["status"], "prepared")
            self.assertEqual(first["venue"], "binance")
            self.assertEqual(
                first["environment"],
                "spot-testnet",
            )
            self.assertEqual(
                journal.summary()["counts"]["prepared"],
                1,
            )

            conflicting = dict(payload)
            conflicting["qty"] = "99"
            with self.assertRaises(
                ExecutionReliabilityError
            ):
                journal.prepare(plan, conflicting)

            serialized = json.dumps(
                journal.get(first["intent_id"])
            )
            self.assertNotIn(
                "api_secret",
                serialized.lower(),
            )
            self.assertNotIn(
                "api_key",
                serialized.lower(),
            )
            store.close()

    def test_journal_scope_ignores_legacy_other_venue_rows(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()
            legacy = DurableExecutionJournal(
                store,
                venue="legacy",
                environment="old",
            )
            legacy.prepare(
                plan,
                execution_plan_to_binance_order(plan),
            )
            binance = DurableExecutionJournal(store)
            self.assertEqual(binance.list(), [])
            self.assertEqual(
                binance.summary()["total"],
                0,
            )
            store.close()

    def test_submit_claim_is_atomic_across_journals(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            first = DurableExecutionJournal(store)
            second = DurableExecutionJournal(store)
            plan = sample_plan()
            row = first.prepare(
                plan,
                execution_plan_to_binance_order(plan),
            )
            first.claim_for_submit(row["intent_id"])
            with self.assertRaises(
                ExecutionReliabilityError
            ):
                second.claim_for_submit(
                    row["intent_id"]
                )
            self.assertEqual(
                second.get(row["intent_id"])["status"],
                "submitting",
            )
            store.close()


class ReliableBinanceExecutorTests(unittest.TestCase):
    def make_executor(self, store, transport):
        compliance = ComplianceEngine()
        compliance.human_arm_testnet(
            confirmation="ARM TESTNET"
        )
        client = BinanceSpotClient(
            "test-key",
            "test-secret",
            time_ms=lambda: 1_700_000_000_000,
            transport=transport,
        )
        journal = DurableExecutionJournal(store)
        return (
            ReliableHumanTestnetExecutor(
                compliance,
                client,
                journal,
            ),
            journal,
        )

    @staticmethod
    def ack_from_post(data):
        body = dict(
            urllib.parse.parse_qsl(
                data.decode()
            )
        )
        return {
            "symbol": body["symbol"],
            "orderId": 101,
            "clientOrderId": body[
                "newClientOrderId"
            ],
            "price": body.get("price", "0"),
            "origQty": body["quantity"],
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
            "status": "NEW",
            "timeInForce": body.get(
                "timeInForce",
                "GTC",
            ),
            "type": body["type"],
            "side": body["side"],
        }

    def test_reliable_submit_still_requires_human_arm(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0}

            def transport(method, url, data, headers):
                del url, headers
                if method == "POST":
                    calls["post"] += 1
                return self.ack_from_post(data)

            client = BinanceSpotClient(
                "key",
                "secret",
                transport=transport,
            )
            journal = DurableExecutionJournal(store)
            executor = ReliableHumanTestnetExecutor(
                ComplianceEngine(),
                client,
                journal,
            )
            with self.assertRaises(
                ComplianceViolation
            ):
                executor.submit_plan(sample_plan())
            self.assertEqual(calls["post"], 0)
            self.assertEqual(journal.list(), [])
            store.close()

    def test_successful_submission_is_idempotent_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0}

            def transport(method, url, data, headers):
                del url, headers
                if method == "POST":
                    calls["post"] += 1
                    return self.ack_from_post(data)
                raise AssertionError("unexpected GET")

            executor, journal = self.make_executor(
                store,
                transport,
            )
            plan = sample_plan()
            first = executor.submit_plan(plan)
            self.assertEqual(
                first["status"],
                "acknowledged",
            )
            second = executor.submit_plan(plan)
            self.assertEqual(
                second["status"],
                "acknowledged",
            )
            restarted, _ = self.make_executor(
                store,
                transport,
            )
            third = restarted.submit_plan(plan)
            self.assertEqual(
                third["status"],
                "acknowledged",
            )
            self.assertEqual(calls["post"], 1)
            self.assertEqual(
                journal.summary()["counts"][
                    "acknowledged"
                ],
                1,
            )
            store.close()

    def test_ambiguous_submission_reconciles_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()
            calls = {"post": 0, "get": 0}

            def transport(method, url, data, headers):
                del headers
                if method == "POST":
                    calls["post"] += 1
                    raise TimeoutError(
                        "connection lost after broker accepted"
                    )
                calls["get"] += 1
                self.assertIn(
                    "origClientOrderId=",
                    url,
                )
                return broker_row(plan)

            executor, journal = self.make_executor(
                store,
                transport,
            )
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            self.assertEqual(
                intent["status"],
                "uncertain",
            )
            with self.assertRaises(TestnetError):
                executor.submit_plan(plan)
            self.assertEqual(calls["post"], 1)

            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(
                result["status"],
                "reconciled",
            )
            self.assertEqual(
                result["reconciliation_status"],
                "matched",
            )
            again = executor.submit_plan(plan)
            self.assertEqual(
                again["status"],
                "reconciled",
            )
            self.assertEqual(calls["post"], 1)
            store.close()

    def test_not_found_stays_uncertain_and_can_be_abandoned(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0}

            def transport(method, url, data, headers):
                del url, data, headers
                if method == "POST":
                    calls["post"] += 1
                    raise TimeoutError("ambiguous")
                return {
                    "code": -2013,
                    "msg": "Order does not exist.",
                }

            executor, journal = self.make_executor(
                store,
                transport,
            )
            plan = sample_plan()
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(
                result["status"],
                "uncertain",
            )
            self.assertEqual(
                result["reconciliation_status"],
                "not_found",
            )
            abandoned = journal.abandon_not_found(
                intent["intent_id"]
            )
            self.assertEqual(
                abandoned["status"],
                "abandoned",
            )
            with self.assertRaises(TestnetError):
                executor.submit_plan(plan)
            self.assertEqual(calls["post"], 1)
            store.close()

    def test_broker_payload_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()

            def transport(method, url, data, headers):
                del url, data, headers
                if method == "POST":
                    raise TimeoutError("ambiguous")
                return broker_row(plan, qty="999")

            executor, journal = self.make_executor(
                store,
                transport,
            )
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(
                result["status"],
                "uncertain",
            )
            self.assertIn(
                "qty_mismatch",
                result["issues"],
            )
            store.close()

    def test_invalid_ack_identity_becomes_uncertain(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")

            def transport(method, url, data, headers):
                del method, url, data, headers
                return {
                    "orderId": "",
                    "clientOrderId": "wrong-link",
                }

            executor, journal = self.make_executor(
                store,
                transport,
            )
            with self.assertRaises(TestnetError):
                executor.submit_plan(sample_plan())
            row = journal.list()[0]
            self.assertEqual(
                row["status"],
                "uncertain",
            )
            self.assertIn(
                "broker_ack_identity_invalid",
                row["last_error"],
            )
            store.close()

    def test_reconciliation_is_read_only_without_testnet_arm(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()
            journal = DurableExecutionJournal(store)
            row = journal.prepare(
                plan,
                execution_plan_to_binance_order(plan),
            )
            journal.claim_for_submit(
                row["intent_id"]
            )
            journal.mark_uncertain(
                row["intent_id"],
                error="restart_recovery",
            )

            def transport(method, url, data, headers):
                del url, data, headers
                if method != "GET":
                    raise AssertionError(
                        "recovery must not submit"
                    )
                return broker_row(plan)

            executor = ReliableHumanTestnetExecutor(
                ComplianceEngine(),
                BinanceSpotClient(
                    "key",
                    "secret",
                    transport=transport,
                ),
                journal,
            )
            result = executor.reconcile_intent(
                row["intent_id"]
            )
            self.assertEqual(
                result["status"],
                "reconciled",
            )
            store.close()

    def test_signed_order_lookup_uses_orig_client_order_id(self):
        calls = []
        plan = sample_plan()
        payload = execution_plan_to_binance_order(plan)
        timestamp = 1_700_000_000_000
        secret = "secret"

        def transport(method, url, data, headers):
            del data
            calls.append(
                (method, url, dict(headers))
            )
            return broker_row(plan)

        client = BinanceSpotClient(
            "key",
            secret,
            time_ms=lambda: timestamp,
            transport=transport,
        )
        found = client.find_order(
            symbol="BTCUSDT",
            order_link_id=payload[
                "order_link_id"
            ],
        )
        self.assertEqual(
            found["order_id"],
            "77",
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "GET")
        query = dict(
            urllib.parse.parse_qsl(
                calls[0][1].split("?", 1)[1]
            )
        )
        signature = query.pop("signature")
        unsigned = urllib.parse.urlencode(
            sorted(query.items())
        )
        expected = hmac.new(
            secret.encode(),
            unsigned.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(
            query["origClientOrderId"],
            payload["order_link_id"],
        )


if __name__ == "__main__":
    unittest.main()
