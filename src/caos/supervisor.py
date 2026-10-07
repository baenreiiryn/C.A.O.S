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



def audit_portfolio(caos) -> dict:
    if caos.paper is None:
        return {
            "status": "unavailable",
            "reports": [],
            "alerts": [],
        }

    reports = []
    alerts = []
    for entry in caos.portfolio:
        realized = [
            float(row["pnl_pct"])
            for row in caos.paper.realized_trades
            if row.get("symbol") == entry.symbol
            and row.get("strategy") == entry.strategy.name
        ]
        report = divergence(entry.expected, realized)
        payload = {
            "symbol": entry.symbol,
            "strategy": entry.strategy.name,
            "realized_trades": len(realized),
            "divergence": {
                "expected_win_rate_pct": report.expected_win_rate_pct,
                "realized_win_rate_pct": report.realized_win_rate_pct,
                "expected_profit_factor": report.expected_profit_factor,
                "realized_profit_factor": report.realized_profit_factor,
                "score": report.score,
                "status": report.status,
            },
        }
        reports.append(payload)
        if report.status == "diverged":
            alerts.append(
                {
                    "symbol": entry.symbol,
                    "strategy": entry.strategy.name,
                    "reason": "expected_vs_real_divergence",
                    "score": report.score,
                }
            )

    status = (
        "alert"
        if alerts
        else "watch"
        if any(
            x["divergence"]["status"] == "watch"
            for x in reports
        )
        else "ok"
    )
    return {
        "status": status,
        "reports": reports,
        "alerts": alerts,
    }
