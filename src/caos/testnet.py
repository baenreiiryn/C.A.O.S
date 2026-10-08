from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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


def execution_plan_to_binance_order(
    plan: ExecutionPlan,
    *,
    order_type: str = "MARKET",
    quantity_decimals: int = 8,
) -> dict[str, Any]:
    """Translate a venue-agnostic plan into a Binance Spot TESTNET order.

    Spot does not support opening a naked short. SELL is therefore accepted
    only for an ExecutionPlan that is explicitly risk-reducing.
    """
    if not plan.executable or plan.side is None:
        raise TestnetError("execution_plan_not_executable")
    order_type = str(order_type).upper()
    if order_type not in {"MARKET", "LIMIT"}:
        raise ValueError("order_type must be MARKET or LIMIT")
    if quantity_decimals < 0 or quantity_decimals > 16:
        raise ValueError("invalid_quantity_decimals")
    if plan.side == "sell" and not plan.risk_reducing:
        raise TestnetError("binance_spot_shorting_not_supported")

    qty = plan.order_notional / plan.reference_price
    if qty <= 0:
        raise TestnetError("execution_plan_quantity_invalid")
    qty_text = (
        f"{qty:.{quantity_decimals}f}"
        .rstrip("0")
        .rstrip(".")
    )
    if not qty_text:
        raise TestnetError(
            "execution_plan_quantity_rounds_to_zero"
        )

    payload: dict[str, Any] = {
        "symbol": plan.symbol.upper(),
        "side": "BUY" if plan.side == "buy" else "SELL",
        "order_type": order_type,
        "qty": qty_text,
        "order_link_id": plan.plan_id[:36],
    }
    if order_type == "LIMIT":
        payload["price"] = str(plan.reference_price)
    return payload


class BinanceSpotClient:
    """Minimal Binance Spot client for Japan-compatible integration.

    - spot-testnet: signed orders are allowed, still human-gated by C.A.O.S.
    - production-readonly: account/order metadata can be queried but order
      submission is blocked in code.

    Production REST uses the standard Binance Spot API documented for
    Binance Japan API users. Money-moving production execution remains
    unavailable.
    """

    TESTNET_BASE_URL = "https://testnet.binance.vision"
    PRODUCTION_BASE_URL = "https://api.binance.com"
    ENVIRONMENTS = {
        "spot-testnet": TESTNET_BASE_URL,
        "production-readonly": PRODUCTION_BASE_URL,
    }

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        environment: str = "spot-testnet",
        recv_window: int = 5000,
        base_url: str | None = None,
        time_ms: Callable[[], int] | None = None,
        transport: Callable[
            [str, str, bytes | None, dict[str, str]],
            dict,
        ]
        | None = None,
    ):
        environment = str(environment).strip().lower()
        if environment not in self.ENVIRONMENTS:
            raise TestnetError(
                "unsupported_binance_environment"
            )
        expected = self.ENVIRONMENTS[environment]
        requested = (base_url or expected).rstrip("/")
        if requested != expected:
            raise TestnetError(
                "unknown_binance_host_forbidden"
            )
        if not api_key or not api_secret:
            raise TestnetError("binance_credentials_required")
        if recv_window <= 0:
            raise ValueError(
                "recv_window must be positive"
            )
        self.api_key = str(api_key)
        self._api_secret = str(api_secret)
        self.environment = environment
        self.recv_window = int(recv_window)
        self.base_url = expected
        self._time_ms = (
            time_ms
            or (lambda: int(time.time() * 1000))
        )
        self._transport = (
            transport or self._urllib_transport
        )

    @property
    def trading_enabled(self) -> bool:
        return self.environment == "spot-testnet"

    @staticmethod
    def _urllib_transport(
        method: str,
        url: str,
        data: bytes | None,
        headers: dict[str, str],
    ) -> dict:
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                req,
                timeout=15.0,
            ) as resp:
                return json.loads(
                    resp.read().decode("utf-8")
                )
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(
                    exc.read().decode("utf-8")
                )
            except Exception:
                raise TestnetError(
                    f"binance_http_error:{exc.code}"
                ) from exc
            raise TestnetError(
                "binance_api_error:"
                f"{payload.get('code')}:{payload.get('msg')}"
            ) from exc

    @staticmethod
    def _query_string(
        params: dict[str, Any],
    ) -> str:
        items = [
            (key, str(value))
            for key, value in sorted(params.items())
            if value is not None
        ]
        return urllib.parse.urlencode(items)

    def signature(self, query_string: str) -> str:
        return hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _signed_params(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        signed = {
            **params,
            "recvWindow": self.recv_window,
            "timestamp": self._time_ms(),
        }
        query = self._query_string(signed)
        signed["signature"] = self.signature(query)
        return signed

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = True,
    ):
        values = dict(params or {})
        if signed:
            values = self._signed_params(values)
        query = self._query_string(values)
        headers = {
            "Accept": "application/json",
            "User-Agent": "caos/0.7.2",
        }
        if signed:
            headers["X-MBX-APIKEY"] = self.api_key

        method = method.upper()
        url = self.base_url + path
        data = None
        if method == "GET":
            if query:
                url += "?" + query
        else:
            headers[
                "Content-Type"
            ] = "application/x-www-form-urlencoded"
            data = query.encode("utf-8")

        result = self._transport(
            method,
            url,
            data,
            headers,
        )
        if (
            isinstance(result, dict)
            and isinstance(result.get("code"), int)
            and int(result["code"]) < 0
        ):
            raise TestnetError(
                "binance_api_error:"
                f"{result.get('code')}:{result.get('msg')}"
            )
        return result

    def get_account_info(self) -> dict:
        row = self._request(
            "GET",
            "/api/v3/account",
            {},
            signed=True,
        )
        balances = []
        for item in row.get("balances", []) or []:
            try:
                free = Decimal(str(item.get("free", "0")))
                locked = Decimal(
                    str(item.get("locked", "0"))
                )
            except InvalidOperation:
                continue
            if free != 0 or locked != 0:
                balances.append(
                    {
                        "asset": str(
                            item.get("asset", "")
                        ),
                        "free": str(free),
                        "locked": str(locked),
                    }
                )
        return {
            "environment": self.environment,
            "can_trade": bool(
                row.get("canTrade", False)
            ),
            "can_withdraw": bool(
                row.get("canWithdraw", False)
            ),
            "can_deposit": bool(
                row.get("canDeposit", False)
            ),
            "account_type": str(
                row.get("accountType", "")
            ),
            "permissions": list(
                row.get("permissions", []) or []
            ),
            "balances_nonzero": balances,
            "uid": str(row.get("uid", "")),
        }

    def get_exchange_info(
        self,
        symbol: str | None = None,
    ) -> dict:
        params = (
            {"symbol": symbol.upper()}
            if symbol
            else {}
        )
        result = self._request(
            "GET",
            "/api/v3/exchangeInfo",
            params,
            signed=False,
        )
        return dict(result)

    @staticmethod
    def _normalize_order(
        row: dict[str, Any],
    ) -> dict:
        executed = Decimal(
            str(row.get("executedQty", "0") or "0")
        )
        quote = Decimal(
            str(
                row.get(
                    "cummulativeQuoteQty",
                    "0",
                )
                or "0"
            )
        )
        avg_price = (
            str(quote / executed)
            if executed > 0
            else str(row.get("price", ""))
        )
        return {
            "order_id": str(
                row.get("orderId", "")
            ),
            "order_link_id": str(
                row.get("clientOrderId", "")
            ),
            "symbol": str(
                row.get("symbol", "")
            ).upper(),
            "side": str(row.get("side", "")).upper(),
            "order_type": str(
                row.get("type", "")
            ).upper(),
            "qty": str(row.get("origQty", "")),
            "order_status": str(
                row.get("status", "")
            ),
            "cum_exec_qty": str(
                row.get("executedQty", "")
            ),
            "avg_price": avg_price,
            "raw": dict(row),
        }

    def find_order(
        self,
        *,
        symbol: str,
        order_link_id: str,
    ) -> dict | None:
        if not symbol or not order_link_id:
            raise ValueError(
                "symbol_and_order_link_id_required"
            )
        try:
            row = self._request(
                "GET",
                "/api/v3/order",
                {
                    "symbol": symbol.upper(),
                    "origClientOrderId": (
                        order_link_id
                    ),
                },
                signed=True,
            )
        except TestnetError as exc:
            # Binance -2013 means the order is not known.
            if "binance_api_error:-2013:" in str(exc):
                return None
            raise
        if not isinstance(row, dict):
            return None
        if (
            str(row.get("clientOrderId", ""))
            != str(order_link_id)
        ):
            return None
        return self._normalize_order(row)

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        qty: str,
        price: str | None = None,
        time_in_force: str = "GTC",
        order_link_id: str | None = None,
    ) -> TestnetOrderAck:
        if not self.trading_enabled:
            raise TestnetError(
                "binance_production_trading_forbidden"
            )
        side = str(side).upper()
        order_type = str(order_type).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError(
                "side must be BUY or SELL"
            )
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(
                "order_type must be MARKET or LIMIT"
            )
        if not symbol or not qty:
            raise ValueError(
                "symbol and qty are required"
            )
        if order_type == "LIMIT" and price is None:
            raise ValueError("limit price required")

        payload: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
            "quantity": str(qty),
        }
        if order_link_id:
            payload["newClientOrderId"] = str(
                order_link_id
            )[:36]
        if order_type == "LIMIT":
            payload["timeInForce"] = time_in_force
            payload["price"] = str(price)

        result = self._request(
            "POST",
            "/api/v3/order",
            payload,
            signed=True,
        )
        return TestnetOrderAck(
            order_id=str(
                result.get("orderId", "")
            ),
            order_link_id=str(
                result.get("clientOrderId", "")
            ),
            raw=dict(result),
        )


class HumanTestnetExecutor:
    """Human-gated Binance Spot TESTNET surface.

    This class is intentionally not registered as an LLM tool.
    """

    def __init__(
        self,
        compliance: ComplianceEngine,
        client: BinanceSpotClient,
    ):
        self.compliance = compliance
        self.client = client

    def place_order(
        self,
        **kwargs,
    ) -> TestnetOrderAck:
        self.compliance.allow_mode(Mode.TESTNET)
        return self.client.place_order(**kwargs)

    def execute_plan(
        self,
        plan: ExecutionPlan,
        *,
        order_type: str = "MARKET",
        quantity_decimals: int = 8,
    ) -> TestnetOrderAck:
        self.compliance.allow_mode(Mode.TESTNET)
        payload = execution_plan_to_binance_order(
            plan,
            order_type=order_type,
            quantity_decimals=quantity_decimals,
        )
        return self.client.place_order(**payload)


class ReliableHumanTestnetExecutor:
    """Durable, human-gated Binance Spot TESTNET execution.

    Ambiguous submissions are never automatically resent. Recovery queries
    the order by the deterministic ExecutionPlan client order ID.
    """

    def __init__(
        self,
        compliance: ComplianceEngine,
        client: BinanceSpotClient,
        journal: DurableExecutionJournal,
    ):
        if client.environment != "spot-testnet":
            raise TestnetError(
                "reliable_executor_requires_spot_testnet"
            )
        if (
            journal.venue != "binance"
            or journal.environment
            != "spot-testnet"
        ):
            raise TestnetError(
                "journal_scope_must_match_binance_spot_testnet"
            )
        self.compliance = compliance
        self.client = client
        self.journal = journal

    def prepare_plan(
        self,
        plan: ExecutionPlan,
        *,
        order_type: str = "MARKET",
        quantity_decimals: int = 8,
    ) -> dict:
        payload = execution_plan_to_binance_order(
            plan,
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
        order_type: str = "MARKET",
        quantity_decimals: int = 8,
    ) -> dict:
        self.compliance.allow_mode(Mode.TESTNET)
        row = self.prepare_plan(
            plan,
            order_type=order_type,
            quantity_decimals=quantity_decimals,
        )
        if row["status"] in {
            "acknowledged",
            "reconciled",
        }:
            return row
        try:
            claimed = (
                self.journal.claim_for_submit(
                    row["intent_id"]
                )
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
            or ack.order_link_id
            != expected_link_id
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
        return [
            self.reconcile_intent(
                row["intent_id"]
            )
            for row in (
                self.journal.recovery_candidates()
            )
        ]
