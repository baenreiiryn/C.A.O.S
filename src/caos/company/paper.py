from __future__ import annotations

from dataclasses import dataclass

from ..broker import PaperBroker
from ..domain import Mandate, OrderRequest
from ..execution_fabric import (
    ExecutionPlan,
    StrategyDecision,
    TargetPosition,
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from ..risk import RiskEngine
from .adapter import CAOSAdapter
from .domain import CompanyPolicy, TraderStatus
from .market import MarketAllocator
from .registry import TraderRegistry
from .risk import CompanyRiskGovernor
from .strategy import CompanyStrategyRegistry
from .treasury import Treasury


class CompanyPaperError(RuntimeError):
    pass


@dataclass(slots=True)
class TraderPaperCycle:
    trader_id: str
    action: str
    signal: str | None
    fill: dict | None
    equity: float
    realized_equity: float
    decision: dict | None = None
    target: dict | None = None
    plan: dict | None = None

    def to_dict(self) -> dict:
        return {
            "trader_id": self.trader_id,
            "action": self.action,
            "signal": self.signal,
            "fill": self.fill,
            "equity": self.equity,
            "realized_equity": self.realized_equity,
            "decision": self.decision,
            "target": self.target,
            "plan": self.plan,
        }


class CompanyPaperBook:
    """Independent paper subaccounts for Company Traders.

    Each account uses the existing deterministic C.A.O.S PaperBroker/RiskEngine.
    Treasury remains the Company capital ledger; broker cost-basis equity is
    reconciled into the corresponding Treasury bucket after each fill.
    """

    def __init__(
        self,
        engine: CAOSAdapter,
        policy: CompanyPolicy,
        treasury: Treasury,
        registry: TraderRegistry,
        market: MarketAllocator,
        company_risk: CompanyRiskGovernor,
        strategies: CompanyStrategyRegistry,
        *,
        fee_bps: float = 5.0,
    ):
        self.engine = engine
        self.policy = policy
        self.treasury = treasury
        self.registry = registry
        self.market = market
        self.company_risk = company_risk
        self.strategies = strategies
        self.fee_bps = float(fee_bps)
        self.accounts: dict[str, PaperBroker] = {}
        self.last_plans: dict[str, dict] = {}

    def ensure_account(self, trader_id: str) -> PaperBroker:
        trader = self.registry.get(trader_id)
        if trader.status == TraderStatus.RETIRED:
            raise CompanyPaperError("retired_trader")
        account = self.accounts.get(trader_id)
        if account is not None:
            return account
        capital = self.treasury.balance(trader_id)
        if capital <= 0:
            raise CompanyPaperError("trader_has_no_allocated_capital")
        mandate = Mandate(
            capital=capital,
            max_drawdown_pct=self.policy.company_max_drawdown_pct,
            max_position_pct=trader.max_trade_exposure_pct,
        )
        account = PaperBroker(RiskEngine(mandate), fee_bps=self.fee_bps)
        self.accounts[trader_id] = account
        return account

    def has_open_position(self, trader_id: str) -> bool:
        account = self.accounts.get(trader_id)
        if account is None:
            return False
        return any(
            position.quantity > 1e-12
            for position in account.positions.values()
        )

    def positions_flat(self, trader_id: str) -> bool:
        return not self.has_open_position(trader_id)

    def _marks(self, trader_id: str) -> dict[str, float]:
        trader = self.registry.get(trader_id)
        if not trader.market:
            return {}
        bars = self.engine.bars(trader.market)
        if not bars:
            return {}
        return {trader.market: bars[-1].close}

    def marked_equity(self, trader_id: str) -> float:
        account = self.accounts.get(trader_id)
        if account is None:
            return self.treasury.balance(trader_id)
        return account.equity(self._marks(trader_id))

    def realized_equity(self, trader_id: str) -> float:
        account = self.accounts.get(trader_id)
        if account is None:
            return self.treasury.balance(trader_id)
        marks = {
            symbol: position.avg_price
            for symbol, position in account.positions.items()
            if position.quantity > 1e-12
        }
        return account.equity(marks)

    def reconcile_trader(self, trader_id: str) -> dict:
        if trader_id not in self.accounts:
            return {
                "trader_id": trader_id,
                "delta": 0.0,
                "treasury_equity": self.treasury.balance(trader_id),
                "paper_realized_equity": self.treasury.balance(trader_id),
            }
        target = self.realized_equity(trader_id)
        current = self.treasury.balance(trader_id)
        delta = target - current
        if abs(delta) > 1e-9:
            self.treasury.reconcile_balance(
                trader_id,
                target,
                note="paper_account_reconciliation",
            )
        return {
            "trader_id": trader_id,
            "delta": delta,
            "treasury_equity": self.treasury.balance(trader_id),
            "paper_realized_equity": target,
        }

    def audit_reconciliation(self) -> list[dict]:
        rows = []
        for trader_id in sorted(self.accounts):
            target = self.realized_equity(trader_id)
            current = self.treasury.balance(trader_id)
            delta = target - current
            if abs(delta) > 1e-8:
                rows.append(
                    {
                        "trader_id": trader_id,
                        "treasury_equity": current,
                        "paper_realized_equity": target,
                        "delta": delta,
                    }
                )
        return rows

    def exposure(self) -> dict:
        gross = 0.0
        by_trader: dict[str, float] = {}
        by_symbol: dict[str, float] = {}
        for trader_id, account in self.accounts.items():
            trader_total = 0.0
            for symbol, position in account.positions.items():
                if position.quantity <= 1e-12:
                    continue
                bars = self.engine.bars(symbol)
                mark = bars[-1].close if bars else position.avg_price
                notional = position.quantity * mark
                trader_total += notional
                by_symbol[symbol] = by_symbol.get(symbol, 0.0) + notional
            if trader_total > 0:
                by_trader[trader_id] = trader_total
                gross += trader_total
        return {
            "gross_notional": gross,
            "by_trader": by_trader,
            "by_symbol": by_symbol,
        }

    @staticmethod
    def _fill_dict(fill) -> dict:
        return {
            "symbol": fill.symbol,
            "side": fill.side,
            "notional": fill.notional,
            "price": fill.price,
            "fee": fill.fee,
            "strategy": fill.strategy,
        }

    def _execution_price(
        self,
        symbol: str,
        side: str,
        mid_price: float,
    ) -> float:
        roundtrip = self.engine.execution_cost_bps(symbol)
        one_way_total = roundtrip / 2.0
        modeled_non_fee_bps = max(0.0, one_way_total - self.fee_bps)
        if side == "buy":
            return mid_price * (1.0 + modeled_non_fee_bps / 10_000.0)
        return mid_price * (1.0 - modeled_non_fee_bps / 10_000.0)

    def cycle_trader(
        self,
        trader_id: str,
        *,
        allow_new_risk: bool = True,
    ) -> TraderPaperCycle:
        trader = self.registry.get(trader_id)
        if trader.status != TraderStatus.ACTIVE:
            raise CompanyPaperError("trader_not_active")
        if not trader.market:
            raise CompanyPaperError("market_not_assigned")
        if not trader.strategy_id:
            raise CompanyPaperError("strategy_not_assigned")
        if trader.direction == "short":
            raise CompanyPaperError("short_execution_not_supported_yet")

        bars = self.engine.bars(trader.market)
        if not bars:
            raise CompanyPaperError("market_data_required")
        strategy = self.strategies.get(trader.strategy_id)
        requested_weight = (
            trader.requested_trade_exposure_pct() / 100.0
        )
        decision = self.engine.current_decision(
            strategy,
            trader.market,
            requested_weight=requested_weight,
        )
        if self.company_risk.state.kill_switch:
            decision = decision_from_signal(
                symbol=trader.market,
                strategy_id=trader.strategy_id,
                signal="flat",
                requested_weight=0.0,
                as_of=bars[-1].ts,
                reason="company_kill_switch",
            )

        account = self.ensure_account(trader_id)
        marks = {trader.market: bars[-1].close}
        marked_equity = account.equity(marks)
        account.risk.set_equity(marked_equity)

        position = account.positions.get(trader.market)
        open_qty = position.quantity if position else 0.0
        price = bars[-1].close
        current_notional = open_qty * price

        max_notional = min(
            self.company_risk.max_trade_notional(trader_id),
            account.risk.max_position_notional,
        )
        target = resolve_target_position(
            decision,
            equity=marked_equity,
            max_notional=max_notional,
        )
        tolerance = max(
            1e-8,
            target.target_notional * 0.01,
        )
        plan = plan_execution(
            target,
            current_notional=current_notional,
            reference_price=price,
            allow_new_risk=allow_new_risk,
            tolerance=tolerance,
        )
        self.last_plans[trader_id] = plan.to_dict()

        if not plan.executable:
            return TraderPaperCycle(
                trader_id,
                "no_state_change",
                decision.signal,
                None,
                self.marked_equity(trader_id),
                self.realized_equity(trader_id),
                decision.to_dict(),
                target.to_dict(),
                plan.to_dict(),
            )

        if plan.side == "buy":
            if plan.effective_target_notional > max_notional + 1e-9:
                raise CompanyPaperError(
                    "execution_plan_exceeds_target_ceiling"
                )
            self.company_risk.validate(
                trader_id,
                symbol=trader.market,
                notional=plan.effective_target_notional,
            )
            entry_price = self._execution_price(
                trader.market,
                "buy",
                price,
            )
            fill = account.execute(
                OrderRequest(
                    trader.market,
                    "buy",
                    plan.order_notional,
                    entry_price,
                    trader.strategy_id,
                )
            )
            action = (
                "open_long"
                if current_notional <= 1e-8
                else "increase_long"
            )
        else:
            self.company_risk.validate(
                trader_id,
                symbol=trader.market,
                notional=plan.order_notional,
                risk_reducing=True,
            )
            exit_price = self._execution_price(
                trader.market,
                "sell",
                price,
            )
            quantity_to_sell = plan.order_notional / price
            execution_notional = quantity_to_sell * exit_price
            fill = account.execute(
                OrderRequest(
                    trader.market,
                    "sell",
                    execution_notional,
                    exit_price,
                    trader.strategy_id,
                )
            )
            action = (
                "close_long"
                if plan.action == "close"
                else "reduce_long"
            )

        self.reconcile_trader(trader_id)
        return TraderPaperCycle(
            trader_id,
            action,
            decision.signal,
            self._fill_dict(fill),
            self.marked_equity(trader_id),
            self.realized_equity(trader_id),
            decision.to_dict(),
            target.to_dict(),
            plan.to_dict(),
        )

    def force_flatten(self, trader_id: str) -> TraderPaperCycle:
        trader = self.registry.get(trader_id)
        account = self.accounts.get(trader_id)
        if account is None or not trader.market:
            return TraderPaperCycle(
                trader_id,
                "already_flat",
                None,
                None,
                self.marked_equity(trader_id),
                self.realized_equity(trader_id),
            )
        position = account.positions.get(trader.market)
        if position is None or position.quantity <= 1e-12:
            return TraderPaperCycle(
                trader_id,
                "already_flat",
                None,
                None,
                self.marked_equity(trader_id),
                self.realized_equity(trader_id),
            )
        bars = self.engine.bars(trader.market)
        if not bars:
            raise CompanyPaperError("market_data_required_to_flatten")

        price = bars[-1].close
        current_notional = position.quantity * price
        decision = decision_from_signal(
            symbol=trader.market,
            strategy_id=trader.strategy_id or "company_flatten",
            signal="flat",
            requested_weight=0.0,
            as_of=bars[-1].ts,
            reason="company_force_flatten",
        )
        target = resolve_target_position(
            decision,
            equity=self.marked_equity(trader_id),
            max_notional=0.0,
        )
        plan = plan_execution(
            target,
            current_notional=current_notional,
            reference_price=price,
            allow_new_risk=False,
        )
        self.last_plans[trader_id] = plan.to_dict()

        exit_price = self._execution_price(
            trader.market,
            "sell",
            price,
        )
        quantity_to_sell = plan.order_notional / price
        execution_notional = quantity_to_sell * exit_price
        self.company_risk.validate(
            trader_id,
            symbol=trader.market,
            notional=execution_notional,
            risk_reducing=True,
        )
        fill = account.execute(
            OrderRequest(
                trader.market,
                "sell",
                execution_notional,
                exit_price,
                trader.strategy_id or "company_flatten",
            )
        )
        self.reconcile_trader(trader_id)
        return TraderPaperCycle(
            trader_id,
            "forced_flatten",
            "flat",
            self._fill_dict(fill),
            self.marked_equity(trader_id),
            self.realized_equity(trader_id),
            decision.to_dict(),
            target.to_dict(),
            plan.to_dict(),
        )

    def adjust_flat_cash(self, trader_id: str, delta: float) -> None:
        account = self.accounts.get(trader_id)
        if account is None:
            return
        if self.has_open_position(trader_id):
            raise CompanyPaperError("cannot_adjust_cash_with_open_position")
        nxt = account.cash + float(delta)
        if nxt < -1e-9:
            raise CompanyPaperError("paper_cash_cannot_be_negative")
        account.cash = max(0.0, nxt)
        account.risk.set_equity(account.cash)

    def withdraw_flat(self, trader_id: str, amount: float) -> None:
        if amount <= 0:
            raise CompanyPaperError("invalid_withdrawal")
        self.adjust_flat_cash(trader_id, -float(amount))

    def deposit_flat(self, trader_id: str, amount: float) -> None:
        if amount <= 0:
            raise CompanyPaperError("invalid_deposit")
        self.adjust_flat_cash(trader_id, float(amount))

    def remove_account_if_flat(self, trader_id: str) -> None:
        account = self.accounts.get(trader_id)
        if account is None:
            return
        if self.has_open_position(trader_id):
            raise CompanyPaperError("cannot_remove_open_account")
        del self.accounts[trader_id]

    def snapshot(self) -> dict:
        return {
            "fee_bps": self.fee_bps,
            "last_plans": dict(self.last_plans),
            "accounts": {
                trader_id: {
                    "paper": account.snapshot(),
                    "risk": {
                        "kill_switch": account.risk.state.kill_switch,
                        "day_start_equity": account.risk.state.day_start_equity,
                        "current_equity": account.risk.state.current_equity,
                    },
                }
                for trader_id, account in self.accounts.items()
            },
        }

    def restore(self, snapshot: dict) -> None:
        from ..domain import Fill, PendingOrder, Position

        self.fee_bps = float(snapshot.get("fee_bps", self.fee_bps))
        self.last_plans = dict(snapshot.get("last_plans", {}))
        self.accounts = {}
        for trader_id, row in snapshot.get("accounts", {}).items():
            trader = self.registry.get(trader_id)
            if trader.status == TraderStatus.RETIRED:
                continue
            capital = float(
                row.get("risk", {}).get(
                    "day_start_equity",
                    self.treasury.balance(trader_id),
                )
            )
            mandate = Mandate(
                capital=max(capital, 1e-9),
                max_drawdown_pct=self.policy.company_max_drawdown_pct,
                max_position_pct=trader.max_trade_exposure_pct,
            )
            broker = PaperBroker(RiskEngine(mandate), fee_bps=self.fee_bps)
            paper = row["paper"]
            broker.cash = float(paper.get("cash", broker.cash))
            broker.positions = {
                symbol: Position(**data)
                for symbol, data in paper.get("positions", {}).items()
            }
            broker.fills = [
                Fill(**data)
                for data in paper.get("fills", [])
            ]
            broker.realized_trades = list(
                paper.get("realized_trades", [])
            )
            broker.pending_orders = {
                order_id: PendingOrder(**data)
                for order_id, data in paper.get("pending_orders", {}).items()
            }
            risk = row.get("risk", {})
            broker.risk.state.kill_switch = bool(
                risk.get("kill_switch", False)
            )
            broker.risk.state.day_start_equity = float(
                risk.get("day_start_equity", capital)
            )
            broker.risk.state.current_equity = float(
                risk.get("current_equity", broker.cash)
            )
            self.accounts[trader_id] = broker
