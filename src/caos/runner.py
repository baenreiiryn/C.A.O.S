from __future__ import annotations

from dataclasses import dataclass

from .domain import OrderRequest
from .execution_fabric import (
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)
from .portfolio import PortfolioEntry
from .quant import current_decision


@dataclass(slots=True)
class CycleResult:
    actions: list[dict]
    skipped: list[dict]


class PaperRunner:
    """C.A.O.S paper runner backed by the shared Execution Fabric."""

    def __init__(self, caos):
        self.caos = caos

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
        roundtrip = float(self.caos.execution_costs.get(symbol, 0.0))
        broker_fee = float(getattr(self.caos.paper, "fee_bps", 0.0))
        one_way_total = roundtrip / 2.0
        modeled_non_fee_bps = max(0.0, one_way_total - broker_fee)
        if side == "buy":
            return mid_price * (
                1.0 + modeled_non_fee_bps / 10_000.0
            )
        return mid_price * (
            1.0 - modeled_non_fee_bps / 10_000.0
        )

    def _marks(self) -> dict[str, float]:
        return {
            symbol: bars[-1].close
            for symbol, bars in self.caos.market_data.items()
            if bars
        }

    def cycle(self, portfolio: list[PortfolioEntry]) -> CycleResult:
        self.caos._require_mandate()
        actions: list[dict] = []
        skipped: list[dict] = []
        broker = self.caos.paper
        risk = self.caos.risk
        assert broker is not None and risk is not None

        risk.set_equity(broker.equity(self._marks()))

        for entry in portfolio:
            bars = self.caos.market_data.get(entry.symbol)
            if not bars:
                skipped.append(
                    {
                        "symbol": entry.symbol,
                        "reason": "market_data_required",
                    }
                )
                continue

            pos = broker.positions.get(entry.symbol)
            open_qty = pos.quantity if pos else 0.0
            price = bars[-1].close
            current_notional = open_qty * price

            decision = current_decision(
                entry.strategy,
                bars,
                symbol=entry.symbol,
                requested_weight=float(entry.weight),
            )
            if risk.state.kill_switch:
                decision = decision_from_signal(
                    symbol=entry.symbol,
                    strategy_id=entry.strategy.name,
                    signal="flat",
                    requested_weight=0.0,
                    as_of=bars[-1].ts,
                    reason="caos_kill_switch",
                )

            target = resolve_target_position(
                decision,
                equity=risk.state.current_equity,
                max_notional=risk.max_position_notional,
            )
            plan = plan_execution(
                target,
                current_notional=current_notional,
                reference_price=price,
                allow_new_risk=not risk.state.kill_switch,
                tolerance=max(
                    1e-8,
                    target.target_notional * 0.01,
                ),
            )

            if not plan.executable:
                skipped.append(
                    {
                        "symbol": entry.symbol,
                        "reason": (
                            "kill_switch_no_position"
                            if risk.state.kill_switch
                            else "no_state_change"
                        ),
                        "signal": decision.signal,
                        "decision": decision.to_dict(),
                        "target": target.to_dict(),
                        "plan": plan.to_dict(),
                    }
                )
                continue

            if plan.side == "buy":
                # Validate the final aggregate target, not only the delta order.
                risk.validate(
                    OrderRequest(
                        entry.symbol,
                        "buy",
                        plan.effective_target_notional,
                        price,
                        entry.strategy.name,
                    )
                )
                execution_price = self._execution_price(
                    entry.symbol,
                    "buy",
                    price,
                )
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "buy",
                        plan.order_notional,
                        execution_price,
                        entry.strategy.name,
                    )
                )
                action = (
                    "open_long"
                    if current_notional <= 1e-8
                    else "increase_long"
                )
            else:
                execution_price = self._execution_price(
                    entry.symbol,
                    "sell",
                    price,
                )
                quantity_to_sell = plan.order_notional / price
                execution_notional = quantity_to_sell * execution_price
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "sell",
                        execution_notional,
                        execution_price,
                        entry.strategy.name,
                    )
                )
                if risk.state.kill_switch:
                    action = "emergency_close"
                else:
                    action = (
                        "close_long"
                        if plan.action == "close"
                        else "reduce_long"
                    )

            actions.append(
                {
                    "action": action,
                    "fill": self._fill_dict(fill),
                    "decision": decision.to_dict(),
                    "target": target.to_dict(),
                    "plan": plan.to_dict(),
                }
            )

        risk.set_equity(broker.equity(self._marks()))
        return CycleResult(actions, skipped)
