from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .compliance import ComplianceEngine
from .domain import Mode
from .execution_fabric import ExecutionPlan


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
