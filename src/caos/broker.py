from __future__ import annotations

from dataclasses import asdict

from .domain import Fill, OrderRequest, Position
from .risk import RiskEngine


class PaperBroker:
    def __init__(self, risk: RiskEngine, fee_bps: float = 5.0):
        self.risk = risk
        self.cash = risk.mandate.capital
        self.fee_bps = fee_bps
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.realized_trades: list[dict] = []

    def execute(self, order: OrderRequest) -> Fill:
        pos = self.positions.setdefault(order.symbol, Position(order.symbol))
        risk_reducing = order.side == "sell" and pos.quantity > 1e-12
        self.risk.validate(order, risk_reducing=risk_reducing)

        if order.side == "buy":
            fee = order.notional * self.fee_bps / 10_000.0
            if order.notional + fee > self.cash + 1e-9:
                raise RuntimeError("insufficient_cash")
            qty = order.notional / order.price
            old_qty = pos.quantity
            total_qty = old_qty + qty
            if total_qty <= 0:
                raise RuntimeError("invalid_quantity")
            pos.avg_price = (
                old_qty * pos.avg_price + qty * order.price
            ) / total_qty
            pos.quantity = total_qty
            pos.notional = pos.quantity * pos.avg_price
            pos.fees_paid += fee
            pos.strategy = order.strategy or pos.strategy
            self.cash -= order.notional + fee
            fill_notional = order.notional

        else:
            if pos.quantity <= 1e-12:
                raise RuntimeError("shorting_not_supported")
            requested_qty = order.notional / order.price
            if requested_qty > pos.quantity * (1.0 + 1e-9):
                raise RuntimeError("sell_exceeds_position")
            qty = min(requested_qty, pos.quantity)
            proceeds = qty * order.price
            fill_notional = proceeds
            fee = proceeds * self.fee_bps / 10_000.0

            old_qty = pos.quantity
            cost_basis = qty * pos.avg_price
            entry_fee_alloc = (
                pos.fees_paid * (qty / old_qty)
                if old_qty > 0
                else 0.0
            )
            realized = proceeds - cost_basis - fee - entry_fee_alloc
            denom = cost_basis + entry_fee_alloc
            pnl_pct = realized / denom * 100.0 if denom > 1e-12 else 0.0

            pos.quantity -= qty
            pos.fees_paid = max(0.0, pos.fees_paid - entry_fee_alloc)
            pos.realized_pnl += realized
            self.cash += proceeds - fee

            if pos.quantity <= 1e-10:
                pos.quantity = 0.0
                pos.notional = 0.0
                pos.avg_price = 0.0
                pos.fees_paid = 0.0
                strategy = pos.strategy or order.strategy
                pos.strategy = ""
                self.realized_trades.append(
                    {
                        "symbol": order.symbol,
                        "strategy": strategy,
                        "pnl": realized,
                        "pnl_pct": pnl_pct,
                        "exit_price": order.price,
                    }
                )
            else:
                pos.notional = pos.quantity * pos.avg_price

        fill = Fill(
            order.symbol,
            order.side,
            fill_notional,
            order.price,
            fee,
            order.strategy,
        )
        self.fills.append(fill)
        self.risk.set_equity(self.equity({order.symbol: order.price}))
        return fill

    def equity(self, marks: dict[str, float]) -> float:
        value = self.cash
        for symbol, pos in self.positions.items():
            if pos.quantity <= 1e-12:
                continue
            mark = marks.get(symbol, pos.avg_price)
            value += pos.quantity * mark
        return value

    def snapshot(self) -> dict:
        marks = {
            symbol: pos.avg_price
            for symbol, pos in self.positions.items()
        }
        return {
            "cash": round(self.cash, 8),
            "equity_cost_basis": round(self.equity(marks), 8),
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "fills": [asdict(f) for f in self.fills],
            "realized_trades": list(self.realized_trades),
        }
