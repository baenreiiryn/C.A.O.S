import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from caos.compliance import ComplianceEngine
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
    BybitTestnetClient,
    ReliableHumanTestnetExecutor,
    TestnetError,
    execution_plan_to_bybit_order,
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
    payload = execution_plan_to_bybit_order(plan)
    return {
        "orderId": "broker-order-1",
        "orderLinkId": payload["order_link_id"],
        "symbol": payload["symbol"],
        "side": payload["side"],
        "orderType": payload["order_type"],
        "qty": qty if qty is not None else payload["qty"],
        "reduceOnly": payload["reduce_only"],
        "orderStatus": "Filled",
        "cumExecQty": payload["qty"],
        "avgPrice": "50000",
    }


class ExecutionReliabilityJournalTests(unittest.TestCase):
    def test_prepare_is_idempotent_and_payload_conflict_fails(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            journal = DurableExecutionJournal(store)
            plan = sample_plan()
            payload = execution_plan_to_bybit_order(plan)

            first = journal.prepare(plan, payload)
            second = journal.prepare(plan, payload)
            self.assertEqual(first["intent_id"], second["intent_id"])
            self.assertEqual(first["status"], "prepared")
            self.assertEqual(
                journal.summary()["counts"]["prepared"],
                1,
            )

            conflicting = dict(payload)
            conflicting["category"] = "spot"
            with self.assertRaises(ExecutionReliabilityError):
                journal.prepare(plan, conflicting)

            serialized = json.dumps(journal.get(first["intent_id"]))
            self.assertNotIn("api_secret", serialized.lower())
            self.assertNotIn("api_key", serialized.lower())
            store.close()

    def test_submit_claim_is_atomic_across_journals(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            first = DurableExecutionJournal(store)
            second = DurableExecutionJournal(store)
            plan = sample_plan()
            row = first.prepare(
                plan,
                execution_plan_to_bybit_order(plan),
            )
            first.claim_for_submit(row["intent_id"])
            with self.assertRaises(ExecutionReliabilityError):
                second.claim_for_submit(row["intent_id"])
            self.assertEqual(
                second.get(row["intent_id"])["status"],
                "submitting",
            )
            store.close()


class ReliableTestnetExecutorTests(unittest.TestCase):
    def make_executor(
        self,
        store,
        *,
        post_transport,
        query_transport=None,
    ):
        compliance = ComplianceEngine()
        compliance.human_arm_testnet(
            confirmation="ARM TESTNET"
        )
        client = BybitTestnetClient(
            "test-key",
            "test-secret",
            time_ms=lambda: 1_700_000_000_000,
            transport=post_transport,
            query_transport=query_transport,
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

    def test_successful_submission_is_idempotent_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0}

            def post(url, data, headers):
                del url, headers
                calls["post"] += 1
                body = json.loads(data.decode())
                return {
                    "retCode": 0,
                    "result": {
                        "orderId": "order-1",
                        "orderLinkId": body["orderLinkId"],
                    },
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
            )
            plan = sample_plan()
            first = executor.submit_plan(plan)
            self.assertEqual(first["status"], "acknowledged")
            self.assertEqual(calls["post"], 1)

            second = executor.submit_plan(plan)
            self.assertEqual(second["status"], "acknowledged")
            self.assertEqual(calls["post"], 1)

            restarted, _ = self.make_executor(
                store,
                post_transport=post,
            )
            third = restarted.submit_plan(plan)
            self.assertEqual(third["status"], "acknowledged")
            self.assertEqual(calls["post"], 1)
            self.assertEqual(
                journal.summary()["counts"]["acknowledged"],
                1,
            )
            store.close()

    def test_ambiguous_submission_never_retries_before_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0, "query": 0}
            plan = sample_plan()

            def post(url, data, headers):
                del url, data, headers
                calls["post"] += 1
                raise TimeoutError(
                    "connection lost after broker accepted order"
                )

            def query(url, headers):
                del headers
                calls["query"] += 1
                return {
                    "retCode": 0,
                    "result": {
                        "list": [broker_row(plan)],
                    },
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)

            intent = journal.list()[0]
            self.assertEqual(intent["status"], "uncertain")
            self.assertEqual(calls["post"], 1)

            with self.assertRaises(TestnetError):
                executor.submit_plan(plan)
            self.assertEqual(calls["post"], 1)

            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(result["status"], "reconciled")
            self.assertEqual(
                result["reconciliation_status"],
                "matched",
            )

            again = executor.submit_plan(plan)
            self.assertEqual(again["status"], "reconciled")
            self.assertEqual(calls["post"], 1)
            store.close()

    def test_not_found_stays_uncertain_and_cannot_auto_retry(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0, "query": 0}

            def post(url, data, headers):
                del url, data, headers
                calls["post"] += 1
                raise TimeoutError("ambiguous")

            def query(url, headers):
                del url, headers
                calls["query"] += 1
                return {
                    "retCode": 0,
                    "result": {"list": []},
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            plan = sample_plan()
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(result["status"], "uncertain")
            self.assertEqual(
                result["reconciliation_status"],
                "not_found",
            )
            self.assertEqual(calls["query"], 2)

            with self.assertRaises(TestnetError):
                executor.submit_plan(plan)
            self.assertEqual(calls["post"], 1)
            store.close()

    def test_confirmed_missing_intent_can_be_abandoned_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            calls = {"post": 0}

            def post(url, data, headers):
                del url, data, headers
                calls["post"] += 1
                raise TimeoutError("ambiguous")

            def query(url, headers):
                del url, headers
                return {
                    "retCode": 0,
                    "result": {"list": []},
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            plan = sample_plan()
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            result = executor.reconcile_intent(
                intent["intent_id"]
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
            self.assertEqual(
                journal.summary()["recovery_required"],
                0,
            )
            with self.assertRaises(TestnetError):
                executor.submit_plan(plan)
            self.assertEqual(calls["post"], 1)
            store.close()

    def test_broker_payload_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()

            def post(url, data, headers):
                del url, data, headers
                raise TimeoutError("ambiguous")

            def query(url, headers):
                del url, headers
                return {
                    "retCode": 0,
                    "result": {
                        "list": [
                            broker_row(plan, qty="999")
                        ]
                    },
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            intent = journal.list()[0]
            result = executor.reconcile_intent(
                intent["intent_id"]
            )
            self.assertEqual(result["status"], "uncertain")
            self.assertEqual(
                result["reconciliation_status"],
                "mismatch",
            )
            self.assertIn("qty_mismatch", result["issues"])
            store.close()

    def test_reconciled_intent_is_not_downgraded_by_later_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()
            visible = {"value": True}

            def post(url, data, headers):
                del url, headers
                body = json.loads(data.decode())
                return {
                    "retCode": 0,
                    "result": {
                        "orderId": "order-1",
                        "orderLinkId": body["orderLinkId"],
                    },
                }

            def query(url, headers):
                del url, headers
                return {
                    "retCode": 0,
                    "result": {
                        "list": (
                            [broker_row(plan)]
                            if visible["value"]
                            else []
                        )
                    },
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            row = executor.submit_plan(plan)
            matched = executor.reconcile_intent(
                row["intent_id"]
            )
            self.assertEqual(matched["status"], "reconciled")

            visible["value"] = False
            still = executor.reconcile_intent(
                row["intent_id"]
            )
            self.assertEqual(still["status"], "reconciled")
            self.assertEqual(
                journal.get(row["intent_id"])[
                    "reconciliation_status"
                ],
                "matched",
            )
            store.close()

    def test_recovery_reconciles_all_pending_without_resubmit(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()
            calls = {"post": 0}

            def post(url, data, headers):
                del url, data, headers
                calls["post"] += 1
                raise TimeoutError("ambiguous")

            def query(url, headers):
                del url, headers
                return {
                    "retCode": 0,
                    "result": {
                        "list": [broker_row(plan)]
                    },
                }

            executor, journal = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            with self.assertRaises(TimeoutError):
                executor.submit_plan(plan)
            recovered = executor.recover()
            self.assertEqual(len(recovered), 1)
            self.assertEqual(
                recovered[0]["status"],
                "reconciled",
            )
            self.assertEqual(calls["post"], 1)
            self.assertEqual(
                journal.summary()["recovery_required"],
                0,
            )
            store.close()


    def test_reliability_transitions_are_audited(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "reliability.db")
            plan = sample_plan()

            def post(url, data, headers):
                del url, headers
                body = json.loads(data.decode())
                return {
                    "retCode": 0,
                    "result": {
                        "orderId": "order-audit",
                        "orderLinkId": body["orderLinkId"],
                    },
                }

            def query(url, headers):
                del url, headers
                return {
                    "retCode": 0,
                    "result": {
                        "list": [broker_row(plan)]
                    },
                }

            executor, _ = self.make_executor(
                store,
                post_transport=post,
                query_transport=query,
            )
            row = executor.submit_plan(plan)
            executor.reconcile_intent(row["intent_id"])
            kinds = {
                event["kind"]
                for event in store.recent_events(20)
            }
            self.assertIn(
                "execution_intent_submitting",
                kinds,
            )
            self.assertIn(
                "execution_intent_acknowledged",
                kinds,
            )
            self.assertIn(
                "execution_intent_reconciled",
                kinds,
            )
            store.close()


class BybitReconciliationQueryTests(unittest.TestCase):
    def test_find_order_uses_realtime_then_history_and_signed_query(self):
        calls = []
        plan = sample_plan()
        payload = execution_plan_to_bybit_order(plan)
        timestamp = 1_700_000_000_000
        secret = "secret"

        def query(url, headers):
            calls.append((url, dict(headers)))
            if "/v5/order/realtime" in url:
                return {
                    "retCode": 0,
                    "result": {"list": []},
                }
            return {
                "retCode": 0,
                "result": {
                    "list": [broker_row(plan)]
                },
            }

        client = BybitTestnetClient(
            "key",
            secret,
            time_ms=lambda: timestamp,
            transport=lambda *args: {
                "retCode": 0,
                "result": {},
            },
            query_transport=query,
        )
        found = client.find_order(
            category="linear",
            symbol="BTCUSDT",
            order_link_id=payload["order_link_id"],
        )
        self.assertEqual(found["order_id"], "broker-order-1")
        self.assertEqual(len(calls), 2)
        self.assertIn("/v5/order/realtime?", calls[0][0])
        self.assertIn("/v5/order/history?", calls[1][0])

        query_string = calls[0][0].split("?", 1)[1]
        message = (
            f"{timestamp}key5000{query_string}"
        )
        expected = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            calls[0][1]["X-BAPI-SIGN"],
            expected,
        )


if __name__ == "__main__":
    unittest.main()
