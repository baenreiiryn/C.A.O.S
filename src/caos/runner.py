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

    def cycle(self, portfolio: list[PortfolioEntry]) -> CycleResult:
        self.caos._require_mandate()
        actions: list[dict] = []
        skipped: list[dict] = []
        broker = self.caos.paper
        risk = self.caos.risk
        assert broker is not None and risk is not None
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
            signal = current_signal(entry.strategy, bars)
            pos = broker.positions.get(entry.symbol)
            open_notional = pos.notional if pos else 0.0
            price = bars[-1].close
            target = min(
                risk.max_position_notional,
                risk.state.current_equity * entry.weight,
            )
            if signal == "long" and open_notional <= 1e-9:
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "buy",
                        target,
                        price,
                        entry.strategy.name,
                    )
                )
                actions.append(
                    {
                        "action": "open_long",
                        "fill": self._fill_dict(fill),
                    }
                )
            elif signal == "flat" and open_notional > 1e-9:
                fill = broker.execute(
                    OrderRequest(
                        entry.symbol,
                        "sell",
                        open_notional,
                        price,
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
        return CycleResult(actions, skipped)
