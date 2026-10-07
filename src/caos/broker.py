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

    def execute(self, order: OrderRequest) -> Fill:
        self.risk.validate(order)
        fee = order.notional * self.fee_bps / 10_000.0
        pos = self.positions.setdefault(order.symbol, Position(order.symbol))
        signed = order.notional if order.side == "buy" else -order.notional
        new_notional = pos.notional + signed
        if order.side == "buy" and order.notional + fee > self.cash:
            raise RuntimeError("insufficient_cash")
        if order.side == "buy":
            self.cash -= order.notional + fee
        else:
            self.cash += order.notional - fee
        if abs(new_notional) < 1e-9:
            pos.notional = 0.0
            pos.avg_price = 0.0
        else:
            if pos.notional == 0 or (pos.notional > 0) == (signed > 0):
                total_abs = abs(pos.notional) + abs(signed)
                pos.avg_price = (
                    (abs(pos.notional) * pos.avg_price)
                    + (abs(signed) * order.price)
                ) / total_abs
            pos.notional = new_notional
        fill = Fill(
            order.symbol,
            order.side,
            order.notional,
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
            if abs(pos.notional) < 1e-9:
                continue
            mark = marks.get(symbol, pos.avg_price)
            if pos.avg_price > 0:
                value += pos.notional * (mark / pos.avg_price)
        return value

    def snapshot(self) -> dict:
        return {
            "cash": round(self.cash, 8),
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "fills": [asdict(f) for f in self.fills],
        }
