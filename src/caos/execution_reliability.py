from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .execution_fabric import ExecutionPlan
from .store import Store


EXECUTION_RELIABILITY_VERSION = "execution-reliability/v1"


class ExecutionReliabilityError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ReconciliationResult:
    intent_id: str
    status: str
    reconciliation_status: str
    issues: tuple[str, ...]
    broker_order: dict | None

    def to_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "status": self.status,
            "reconciliation_status": self.reconciliation_status,
            "issues": list(self.issues),
            "broker_order": self.broker_order,
        }


def canonical_payload_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def execution_intent_id(
    *,
    venue: str,
    environment: str,
    plan_id: str,
) -> str:
    encoded = (
        f"{venue}|{environment}|{plan_id}"
    ).encode("utf-8")
    return "intent-" + hashlib.sha256(encoded).hexdigest()[:24]


def _decimal_equal(a, b, *, tolerance: Decimal = Decimal("0.00000001")) -> bool:
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= tolerance
    except (InvalidOperation, ValueError):
        return False


def compare_intent_to_broker_order(
    intent: dict,
    broker_order: dict,
) -> tuple[str, ...]:
    payload = intent["payload"]
    issues: list[str] = []

    expected = {
        "order_link_id": str(payload.get("order_link_id", "")),
        "symbol": str(payload.get("symbol", "")).upper(),
        "side": str(payload.get("side", "")),
        "order_type": str(payload.get("order_type", "")),
        "qty": payload.get("qty"),
    }
    actual = {
        "order_link_id": str(
            broker_order.get("order_link_id", "")
        ),
        "symbol": str(
            broker_order.get("symbol", "")
        ).upper(),
        "side": str(broker_order.get("side", "")),
        "order_type": str(
            broker_order.get("order_type", "")
        ),
        "qty": broker_order.get("qty"),
    }

    for key in (
        "order_link_id",
        "symbol",
        "side",
        "order_type",
    ):
        if expected[key] != actual[key]:
            issues.append(f"{key}_mismatch")

    if not _decimal_equal(expected["qty"], actual["qty"]):
        issues.append("qty_mismatch")

    return tuple(issues)


class DurableExecutionJournal:
    """Persistent execution intent/outbox journal.

    Credentials are intentionally never accepted or stored.
    """

    def __init__(
        self,
        store: Store,
        *,
        venue: str = "binance",
        environment: str = "spot-testnet",
    ):
        if store is None:
            raise ExecutionReliabilityError(
                "persistent_store_required"
            )
        self.store = store
        self.venue = venue
        self.environment = environment

    def prepare(
        self,
        plan: ExecutionPlan,
        payload: dict,
    ) -> dict:
        intent_id = execution_intent_id(
            venue=self.venue,
            environment=self.environment,
            plan_id=plan.plan_id,
        )
        payload_hash = canonical_payload_hash(payload)
        row = self.store.prepare_execution_intent(
            intent_id=intent_id,
            plan_id=plan.plan_id,
            venue=self.venue,
            environment=self.environment,
            symbol=plan.symbol,
            payload=payload,
            payload_hash=payload_hash,
        )
        if row["intent_id"] != intent_id:
            raise ExecutionReliabilityError(
                "execution_intent_identity_mismatch"
            )
        if row["payload_hash"] != payload_hash:
            raise ExecutionReliabilityError(
                "execution_intent_payload_conflict"
            )
        return row

    def get(self, intent_id: str) -> dict:
        row = self.store.get_execution_intent(intent_id)
        if row is None:
            raise ExecutionReliabilityError(
                "unknown_execution_intent"
            )
        return row

    def list(
        self,
        *,
        limit: int = 100,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict]:
        return self.store.list_execution_intents(
            limit=limit,
            statuses=statuses,
            venue=self.venue,
            environment=self.environment,
        )

    def claim_for_submit(self, intent_id: str) -> dict:
        row = self.get(intent_id)
        if row["status"] in {"acknowledged", "reconciled"}:
            return row
        if row["status"] != "prepared":
            raise ExecutionReliabilityError(
                "execution_intent_requires_reconciliation"
            )
        claimed = self.store.transition_execution_intent(
            intent_id,
            from_statuses=("prepared",),
            to_status="submitting",
        )
        if claimed:
            self.store.event(
                "execution_intent_submitting",
                {"intent_id": intent_id},
            )
        if not claimed:
            row = self.get(intent_id)
            if row["status"] in {"acknowledged", "reconciled"}:
                return row
            raise ExecutionReliabilityError(
                "execution_intent_submit_claim_failed"
            )
        return self.get(intent_id)

    def mark_acknowledged(
        self,
        intent_id: str,
        *,
        broker_order_id: str,
        broker_order_link_id: str,
        raw: dict,
    ) -> dict:
        changed = self.store.transition_execution_intent(
            intent_id,
            from_statuses=("submitting",),
            to_status="acknowledged",
            broker_order_id=broker_order_id,
            broker_order_link_id=broker_order_link_id,
            reconciliation_status="pending",
            reconciliation_payload=raw,
            last_error=None,
        )
        if changed:
            self.store.event(
                "execution_intent_acknowledged",
                {
                    "intent_id": intent_id,
                    "broker_order_id": broker_order_id,
                    "broker_order_link_id": broker_order_link_id,
                },
            )
        if not changed:
            current = self.get(intent_id)
            if current["status"] in {
                "acknowledged",
                "reconciled",
            }:
                return current
            raise ExecutionReliabilityError(
                "execution_ack_transition_failed"
            )
        return self.get(intent_id)

    def reject_prepared(
        self,
        intent_id: str,
        *,
        reason: str = "human_rejected",
    ) -> dict:
        changed = self.store.transition_execution_intent(
            intent_id,
            from_statuses=("prepared",),
            to_status="rejected",
            reconciliation_status="not_submitted",
            last_error=reason,
        )
        if not changed:
            current = self.get(intent_id)
            if current["status"] == "rejected":
                return current
            raise ExecutionReliabilityError(
                "execution_intent_not_rejectable"
            )
        self.store.event(
            "execution_intent_rejected",
            {
                "intent_id": intent_id,
                "reason": reason,
            },
        )
        return self.get(intent_id)

    def mark_uncertain(
        self,
        intent_id: str,
        *,
        error: str,
    ) -> dict:
        changed = self.store.transition_execution_intent(
            intent_id,
            from_statuses=("submitting",),
            to_status="uncertain",
            reconciliation_status="required",
            last_error=error,
        )
        if changed:
            self.store.event(
                "execution_intent_uncertain",
                {
                    "intent_id": intent_id,
                    "error": error,
                },
            )
        return self.get(intent_id)

    def reconcile(
        self,
        intent_id: str,
        broker_order: dict | None,
    ) -> ReconciliationResult:
        current = self.get(intent_id)
        if broker_order is None:
            if (
                current["status"] == "reconciled"
                and current.get("reconciliation_status") == "matched"
            ):
                return ReconciliationResult(
                    intent_id=intent_id,
                    status="reconciled",
                    reconciliation_status="matched",
                    issues=(),
                    broker_order=current.get(
                        "reconciliation_payload"
                    ),
                )
            self.store.transition_execution_intent(
                intent_id,
                from_statuses=(
                    "submitting",
                    "uncertain",
                    "acknowledged",
                ),
                to_status="uncertain",
                reconciliation_status="not_found",
                reconciliation_payload=None,
                last_error=current.get("last_error"),
            )
            self.store.event(
                "execution_intent_reconciliation_not_found",
                {"intent_id": intent_id},
            )
            row = self.get(intent_id)
            return ReconciliationResult(
                intent_id=intent_id,
                status=row["status"],
                reconciliation_status="not_found",
                issues=(),
                broker_order=None,
            )

        issues = compare_intent_to_broker_order(
            current,
            broker_order,
        )
        if issues:
            self.store.transition_execution_intent(
                intent_id,
                from_statuses=(
                    "submitting",
                    "uncertain",
                    "acknowledged",
                    "reconciled",
                ),
                to_status="uncertain",
                broker_order_id=str(
                    broker_order.get("order_id", "")
                ),
                broker_order_link_id=str(
                    broker_order.get(
                        "order_link_id",
                        "",
                    )
                ),
                reconciliation_status="mismatch",
                reconciliation_payload=broker_order,
                last_error=";".join(issues),
            )
            self.store.event(
                "execution_intent_reconciliation_mismatch",
                {
                    "intent_id": intent_id,
                    "issues": list(issues),
                },
            )
            row = self.get(intent_id)
            return ReconciliationResult(
                intent_id=intent_id,
                status=row["status"],
                reconciliation_status="mismatch",
                issues=issues,
                broker_order=broker_order,
            )

        self.store.transition_execution_intent(
            intent_id,
            from_statuses=(
                "submitting",
                "uncertain",
                "acknowledged",
                "reconciled",
            ),
            to_status="reconciled",
            broker_order_id=str(
                broker_order.get("order_id", "")
            ),
            broker_order_link_id=str(
                broker_order.get("order_link_id", "")
            ),
            reconciliation_status="matched",
            reconciliation_payload=broker_order,
            last_error=None,
        )
        self.store.event(
            "execution_intent_reconciled",
            {
                "intent_id": intent_id,
                "broker_order_id": str(
                    broker_order.get("order_id", "")
                ),
            },
        )
        row = self.get(intent_id)
        return ReconciliationResult(
            intent_id=intent_id,
            status=row["status"],
            reconciliation_status="matched",
            issues=(),
            broker_order=broker_order,
        )

    def abandon_not_found(
        self,
        intent_id: str,
    ) -> dict:
        current = self.get(intent_id)
        if (
            current["status"] != "uncertain"
            or current.get("reconciliation_status")
            != "not_found"
        ):
            raise ExecutionReliabilityError(
                "only_confirmed_not_found_intent_can_be_abandoned"
            )
        changed = self.store.transition_execution_intent(
            intent_id,
            from_statuses=("uncertain",),
            to_status="abandoned",
            reconciliation_status="not_found_abandoned",
            reconciliation_payload=None,
            last_error=current.get("last_error"),
        )
        if not changed:
            raise ExecutionReliabilityError(
                "execution_intent_abandon_transition_failed"
            )
        self.store.event(
            "execution_intent_abandoned",
            {"intent_id": intent_id},
        )
        return self.get(intent_id)

    def recovery_candidates(self) -> list[dict]:
        return self.list(
            statuses=(
                "submitting",
                "uncertain",
                "acknowledged",
            )
        )

    def summary(self) -> dict:
        counts = self.store.execution_intent_counts(
            venue=self.venue,
            environment=self.environment,
        )
        return {
            "version": EXECUTION_RELIABILITY_VERSION,
            "venue": self.venue,
            "environment": self.environment,
            "counts": counts,
            "total": sum(counts.values()),
            "recovery_required": sum(
                counts.get(status, 0)
                for status in (
                    "submitting",
                    "uncertain",
                    "acknowledged",
                )
            ),
        }
