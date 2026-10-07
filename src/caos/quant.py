from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, pstdev

from .domain import BacktestResult, Mandate, MarketBar, StrategySpec, Trade


def _sma(values: list[float], period: int, idx: int) -> float | None:
    if idx + 1 < period:
        return None
    window = values[idx + 1 - period : idx + 1]
    return sum(window) / period


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 1.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def backtest(
    spec: StrategySpec,
    bars: list[MarketBar],
    cost_bps: float = 8.0,
) -> BacktestResult:
    if len(bars) < spec.slow + 3:
        return BacktestResult(
            spec.name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, [1.0], []
        )

    closes = [b.close for b in bars]
    in_trade = False
    entry_price = 0.0
    entry_ts = 0
    trades: list[Trade] = []
    equity = [1.0]
    cost_pct = cost_bps / 100.0

    for i in range(spec.slow, len(bars)):
        fast = _sma(closes, spec.fast, i)
        slow = _sma(closes, spec.slow, i)
        prev_fast = _sma(closes, spec.fast, i - 1)
        prev_slow = _sma(closes, spec.slow, i - 1)
        if None in (fast, slow, prev_fast, prev_slow):
            continue
        price = closes[i]
        if not in_trade and prev_fast <= prev_slow and fast > slow:
            in_trade = True
            entry_price = price
            entry_ts = bars[i].ts
            continue
        if in_trade:
            move_pct = (price / entry_price - 1.0) * 100.0
            reason = None
            if move_pct <= -spec.stop_loss_pct:
                reason = "stop"
            elif move_pct >= spec.take_profit_pct:
                reason = "target"
            elif prev_fast >= prev_slow and fast < slow:
                reason = "cross"
            elif i == len(bars) - 1:
                reason = "end"
            if reason:
                pnl_pct = move_pct - cost_pct
                trades.append(
                    Trade(
                        entry_ts,
                        bars[i].ts,
                        "long",
                        entry_price,
                        price,
                        pnl_pct,
                        reason,
                    )
                )
                equity.append(equity[-1] * (1.0 + pnl_pct / 100.0))
                in_trade = False

    wins = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losses = [t.pnl_pct for t in trades if t.pnl_pct < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (
        gross_profit / gross_loss
        if gross_loss > 1e-12
        else (999.0 if gross_profit > 0 else 0.0)
    )
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    expectancy = mean([t.pnl_pct for t in trades]) if trades else 0.0
    pnl_pct = (equity[-1] - 1.0) * 100.0
    return BacktestResult(
        strategy=spec.name,
        trades=len(trades),
        pnl_pct=pnl_pct,
        win_rate_pct=win_rate,
        profit_factor=pf,
        max_drawdown_pct=_max_drawdown(equity),
        expectancy_pct=expectancy,
        equity_curve=equity,
        trade_log=trades,
    )


@dataclass(slots=True)
class RobustnessResult:
    passed: bool
    walk_forward_positive_ratio: float
    monte_carlo_p05_pct: float
    stressed_profit_factor: float
    reasons: list[str]


def walk_forward(
    spec: StrategySpec,
    bars: list[MarketBar],
    folds: int = 4,
    cost_bps: float = 8.0,
) -> float:
    if folds < 2:
        raise ValueError("folds must be >= 2")
    chunk = max(len(bars) // folds, spec.slow + 3)
    results: list[float] = []
    for start in range(0, len(bars), chunk):
        segment = bars[start : start + chunk]
        if len(segment) < spec.slow + 3:
            continue
        results.append(backtest(spec, segment, cost_bps).pnl_pct)
    if not results:
        return 0.0
    return sum(1 for r in results if r > 0) / len(results)


def monte_carlo_p05(
    trades: list[Trade],
    runs: int = 300,
    seed: int = 7,
) -> float:
    if not trades:
        return -100.0
    rng = random.Random(seed)
    outcomes: list[float] = []
    pnls = [t.pnl_pct for t in trades]
    for _ in range(runs):
        sampled = [rng.choice(pnls) for _ in pnls]
        equity = 1.0
        for pnl in sampled:
            equity *= 1.0 + pnl / 100.0
        outcomes.append((equity - 1.0) * 100.0)
    outcomes.sort()
    idx = max(0, min(len(outcomes) - 1, int(len(outcomes) * 0.05)))
    return outcomes[idx]


def robustness(
    spec: StrategySpec,
    bars: list[MarketBar],
    mandate: Mandate,
    cost_bps: float = 8.0,
) -> RobustnessResult:
    base = backtest(spec, bars, cost_bps)
    wf = walk_forward(spec, bars, folds=4, cost_bps=cost_bps)
    mc = monte_carlo_p05(base.trade_log)
    stressed = backtest(spec, bars, cost_bps=cost_bps * 2.0)
    reasons: list[str] = []
    if base.trades < 3:
        reasons.append("too_few_trades")
    if base.profit_factor < 1.05:
        reasons.append("profit_factor")
    if base.max_drawdown_pct > mandate.max_drawdown_pct:
        reasons.append("drawdown")
    if wf < 0.5:
        reasons.append("walk_forward")
    if stressed.profit_factor < 1.0:
        reasons.append("cost_stress")
    if mc < -mandate.max_drawdown_pct:
        reasons.append("monte_carlo_tail")
    return RobustnessResult(
        not reasons,
        wf,
        mc,
        stressed.profit_factor,
        reasons,
    )


def mine_strategies(
    bars: list[MarketBar],
    mandate: Mandate,
    cost_bps: float = 8.0,
) -> list[tuple[StrategySpec, BacktestResult, RobustnessResult]]:
    candidates: list[
        tuple[StrategySpec, BacktestResult, RobustnessResult]
    ] = []
    for fast in (3, 5, 8, 13):
        for slow in (21, 34, 55):
            if fast >= slow:
                continue
            spec = StrategySpec(
                f"ma_{fast}_{slow}",
                "trend",
                fast,
                slow,
            )
            bt = backtest(spec, bars, cost_bps)
            rb = robustness(spec, bars, mandate, cost_bps)
            if rb.passed:
                candidates.append((spec, bt, rb))
    candidates.sort(
        key=lambda item: (
            item[1].profit_factor,
            item[1].pnl_pct,
        ),
        reverse=True,
    )
    return candidates


def market_regime(bars: list[MarketBar]) -> dict[str, float | str]:
    if len(bars) < 20:
        return {
            "regime": "unknown",
            "trend_pct": 0.0,
            "volatility_pct": 0.0,
        }
    closes = [b.close for b in bars]
    trend = (closes[-1] / closes[-20] - 1.0) * 100.0
    returns = [
        (closes[i] / closes[i - 1] - 1.0) * 100.0
        for i in range(1, len(closes))
    ]
    vol = pstdev(returns[-20:]) if len(returns) >= 2 else 0.0
    regime = (
        "trend_up"
        if trend > vol * 2
        else "trend_down"
        if trend < -vol * 2
        else "range"
    )
    return {
        "regime": regime,
        "trend_pct": trend,
        "volatility_pct": vol,
    }


def current_signal(spec: StrategySpec, bars: list[MarketBar]) -> str:
    """Return long/flat from the latest completed bar using the same MA crossover family."""
    if len(bars) < spec.slow + 1:
        return "flat"
    closes = [b.close for b in bars]
    i = len(closes) - 1
    fast = _sma(closes, spec.fast, i)
    slow = _sma(closes, spec.slow, i)
    if fast is None or slow is None:
        return "flat"
    return "long" if fast > slow else "flat"
