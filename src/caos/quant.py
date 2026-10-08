from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean, pstdev

from .domain import BacktestResult, Mandate, MarketBar, StrategySpec, Trade
from .execution_fabric import (
    ExecutionPlan,
    StrategyDecision,
    TargetPosition,
    decision_from_signal,
    plan_execution,
    resolve_target_position,
)


def _sma(values: list[float], period: int, idx: int) -> float | None:
    if idx + 1 < period:
        return None
    window = values[idx + 1 - period : idx + 1]
    return sum(window) / period


def _zscore(values: list[float], period: int, idx: int) -> float | None:
    if idx + 1 < period:
        return None
    window = values[idx + 1 - period : idx + 1]
    mu = mean(window)
    sigma = pstdev(window)
    if sigma <= 1e-12:
        return 0.0
    return (values[idx] - mu) / sigma


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 1.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _entry_signal(spec: StrategySpec, closes: list[float], idx: int) -> bool:
    if idx <= 0:
        return False

    if spec.family == "trend":
        fast = _sma(closes, spec.fast, idx)
        slow = _sma(closes, spec.slow, idx)
        pfast = _sma(closes, spec.fast, idx - 1)
        pslow = _sma(closes, spec.slow, idx - 1)
        return (
            None not in (fast, slow, pfast, pslow)
            and pfast <= pslow
            and fast > slow
        )

    if spec.family == "mean_reversion":
        z = _zscore(closes, spec.slow, idx)
        return z is not None and z <= -spec.threshold

    if spec.family == "breakout":
        if idx < spec.slow:
            return False
        prior = closes[idx - spec.slow : idx]
        return bool(prior) and closes[idx] > max(prior)

    if spec.family == "momentum":
        if idx < spec.slow:
            return False
        base = closes[idx - spec.slow]
        if base <= 0:
            return False
        momentum_pct = (closes[idx] / base - 1.0) * 100.0
        return momentum_pct >= spec.threshold

    return False


def _exit_signal(spec: StrategySpec, closes: list[float], idx: int) -> bool:
    if idx <= 0:
        return False

    if spec.family == "trend":
        fast = _sma(closes, spec.fast, idx)
        slow = _sma(closes, spec.slow, idx)
        pfast = _sma(closes, spec.fast, idx - 1)
        pslow = _sma(closes, spec.slow, idx - 1)
        return (
            None not in (fast, slow, pfast, pslow)
            and pfast >= pslow
            and fast < slow
        )

    if spec.family == "mean_reversion":
        z = _zscore(closes, spec.slow, idx)
        return z is not None and z >= -0.15

    if spec.family == "breakout":
        exit_lookback = max(3, spec.fast)
        if idx < exit_lookback:
            return False
        prior = closes[idx - exit_lookback : idx]
        return bool(prior) and closes[idx] < min(prior)

    if spec.family == "momentum":
        if idx < spec.fast:
            return False
        base = closes[idx - spec.fast]
        if base <= 0:
            return False
        short_momentum = (closes[idx] / base - 1.0) * 100.0
        return short_momentum <= 0.0

    return False


def signal_state_series(spec: StrategySpec, bars: list[MarketBar]) -> list[int]:
    """Long/flat state per bar for correlation and diagnostics."""
    closes = [b.close for b in bars]
    state = 0
    out: list[int] = []
    for i in range(len(bars)):
        if state == 0 and _entry_signal(spec, closes, i):
            state = 1
        elif state == 1 and _exit_signal(spec, closes, i):
            state = 0
        out.append(state)
    return out


def strategy_return_series(
    spec: StrategySpec,
    bars: list[MarketBar],
    cost_bps: float = 8.0,
) -> list[float]:
    """Approximate bar-level strategy returns for cross-strategy correlation."""
    if len(bars) < 2:
        return []
    state = signal_state_series(spec, bars)
    cost_pct = cost_bps / 100.0
    returns: list[float] = [0.0]
    for i in range(1, len(bars)):
        raw = (
            (bars[i].close / bars[i - 1].close - 1.0) * 100.0
            if state[i - 1]
            else 0.0
        )
        turnover = abs(state[i] - state[i - 1])
        returns.append(raw - turnover * cost_pct / 2.0)
    return returns


def pearson_correlation(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    x = a[-n:]
    y = b[-n:]
    mx = mean(x)
    my = mean(y)
    dx = [v - mx for v in x]
    dy = [v - my for v in y]
    denom = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, sum(i * j for i, j in zip(dx, dy)) / denom))


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
    roundtrip_cost_pct = cost_bps / 100.0

    for i in range(spec.slow, len(bars)):
        price = closes[i]
        if not in_trade and _entry_signal(spec, closes, i):
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
            elif _exit_signal(spec, closes, i):
                reason = "signal"
            elif i == len(bars) - 1:
                reason = "end"

            if reason:
                pnl_pct = move_pct - roundtrip_cost_pct
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


def _candidate_specs() -> list[StrategySpec]:
    specs: list[StrategySpec] = []

    for fast in (3, 5, 8, 13):
        for slow in (21, 34, 55):
            if fast < slow:
                specs.append(
                    StrategySpec(
                        f"trend_ma_{fast}_{slow}",
                        "trend",
                        fast,
                        slow,
                    )
                )

    for lookback in (14, 20, 30):
        for z in (1.25, 1.75, 2.25):
            specs.append(
                StrategySpec(
                    f"meanrev_z{z}_{lookback}",
                    "mean_reversion",
                    max(3, lookback // 4),
                    lookback,
                    stop_loss_pct=2.5,
                    take_profit_pct=3.0,
                    threshold=z,
                )
            )

    for lookback in (20, 40, 60):
        specs.append(
            StrategySpec(
                f"breakout_{lookback}",
                "breakout",
                max(5, lookback // 4),
                lookback,
                stop_loss_pct=2.5,
                take_profit_pct=5.0,
                threshold=0.0,
            )
        )

    for lookback in (12, 24, 48):
        for threshold in (0.5, 1.0, 2.0):
            specs.append(
                StrategySpec(
                    f"momentum_{lookback}_{threshold}",
                    "momentum",
                    max(3, lookback // 3),
                    lookback,
                    stop_loss_pct=2.0,
                    take_profit_pct=4.5,
                    threshold=threshold,
                )
            )

    return specs


def mine_strategies(
    bars: list[MarketBar],
    mandate: Mandate,
    cost_bps: float = 8.0,
) -> list[tuple[StrategySpec, BacktestResult, RobustnessResult]]:
    candidates: list[
        tuple[StrategySpec, BacktestResult, RobustnessResult]
    ] = []
    for spec in _candidate_specs():
        bt = backtest(spec, bars, cost_bps)
        rb = robustness(spec, bars, mandate, cost_bps)
        if rb.passed:
            candidates.append((spec, bt, rb))
    candidates.sort(
        key=lambda item: (
            item[1].profit_factor,
            item[1].pnl_pct,
            item[1].trades,
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
    """Return long/flat from the latest completed bar for any supported family."""
    if len(bars) < spec.slow + 1:
        return "flat"
    closes = [b.close for b in bars]
    i = len(closes) - 1
    return "long" if _entry_signal(spec, closes, i) or (
        signal_state_series(spec, bars)[-1] == 1
    ) else "flat"


def current_decision(
    spec: StrategySpec,
    bars: list[MarketBar],
    *,
    symbol: str,
    requested_weight: float = 1.0,
) -> StrategyDecision:
    """Return the venue-agnostic strategy decision for the latest bar."""
    signal = current_signal(spec, bars)
    as_of = bars[-1].ts if bars else None
    return decision_from_signal(
        symbol=symbol,
        strategy_id=spec.name,
        signal=signal,
        requested_weight=float(requested_weight),
        as_of=as_of,
    )


def target_position_series(
    spec: StrategySpec,
    bars: list[MarketBar],
    *,
    symbol: str,
    requested_weight: float = 1.0,
    equity: float = 1.0,
    max_notional: float | None = None,
) -> list[TargetPosition]:
    """Research/backtest representation using the same target schema as execution."""
    if not 0.0 <= float(requested_weight) <= 1.0:
        raise ValueError("requested_weight_must_be_in_0_1")
    ceiling = float(equity) if max_notional is None else float(max_notional)
    states = signal_state_series(spec, bars)
    targets: list[TargetPosition] = []
    for bar, state in zip(bars, states):
        decision = decision_from_signal(
            symbol=symbol,
            strategy_id=spec.name,
            signal="long" if state else "flat",
            requested_weight=float(requested_weight),
            as_of=bar.ts,
        )
        targets.append(
            resolve_target_position(
                decision,
                equity=float(equity),
                max_notional=ceiling,
            )
        )
    return targets



def execution_plan_series(
    spec: StrategySpec,
    bars: list[MarketBar],
    *,
    symbol: str,
    requested_weight: float = 1.0,
    equity: float = 1.0,
    max_notional: float | None = None,
) -> list[ExecutionPlan]:
    """Historical Execution Fabric trace for research/backtest diagnostics.

    The trace uses the same target resolver and planner as paper/testnet.
    It intentionally models strategy state transitions, not venue slippage.
    """
    targets = target_position_series(
        spec,
        bars,
        symbol=symbol,
        requested_weight=requested_weight,
        equity=equity,
        max_notional=max_notional,
    )
    plans: list[ExecutionPlan] = []
    current_notional = 0.0
    for bar, target in zip(bars, targets):
        plan = plan_execution(
            target,
            current_notional=current_notional,
            reference_price=bar.close,
            allow_new_risk=True,
        )
        plans.append(plan)
        current_notional = plan.effective_target_notional
    return plans



def backtest_execution_trace(
    spec: StrategySpec,
    bars: list[MarketBar],
    *,
    symbol: str,
    requested_weight: float = 1.0,
    equity: float = 1.0,
    max_notional: float | None = None,
    cost_bps: float = 8.0,
) -> dict:
    """Map the exact backtest trade log into Execution Fabric objects."""
    result = backtest(spec, bars, cost_bps=cost_bps)
    running_equity = float(equity)
    events: list[dict] = []

    for trade in result.trade_log:
        ceiling = (
            running_equity
            if max_notional is None
            else min(float(max_notional), running_equity)
        )
        entry_decision = decision_from_signal(
            symbol=symbol,
            strategy_id=spec.name,
            signal="long",
            requested_weight=float(requested_weight),
            as_of=trade.entry_ts,
            reason="backtest_entry",
        )
        entry_target = resolve_target_position(
            entry_decision,
            equity=running_equity,
            max_notional=ceiling,
        )
        entry_plan = plan_execution(
            entry_target,
            current_notional=0.0,
            reference_price=trade.entry,
        )
        events.append(
            {
                "phase": "entry",
                "reason": "signal",
                "decision": entry_decision.to_dict(),
                "target": entry_target.to_dict(),
                "plan": entry_plan.to_dict(),
            }
        )

        marked_notional = (
            entry_target.target_notional
            * trade.exit
            / trade.entry
            if trade.entry > 0
            else entry_target.target_notional
        )
        exit_decision = decision_from_signal(
            symbol=symbol,
            strategy_id=spec.name,
            signal="flat",
            requested_weight=0.0,
            as_of=trade.exit_ts,
            reason=f"backtest_exit:{trade.reason}",
        )
        exit_target = resolve_target_position(
            exit_decision,
            equity=running_equity,
            max_notional=ceiling,
        )
        exit_plan = plan_execution(
            exit_target,
            current_notional=marked_notional,
            reference_price=trade.exit,
            allow_new_risk=False,
        )
        events.append(
            {
                "phase": "exit",
                "reason": trade.reason,
                "decision": exit_decision.to_dict(),
                "target": exit_target.to_dict(),
                "plan": exit_plan.to_dict(),
            }
        )
        running_equity *= 1.0 + trade.pnl_pct / 100.0

    return {
        "strategy": spec.name,
        "symbol": symbol.upper(),
        "requested_weight": float(requested_weight),
        "backtest": result.to_dict(),
        "events": events,
    }
