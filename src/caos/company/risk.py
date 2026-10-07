from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .domain import CompanyPolicy, TraderStatus
from .market import MarketAllocator
from .registry import TraderRegistry
from .treasury import Treasury


class CompanyRiskViolation(RuntimeError):
    pass


@dataclass(slots=True)
class CompanyRiskState:
    kill_switch: bool = False
    start_equity: float = 0.0


class CompanyRiskGovernor:
    """Company-level gate above the existing C.A.O.S per-order RiskEngine."""

    def __init__(
        self,
        policy: CompanyPolicy,
        treasury: Treasury,
        registry: TraderRegistry,
        market_allocator: MarketAllocator,
    ):
        self.policy = policy
        self.treasury = treasury
        self.registry = registry
        self.market_allocator = market_allocator
        self.state = CompanyRiskState(
            kill_switch=False,
            start_equity=treasury.company_equity,
        )
        self._trader_equity_provider: Callable[[str], float] | None = None
        self._company_equity_provider: Callable[[], float] | None = None

    def set_equity_providers(
        self,
        *,
        trader_equity: Callable[[str], float] | None = None,
        company_equity: Callable[[], float] | None = None,
    ) -> None:
        self._trader_equity_provider = trader_equity
        self._company_equity_provider = company_equity

    def trader_equity(self, trader_id: str) -> float:
        if self._trader_equity_provider is not None:
            return float(self._trader_equity_provider(trader_id))
        return self.treasury.balance(trader_id)

    def company_equity(self) -> float:
        if self._company_equity_provider is not None:
            return float(self._company_equity_provider())
        return self.treasury.company_equity

    def max_trade_notional(self, trader_id: str) -> float:
        return (
            self.trader_equity(trader_id)
            * self.policy.max_trade_exposure_pct
            / 100.0
        )

    def drawdown_pct(self) -> float:
        if self.state.start_equity <= 0:
            return 0.0
        return max(
            0.0,
            (
                self.state.start_equity - self.company_equity()
            )
            / self.state.start_equity
            * 100.0,
        )

    def validate(
        self,
        trader_id: str,
        *,
        symbol: str,
        notional: float,
        risk_reducing: bool = False,
    ) -> None:
        if notional <= 0:
            raise CompanyRiskViolation("invalid_notional")
        trader = self.registry.get(trader_id)
        if trader.status != TraderStatus.ACTIVE:
            raise CompanyRiskViolation("trader_not_active")
        assignment = self.market_allocator.assignments.get(trader_id)
        if assignment is None:
            raise CompanyRiskViolation("market_not_assigned")
        if assignment.symbol != symbol.upper():
            raise CompanyRiskViolation("market_assignment_mismatch")
        if risk_reducing:
            return
        if self.state.kill_switch:
            raise CompanyRiskViolation("company_kill_switch_active")
        if self.drawdown_pct() >= self.policy.company_max_drawdown_pct:
            raise CompanyRiskViolation("company_drawdown_limit")
        if notional > self.max_trade_notional(trader_id) + 1e-9:
            raise CompanyRiskViolation("trader_exposure_limit")

    def kill(self) -> None:
        self.state.kill_switch = True

    def reset_human_only(self, *, human_confirmation: bool) -> None:
        if not human_confirmation:
            raise CompanyRiskViolation("human_confirmation_required")
        self.state.kill_switch = False

    def snapshot(self) -> dict:
        return {
            "kill_switch": self.state.kill_switch,
            "start_equity": self.state.start_equity,
            "current_equity": self.company_equity(),
            "drawdown_pct": self.drawdown_pct(),
        }
