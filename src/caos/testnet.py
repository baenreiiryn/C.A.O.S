from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .compliance import ComplianceEngine
from .domain import Mode
from .execution_fabric import ExecutionPlan
from .execution_reliability import (
    DurableExecutionJournal,
    ExecutionReliabilityError,
)


class TestnetError(RuntimeError):
    pass


@dataclass(slots=True)
class TestnetOrderAck:
    order_id: str
    order_link_id: str
    raw: dict[str, Any]


def execution_plan_to_bybit_order(
    plan: ExecutionPlan,
    *,
    category: str = "linear",
    order_type: str = "Market",
    quantity_decimals: int = 8,
) -> dict[str, Any]:
    """Translate a venue-agnostic plan into a Bybit TESTNET order payload."""
    if not plan.executable or plan.side is None:
        raise TestnetError("execution_plan_not_executable")
    if category not in {"linear", "inverse", "spot"}:
        raise ValueError("unsupported category")
    if order_type not in {"Market", "Limit"}:
        raise ValueError("order_type must be Market or Limit")
    if quantity_decimals < 0 or quantity_decimals > 16:
        raise ValueError("invalid_quantity_decimals")

    qty = plan.order_notional / plan.reference_price
    if qty <= 0:
        raise TestnetError("execution_plan_quantity_invalid")
    qty_text = f"{qty:.{quantity_decimals}f}".rstrip("0").rstrip(".")
    if not qty_text:
        raise TestnetError("execution_plan_quantity_rounds_to_zero")

    payload: dict[str, Any] = {
        "category": category,
        "symbol": plan.symbol,
        "side": "Buy" if plan.side == "buy" else "Sell",
        "order_type": order_type,
        "qty": qty_text,
        "reduce_only": bool(plan.risk_reducing),
        "order_link_id": plan.plan_id[:36],
    }
    if order_type == "Limit":
        payload["price"] = str(plan.reference_price)
    return payload


class BybitTestnetClient:
    """Minimal authenticated Bybit V5 client hard-locked to TESTNET."""

    TESTNET_BASE_URL = "https://api-testnet.bybit.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        recv_window: int = 5000,
        base_url: str = TESTNET_BASE_URL,
        time_ms: Callable[[], int] | None = None,
        transport: Callable[[str, bytes, dict[str, str]], dict] | None = None,
        query_transport: Callable[[str, dict[str, str]], dict] | None = None,
    ):
        if base_url.rstrip("/") != self.TESTNET_BASE_URL:
            raise TestnetError("production_or_unknown_bybit_host_forbidden")
        if not api_key or not api_secret:
            raise TestnetError("testnet_credentials_required")
        if recv_window <= 0:
            raise ValueError("recv_window must be positive")
        self.api_key = api_key
        self._api_secret = api_secret
        self.recv_window = int(recv_window)
        self.base_url = self.TESTNET_BASE_URL
        self._time_ms = time_ms or (lambda: int(time.time() * 1000))
        self._transport = transport or self._urllib_transport
        self._query_transport = (
            query_transport or self._urllib_query_transport
        )

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def signature(
        self,
        timestamp: int,
        body_string: str,
    ) -> str:
        message = (
            f"{timestamp}{self.api_key}{self.recv_window}{body_string}"
        )
        return hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _urllib_transport(
        url: str,
        data: bytes,
        headers: dict[str, str],
    ) -> dict:
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _urllib_query_transport(
        url: str,
        headers: dict[str, str],
    ) -> dict:
        req = urllib.request.Request(
            url,
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _canonical_query(
        params: dict[str, Any],
    ) -> str:
        items = [
            (key, str(value))
            for key, value in sorted(params.items())
            if value is not None
        ]
        return urllib.parse.urlencode(items)

    def _get(
        self,
        path: str,
        params: dict[str, Any],
    ) -> dict:
        timestamp = self._time_ms()
        query = self._canonical_query(params)
        headers = {
            "Content-Type": "application/json",
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "X-BAPI-SIGN": self.signature(timestamp, query),
        }
        url = self.base_url + path
        if query:
            url += "?" + query
        result = self._query_transport(
            url,
            headers,
        )
        if int(result.get("retCode", -1)) != 0:
            raise TestnetError(
                f"bybit_testnet_error:{result.get('retCode')}:{result.get('retMsg')}"
            )
        return result

    def _post(self, path: str, payload: dict[str, Any]) -> dict:
        timestamp = self._time_ms()
        body = self._canonical_json(payload)
        headers = {
            "Content-Type": "application/json",
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "X-BAPI-SIGN": self.signature(timestamp, body),
        }
        result = self._transport(
            self.base_url + path,
            body.encode("utf-8"),
            headers,
        )
        if int(result.get("retCode", -1)) != 0:
            raise TestnetError(
                f"bybit_testnet_error:{result.get('retCode')}:{result.get('retMsg')}"
            )
        return result

    @staticmethod
    def _normalize_order(row: dict[str, Any]) -> dict:
        reduce_only = row.get("reduceOnly", False)
        if isinstance(reduce_only, str):
            reduce_only = reduce_only.lower() == "true"
        return {
            "order_id": str(row.get("orderId", "")),
            "order_link_id": str(
                row.get("orderLinkId", "")
            ),
            "symbol": str(row.get("symbol", "")).upper(),
            "side": str(row.get("side", "")),
            "order_type": str(row.get("orderType", "")),
            "qty": str(row.get("qty", "")),
            "reduce_only": bool(reduce_only),
            "order_status": str(
                row.get("orderStatus", "")
            ),
            "cum_exec_qty": str(
                row.get("cumExecQty", "")
            ),
            "avg_price": str(
                row.get("avgPrice", "")
            ),
            "raw": dict(row),
        }

    def get_api_key_info(self) -> dict:
        """Authenticate the configured TESTNET API key and return safe metadata."""
        result = self._get(
            "/v5/user/query-api",
            {},
        )
        row = result.get("result", {}) or {}
        return {
            "read_only": bool(
                int(row.get("readOnly", 0))
            ),
            "permissions": dict(
                row.get("permissions", {}) or {}
            ),
            "note": str(row.get("note", "")),
            "kyc_level": str(
                row.get("kycLevel", "")
            ),
            "kyc_region": str(
                row.get("kycRegion", "")
            ),
        }

    def find_order(
        self,
        *,
        category: str,
        symbol: str,
        order_link_id: str,
    ) -> dict | None:
        if category not in {"linear", "inverse", "spot"}:
            raise ValueError("unsupported category")
        if not symbol or not order_link_id:
            raise ValueError(
                "symbol_and_order_link_id_required"
            )
        params = {
            "category": category,
            "symbol": symbol.upper(),
            "orderLinkId": order_link_id,
        }
        for path in (
            "/v5/order/realtime",
            "/v5/order/history",
        ):
            result = self._get(path, params)
            rows = (
                result.get("result", {}).get("list", [])
                or []
            )
            for row in rows:
                if str(row.get("orderLinkId", "")) == order_link_id:
                    return self._normalize_order(row)
        return None

    def place_order(
        self,
        *,
        category: str,
        symbol: str,
        side: str,
        order_type: str,
        qty: str,
        price: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        order_link_id: str | None = None,
        trigger_price: str | None = None,
        trigger_direction: int | None = None,
    ) -> TestnetOrderAck:
        if category not in {"linear", "inverse", "spot"}:
            raise ValueError("unsupported category")
        if side not in {"Buy", "Sell"}:
            raise ValueError("side must be Buy or Sell")
        if order_type not in {"Market", "Limit"}:
            raise ValueError("order_type must be Market or Limit")
        if not symbol or not qty:
            raise ValueError("symbol and qty are required")
        if order_type == "Limit" and price is None:
            raise ValueError("limit price required")

        payload: dict[str, Any] = {
            "category": category,
            "symbol": symbol.upper(),
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": time_in_force,
            "reduceOnly": bool(reduce_only),
        }
        if price is not None:
            payload["price"] = str(price)
        if order_link_id:
            payload["orderLinkId"] = order_link_id
        if trigger_price is not None:
            payload["triggerPrice"] = str(trigger_price)
        if trigger_direction is not None:
            payload["triggerDirection"] = int(trigger_direction)

        result = self._post("/v5/order/create", payload)
        data = result.get("result", {})
        return TestnetOrderAck(
            order_id=str(data.get("orderId", "")),
            order_link_id=str(data.get("orderLinkId", "")),
            raw=result,
        )


class HumanTestnetExecutor:
    """Human-gated testnet order surface.

    This class is intentionally not registered as an LLM tool.
    """

    def __init__(
        self,
        compliance: ComplianceEngine,
        client: BybitTestnetClient,
    ):
        self.compliance = compliance
        self.client = client

    def place_order(self, **kwargs) -> TestnetOrderAck:
        self.compliance.allow_mode(Mode.TESTNET)
        return self.client.place_order(**kwargs)

    def execute_plan(
        self,
        plan: ExecutionPlan,
        *,
        category: str = "linear",
        order_type: str = "Market",
        quantity_decimals: int = 8,
    ) -> TestnetOrderAck:
        self.compliance.allow_mode(Mode.TESTNET)
        payload = execution_plan_to_bybit_order(
            plan,
            category=category,
            order_type=order_type,
            quantity_decimals=quantity_decimals,
        )
        return self.client.place_order(**payload)



class ReliableHumanTestnetExecutor:
    """Durable, human-gated ExecutionPlan submission for TESTNET.

    Prepared intents contain no credentials. Ambiguous submissions are never
    automatically resent; they must be reconciled by orderLinkId first.
    """

    def __init__(
        self,
        compliance: ComplianceEngine,
        client: BybitTestnetClient,
        journal: DurableExecutionJournal,
    ):
        self.compliance = compliance
        self.client = client
        self.journal = journal

    def prepare_plan(
        self,
        plan: ExecutionPlan,
        *,
        category: str = "linear",
        order_type: str = "Market",
        quantity_decimals: int = 8,
    ) -> dict:
        payload = execution_plan_to_bybit_order(
            plan,
            category=category,
            order_type=order_type,
            quantity_decimals=quantity_decimals,
        )
        return self.journal.prepare(
            plan,
            payload,
        )

    def submit_plan(
        self,
        plan: ExecutionPlan,
        *,
        category: str = "linear",
        order_type: str = "Market",
        quantity_decimals: int = 8,
    ) -> dict:
        self.compliance.allow_mode(Mode.TESTNET)
        row = self.prepare_plan(
            plan,
            category=category,
            order_type=order_type,
            quantity_decimals=quantity_decimals,
        )
        if row["status"] in {
            "acknowledged",
            "reconciled",
        }:
            return row
        try:
            claimed = self.journal.claim_for_submit(
                row["intent_id"]
            )
        except ExecutionReliabilityError as exc:
            raise TestnetError(str(exc)) from exc
        if claimed["status"] in {
            "acknowledged",
            "reconciled",
        }:
            return claimed

        try:
            ack = self.client.place_order(
                **claimed["payload"]
            )
        except Exception as exc:
            self.journal.mark_uncertain(
                claimed["intent_id"],
                error=(
                    f"{type(exc).__name__}: {exc}"
                ),
            )
            raise

        expected_link_id = str(
            claimed["payload"]["order_link_id"]
        )
        if (
            not ack.order_id
            or not ack.order_link_id
            or ack.order_link_id != expected_link_id
        ):
            error = (
                "broker_ack_identity_invalid:"
                f"order_id={ack.order_id}:"
                f"order_link_id={ack.order_link_id}:"
                f"expected={expected_link_id}"
            )
            self.journal.mark_uncertain(
                claimed["intent_id"],
                error=error,
            )
            raise TestnetError(error)

        return self.journal.mark_acknowledged(
            claimed["intent_id"],
            broker_order_id=ack.order_id,
            broker_order_link_id=ack.order_link_id,
            raw=ack.raw,
        )

    def reconcile_intent(
        self,
        intent_id: str,
    ) -> dict:
        row = self.journal.get(intent_id)
        payload = row["payload"]
        broker_order = self.client.find_order(
            category=str(payload["category"]),
            symbol=str(payload["symbol"]),
            order_link_id=str(
                payload["order_link_id"]
            ),
        )
        return self.journal.reconcile(
            intent_id,
            broker_order,
        ).to_dict()

    def recover(self) -> list[dict]:
        results = []
        for row in self.journal.recovery_candidates():
            results.append(
                self.reconcile_intent(
                    row["intent_id"]
                )
            )
        return results
