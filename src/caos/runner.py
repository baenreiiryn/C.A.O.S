from __future__ import annotations

from dataclasses import dataclass

from .domain import OrderRequest
from .portfolio import PortfolioEntry
from .quant import current_signal


@dataclass(slots=True)
class CycleResult:
    actions: list[dict]
    skipped: list[dict]


class PaperRunner:
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

    def _execution_price(self, symbol: str, side: str, mid_price: float) -> float:
        roundtrip = float(self.caos.execution_costs.get(symbol, 0.0))
        broker_fee = float(getattr(self.caos.paper, "fee_bps", 0.0))
        one_way_total = roundtrip / 2.0
        modeled_non_fee_bps = max(0.0, one_way_total - broker_fee)
        if side == "buy":
            return mid_price * (1.0 + modeled_non_fee_bps / 10_000.0)
        return mid_price * (1.0 - modeled_non_fee_bps / 10_000.0)

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

            if risk.state.kill_switch:
                if open_qty > 1e-12:
                    exit_price = self._execution_price(
                        entry.symbol,
                        "sell",
                        price,
                    )
                    fill = broker.execute(
                        OrderRequest(
                            entry.symbol,
                            "sell",
                            open_qty * exit_price,
                            exit_price,
                            entry.strategy.name,
                        )
                    )
                    actions.append(
                        {
                            "action": "emergency_close",
                            "fill": self._fill_dict(fill),
                        }
                    )
                else:
                    skipped.append(
                        {
                            "symbol": entry.symbol,
                            "reason": "kill_switch_no_position",
                        }
                    )
                continue

            signal = current_signal(entry.strategy, bars)
            target = min(
                risk.max_position_notional,
                risk.state.current_equity * entry.weight,
            )

            if signal == "long" and open_qty <= 1e-12:
                entry_price = self._execution_price(
                    entry.symbol,
                    "buy",
                    price,
                )
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "buy",
                        target,
                        entry_price,
                        entry.strategy.name,
                    )
                )
                actions.append(
                    {
                        "action": "open_long",
                        "fill": self._fill_dict(fill),
                    }
                )

            elif signal == "flat" and open_qty > 1e-12:
                exit_price = self._execution_price(
                    entry.symbol,
                    "sell",
                    price,
                )
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "sell",
                        open_qty * exit_price,
                        exit_price,
                        entry.strategy.name,
                    )
                )
                actions.append(
                    {
                        "action": "close_long",
                        "fill": self._fill_dict(fill),
                    }
                )

            else:
                skipped.append(
                    {
                        "symbol": entry.symbol,
                        "reason": "no_state_change",
                        "signal": signal,
                    }
                )

        risk.set_equity(broker.equity(self._marks()))
        return CycleResult(actions, skipped)
