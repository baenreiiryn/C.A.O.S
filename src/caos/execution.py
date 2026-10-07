from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ExecutionCost:
    side: str
    notional: float
    best_bid: float
    best_ask: float
    mid: float
    vwap: float
    spread_bps: float
    market_impact_bps: float
    fee_bps: float
    one_way_cost_bps: float
    roundtrip_cost_bps: float
    liquidity_sufficient: bool

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_execution_cost(
    bids: list[list[float] | tuple[float, float]],
    asks: list[list[float] | tuple[float, float]],
    side: str,
    notional: float,
    fee_bps: float = 5.0,
) -> ExecutionCost:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if notional <= 0:
        raise ValueError("notional must be positive")
    if not bids or not asks:
        raise ValueError("orderbook requires bids and asks")

    bid_levels = [(float(p), float(q)) for p, q in bids]
    ask_levels = [(float(p), float(q)) for p, q in asks]
    best_bid = bid_levels[0][0]
    best_ask = ask_levels[0][0]
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        raise ValueError("invalid orderbook")

    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000.0
    levels = ask_levels if side == "buy" else bid_levels

    remaining = notional
    total_quote = 0.0
    total_base = 0.0
    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        quote_capacity = price * qty
        take_quote = min(remaining, quote_capacity)
        total_quote += take_quote
        total_base += take_quote / price
        remaining -= take_quote
        if remaining <= 1e-9:
            break

    liquidity_sufficient = remaining <= max(1e-9, notional * 1e-9)
    if total_base <= 0:
        raise ValueError("no executable liquidity")
    vwap = total_quote / total_base

    if side == "buy":
        impact = max(0.0, (vwap / mid - 1.0) * 10_000.0)
    else:
        impact = max(0.0, (1.0 - vwap / mid) * 10_000.0)

    one_way = float(fee_bps) + impact
    return ExecutionCost(
        side=side,
        notional=float(notional),
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        vwap=vwap,
        spread_bps=spread_bps,
        market_impact_bps=impact,
        fee_bps=float(fee_bps),
        one_way_cost_bps=one_way,
        roundtrip_cost_bps=one_way * 2.0,
        liquidity_sufficient=liquidity_sufficient,
    )
