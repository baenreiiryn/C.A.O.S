from __future__ import annotations

from dataclasses import dataclass

from .domain import Mandate, OrderRequest


class RiskViolation(RuntimeError):
    pass


@dataclass(slots=True)
class RiskState:
    kill_switch: bool = False
    day_start_equity: float = 0.0
    current_equity: float = 0.0


class RiskEngine:
    def __init__(self, mandate: Mandate):
        self.mandate = mandate
        self.state = RiskState(False, mandate.capital, mandate.capital)

    @property
    def max_position_notional(self) -> float:
        return self.state.current_equity * self.mandate.max_position_pct / 100.0

    def set_equity(self, equity: float) -> None:
        if equity < 0:
            raise ValueError("equity cannot be negative")
        self.state.current_equity = equity

    def validate(self, order: OrderRequest, *, risk_reducing: bool = False) -> None:
        if order.notional <= 0 or order.price <= 0:
            raise RiskViolation("invalid_order")
        if risk_reducing:
            return
        if self.state.kill_switch:
            raise RiskViolation("kill_switch_active")
        if order.notional > self.max_position_notional + 1e-9:
            raise RiskViolation("position_limit")
        if self.state.day_start_equity > 0:
            loss_pct = max(
                0.0,
                (self.state.day_start_equity - self.state.current_equity)
                / self.state.day_start_equity
                * 100.0,
            )
            if loss_pct >= self.mandate.max_drawdown_pct:
                raise RiskViolation("drawdown_limit")

    def kill(self) -> None:
        self.state.kill_switch = True

    def reset_kill_switch_human_only(self, *, human_confirmation: bool) -> None:
        if not human_confirmation:
            raise RiskViolation("human_confirmation_required")
        self.state.kill_switch = False
