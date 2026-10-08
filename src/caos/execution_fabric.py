from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal


EXECUTION_FABRIC_VERSION = "execution-fabric/v1"

Signal = Literal["long", "flat"]
PositionSide = Literal["long", "flat"]
PlanAction = Literal["hold", "increase", "reduce", "close"]
OrderSide = Literal["buy", "sell"]


def _stable_id(prefix: str, payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"{prefix}-{digest}"


@dataclass(slots=True, frozen=True)
class StrategyDecision:
    symbol: str
    strategy_id: str
    signal: Signal
    requested_weight: float
    as_of: int | None = None
    reason: str = "strategy_signal"
    decision_id: str = ""

    def __post_init__(self) -> None:
        symbol = self.symbol.upper()
        if not symbol:
            raise ValueError("decision_symbol_required")
        if not self.strategy_id:
            raise ValueError("decision_strategy_required")
        if self.signal not in {"long", "flat"}:
            raise ValueError("unsupported_strategy_signal")
        if not 0.0 <= float(self.requested_weight) <= 1.0:
            raise ValueError("requested_weight_must_be_in_0_1")
        if self.signal == "flat" and abs(self.requested_weight) > 1e-12:
            raise ValueError("flat_decision_requires_zero_weight")
        object.__setattr__(self, "symbol", symbol)
        if not self.decision_id:
            object.__setattr__(
                self,
                "decision_id",
                _stable_id(
                    "decision",
                    {
                        "symbol": symbol,
                        "strategy_id": self.strategy_id,
                        "signal": self.signal,
                        "requested_weight": round(
                            float(self.requested_weight),
                            12,
                        ),
                        "as_of": self.as_of,
                        "reason": self.reason,
                    },
                ),
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TargetPosition:
    symbol: str
    strategy_id: str
    side: PositionSide
    target_weight: float
    target_notional: float
    decision_id: str

    def __post_init__(self) -> None:
        symbol = self.symbol.upper()
        if not symbol:
            raise ValueError("target_symbol_required")
        if self.side not in {"long", "flat"}:
            raise ValueError("unsupported_target_side")
        if not 0.0 <= float(self.target_weight) <= 1.0:
            raise ValueError("target_weight_must_be_in_0_1")
        if self.target_notional < -1e-12:
            raise ValueError("target_notional_cannot_be_negative")
        if self.side == "flat" and (
            abs(self.target_weight) > 1e-12
            or abs(self.target_notional) > 1e-9
        ):
            raise ValueError("flat_target_must_be_zero")
        object.__setattr__(self, "symbol", symbol)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    symbol: str
    strategy_id: str
    decision_id: str
    action: PlanAction
    side: OrderSide | None
    current_notional: float
    desired_target_notional: float
    effective_target_notional: float
    order_notional: float
    reference_price: float
    risk_reducing: bool
    allow_new_risk: bool
    plan_id: str = ""

    def __post_init__(self) -> None:
        symbol = self.symbol.upper()
        if not symbol:
            raise ValueError("plan_symbol_required")
        if self.action not in {"hold", "increase", "reduce", "close"}:
            raise ValueError("unsupported_plan_action")
        if self.side not in {None, "buy", "sell"}:
            raise ValueError("unsupported_plan_side")
        if self.reference_price <= 0:
            raise ValueError("reference_price_must_be_positive")
        for name in (
            "current_notional",
            "desired_target_notional",
            "effective_target_notional",
            "order_notional",
        ):
            if float(getattr(self, name)) < -1e-9:
                raise ValueError(f"{name}_cannot_be_negative")
        if self.action == "hold":
            if self.side is not None or self.order_notional > 1e-9:
                raise ValueError("hold_plan_cannot_have_order")
        else:
            if self.side is None or self.order_notional <= 0:
                raise ValueError("executable_plan_requires_order")
        if self.risk_reducing and self.side != "sell":
            raise ValueError("risk_reducing_plan_must_sell")
        object.__setattr__(self, "symbol", symbol)
        if not self.plan_id:
            object.__setattr__(
                self,
                "plan_id",
                _stable_id(
                    "plan",
                    {
                        "symbol": symbol,
                        "strategy_id": self.strategy_id,
                        "decision_id": self.decision_id,
                        "action": self.action,
                        "side": self.side,
                        "current_notional": round(
                            float(self.current_notional),
                            8,
                        ),
                        "desired_target_notional": round(
                            float(self.desired_target_notional),
                            8,
                        ),
                        "effective_target_notional": round(
                            float(self.effective_target_notional),
                            8,
                        ),
                        "reference_price": round(
                            float(self.reference_price),
                            8,
                        ),
                        "allow_new_risk": bool(self.allow_new_risk),
                    },
                ),
            )

    @property
    def executable(self) -> bool:
        return self.action != "hold"

    def to_dict(self) -> dict:
        out = asdict(self)
        out["executable"] = self.executable
        return out


def decision_from_signal(
    *,
    symbol: str,
    strategy_id: str,
    signal: Signal,
    requested_weight: float,
    as_of: int | None = None,
    reason: str = "strategy_signal",
) -> StrategyDecision:
    weight = float(requested_weight) if signal == "long" else 0.0
    return StrategyDecision(
        symbol=symbol,
        strategy_id=strategy_id,
        signal=signal,
        requested_weight=weight,
        as_of=as_of,
        reason=reason,
    )


def resolve_target_position(
    decision: StrategyDecision,
    *,
    equity: float,
    max_notional: float,
) -> TargetPosition:
    if equity < 0:
        raise ValueError("equity_cannot_be_negative")
    if max_notional < 0:
        raise ValueError("max_notional_cannot_be_negative")
    if decision.signal == "flat":
        return TargetPosition(
            symbol=decision.symbol,
            strategy_id=decision.strategy_id,
            side="flat",
            target_weight=0.0,
            target_notional=0.0,
            decision_id=decision.decision_id,
        )
    desired = float(equity) * float(decision.requested_weight)
    target = min(desired, float(max_notional))
    actual_weight = target / equity if equity > 1e-12 else 0.0
    return TargetPosition(
        symbol=decision.symbol,
        strategy_id=decision.strategy_id,
        side="long" if target > 1e-12 else "flat",
        target_weight=actual_weight,
        target_notional=max(0.0, target),
        decision_id=decision.decision_id,
    )


def plan_execution(
    target: TargetPosition,
    *,
    current_notional: float,
    reference_price: float,
    allow_new_risk: bool = True,
    tolerance: float = 1e-8,
) -> ExecutionPlan:
    current = max(0.0, float(current_notional))
    desired = max(0.0, float(target.target_notional))
    effective = desired
    if not allow_new_risk and desired > current:
        effective = current

    delta = effective - current
    scale = max(1.0, current, effective)
    epsilon = max(float(tolerance), scale * 1e-9)

    if abs(delta) <= epsilon:
        action: PlanAction = "hold"
        side: OrderSide | None = None
        order_notional = 0.0
        risk_reducing = False
    elif delta > 0:
        action = "increase"
        side = "buy"
        order_notional = delta
        risk_reducing = False
    else:
        action = "close" if effective <= epsilon else "reduce"
        side = "sell"
        order_notional = abs(delta)
        risk_reducing = True

    return ExecutionPlan(
        symbol=target.symbol,
        strategy_id=target.strategy_id,
        decision_id=target.decision_id,
        action=action,
        side=side,
        current_notional=current,
        desired_target_notional=desired,
        effective_target_notional=effective,
        order_notional=order_notional,
        reference_price=float(reference_price),
        risk_reducing=risk_reducing,
        allow_new_risk=bool(allow_new_risk),
    )
