from __future__ import annotations

from .domain import BacktestResult, DivergenceReport


def _realized_stats(pnls_pct: list[float]) -> tuple[float, float]:
    if not pnls_pct:
        return 0.0, 0.0
    wins = [x for x in pnls_pct if x > 0]
    losses = [x for x in pnls_pct if x < 0]
    wr = len(wins) / len(pnls_pct) * 100.0
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = gp / gl if gl > 1e-12 else (999.0 if gp > 0 else 0.0)
    return wr, pf


def divergence(expected: BacktestResult, realized_pnls_pct: list[float]) -> DivergenceReport:
    if len(realized_pnls_pct) < 5:
        return DivergenceReport(
            expected.win_rate_pct,
            0.0,
            expected.profit_factor,
            0.0,
            0.0,
            "insufficient_data",
        )
    wr, pf = _realized_stats(realized_pnls_pct)
    wr_gap = abs(expected.win_rate_pct - wr) / max(1.0, expected.win_rate_pct)
    pf_gap = abs(expected.profit_factor - pf) / max(
        1.0, min(expected.profit_factor, 10.0)
    )
    score = max(0.0, 1.0 - (wr_gap * 0.45 + min(pf_gap, 2.0) * 0.55))
    status = "aligned" if score >= 0.75 else "watch" if score >= 0.5 else "diverged"
    return DivergenceReport(
        expected.win_rate_pct,
        wr,
        expected.profit_factor,
        pf,
        round(score, 4),
        status,
    )
