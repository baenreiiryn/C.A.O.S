from __future__ import annotations

from dataclasses import dataclass, field

from ..quant import backtest, current_signal, market_regime
from .domain import Opportunity, OpportunityStatus


DEFAULT_AUTO_TIMEFRAMES = ("1m", "5m", "15m", "1h")


@dataclass(slots=True)
class AutonomousMarketScanner:
    company: object
    timeframes: tuple[str, ...] = DEFAULT_AUTO_TIMEFRAMES
    candidate_limit: int = 10
    publish_limit: int = 6
    min_quote_volume: float = 5_000_000.0
    bars_limit: int = 180
    latest_rankings: list[dict] = field(default_factory=list)

    @staticmethod
    def _strategy_score(
        *,
        regime: dict,
        signal: str,
        backtest_result,
        price_change_pct: float,
    ) -> float:
        score = 35.0

        regime_name = str(regime.get("regime", "unknown"))
        trend = float(regime.get("trend_pct", 0.0))
        vol = max(
            0.0,
            float(regime.get("volatility_pct", 0.0)),
        )
        if regime_name == "trend_up":
            score += 12.0
        elif regime_name == "range":
            score += 4.0

        score += min(8.0, abs(trend) * 1.5)
        score -= min(10.0, vol * 2.5)
        score += 18.0 if signal == "long" else 0.0

        trades = int(backtest_result.trades)
        if trades >= 3:
            score += 4.0
        score += max(
            -8.0,
            min(
                12.0,
                (float(backtest_result.profit_factor) - 1.0)
                * 8.0,
            ),
        )
        score += max(
            -8.0,
            min(
                10.0,
                float(backtest_result.expectancy_pct) * 5.0,
            ),
        )
        score += max(
            -6.0,
            min(
                6.0,
                float(backtest_result.pnl_pct) * 0.5,
            ),
        )
        score -= min(
            12.0,
            float(backtest_result.max_drawdown_pct) * 0.75,
        )
        score += min(
            4.0,
            abs(float(price_change_pct)) * 0.15,
        )
        return max(0.0, min(100.0, score))

    def scan(
        self,
        *,
        now: int,
        opportunity_ttl_ms: int,
    ) -> list[str]:
        for opportunity in (
            self.company.opportunities.opportunities.values()
        ):
            if (
                opportunity.metadata.get("selection_mode")
                == "auto"
                and opportunity.status
                not in {
                    OpportunityStatus.ACTIVE,
                    OpportunityStatus.EXPIRED,
                }
            ):
                opportunity.status = (
                    OpportunityStatus.EXPIRED
                )
                opportunity.reserved_by = None

        client = self.company.engine.caos.market_client
        markets = client.liquid_usdt_candidates(
            limit=self.candidate_limit,
            min_quote_volume=self.min_quote_volume,
        )
        strategies = list(
            self.company.strategies.strategies.items()
        )
        rankings: list[dict] = []
        bars_cache: dict[
            tuple[str, str],
            list,
        ] = {}

        for market in markets:
            symbol = str(market["symbol"]).upper()
            best: dict | None = None
            for timeframe in self.timeframes:
                try:
                    bars = client.klines(
                        symbol,
                        timeframe,
                        self.bars_limit,
                    )
                except Exception:
                    continue
                if len(bars) < 60:
                    continue
                bars_cache[
                    (symbol, timeframe)
                ] = bars
                regime = market_regime(bars)

                for strategy_id, spec in strategies:
                    if not (
                        self.company.rollout.is_strategy_assignable(
                            symbol,
                            strategy_id,
                        )
                    ):
                        continue
                    result = backtest(
                        spec,
                        bars,
                        cost_bps=8.0,
                    )
                    signal = current_signal(spec, bars)
                    score = self._strategy_score(
                        regime=regime,
                        signal=signal,
                        backtest_result=result,
                        price_change_pct=float(
                            market.get(
                                "price_change_pct",
                                0.0,
                            )
                        ),
                    )
                    row = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy_id,
                        "signal": signal,
                        "score": score,
                        "regime": regime,
                        "backtest": {
                            "trades": result.trades,
                            "pnl_pct": result.pnl_pct,
                            "win_rate_pct": (
                                result.win_rate_pct
                            ),
                            "profit_factor": (
                                result.profit_factor
                            ),
                            "max_drawdown_pct": (
                                result.max_drawdown_pct
                            ),
                            "expectancy_pct": (
                                result.expectancy_pct
                            ),
                        },
                        "quote_volume": float(
                            market.get(
                                "quote_volume",
                                0.0,
                            )
                        ),
                        "price_change_pct": float(
                            market.get(
                                "price_change_pct",
                                0.0,
                            )
                        ),
                    }
                    if (
                        best is None
                        or row["score"] > best["score"]
                    ):
                        best = row
            if best is not None:
                rankings.append(best)

        rankings.sort(
            key=lambda row: (
                row["score"],
                row["quote_volume"],
            ),
            reverse=True,
        )

        caos = self.company.engine.caos
        runtime = getattr(
            caos,
            "expert_runtime",
            None,
        )
        loaded = set()
        if runtime is not None:
            try:
                loaded = set(
                    runtime.status().get(
                        "loaded",
                        [],
                    )
                )
            except Exception:
                loaded = set()
        forecast_names = [
            name
            for name in sorted(
                caos.forecast_experts
            )
            if name in loaded
        ]
        for row in rankings[: min(
            self.publish_limit,
            3,
        )]:
            row["oracle_evidence"] = None
            row["oracle_errors"] = {}
            if not forecast_names:
                continue
            bars = bars_cache.get(
                (
                    str(row["symbol"]),
                    str(row["timeframe"]),
                )
            )
            if not bars:
                continue
            forecasts = []
            for name in forecast_names:
                try:
                    forecasts.append(
                        caos.forecast_experts[
                            name
                        ].forecast(
                            str(row["symbol"]),
                            bars,
                            3,
                        )
                    )
                except Exception as exc:
                    row["oracle_errors"][
                        name
                    ] = (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
            if forecasts:
                outlook = (
                    caos.expert_ensemble.combine(
                        forecasts
                    )
                )
                evidence = outlook.to_dict()
                row["oracle_evidence"] = (
                    evidence
                )
                if (
                    evidence.get("direction")
                    == "bearish"
                ):
                    agreement = float(
                        evidence.get(
                            "agreement_score",
                            0.0,
                        )
                    )
                    penalty = min(
                        15.0,
                        5.0
                        + 10.0
                        * max(
                            0.0,
                            min(
                                1.0,
                                agreement,
                            ),
                        ),
                    )
                    row["score"] = max(
                        0.0,
                        float(row["score"])
                        - penalty,
                    )
                    row[
                        "oracle_penalty"
                    ] = penalty

        rankings.sort(
            key=lambda row: (
                row["score"],
                row["quote_volume"],
            ),
            reverse=True,
        )
        self.latest_rankings = rankings[:20]

        created: list[str] = []
        for index, row in enumerate(
            rankings[: self.publish_limit]
        ):
            symbol = str(row["symbol"])
            news_context = (
                self.company.news_intelligence.context_for(
                    symbol
                )
            )
            if news_context.get("block_new_risk"):
                continue
            score = max(
                0.0,
                float(row["score"])
                - float(
                    news_context.get(
                        "score_penalty",
                        0.0,
                    )
                ),
            )
            opportunity = Opportunity(
                id=(
                    "auto:"
                    + symbol
                    + ":"
                    + str(row["timeframe"])
                    + ":"
                    + str(row["strategy_id"])
                    + ":"
                    + str(now)
                    + ":"
                    + str(index)
                ),
                symbol=symbol,
                direction="long",
                score=score,
                regime=str(
                    row["regime"].get(
                        "regime",
                        "unknown",
                    )
                ),
                strategy_candidates=(
                    str(row["strategy_id"]),
                ),
                expires_at=(
                    int(now) + int(opportunity_ttl_ms)
                ),
                metadata={
                    "selection_mode": "auto",
                    "timeframe": str(
                        row["timeframe"]
                    ),
                    "strategy_id": str(
                        row["strategy_id"]
                    ),
                    "signal_at_scan": str(
                        row["signal"]
                    ),
                    "quote_volume": row[
                        "quote_volume"
                    ],
                    "price_change_pct": row[
                        "price_change_pct"
                    ],
                    "trend_pct": float(
                        row["regime"].get(
                            "trend_pct",
                            0.0,
                        )
                    ),
                    "volatility_pct": float(
                        row["regime"].get(
                            "volatility_pct",
                            0.0,
                        )
                    ),
                    "backtest": dict(
                        row["backtest"]
                    ),
                    "news_context": news_context,
                    "oracle_evidence": row.get(
                        "oracle_evidence"
                    ),
                    "oracle_errors": dict(
                        row.get(
                            "oracle_errors",
                            {},
                        )
                    ),
                    "oracle_penalty": float(
                        row.get(
                            "oracle_penalty",
                            0.0,
                        )
                    ),
                },
            )
            self.company.opportunities.add(
                opportunity
            )
            self.company.opportunities.validate(
                opportunity.id
            )
            self.company.opportunities.make_available(
                opportunity.id
            )
            created.append(opportunity.id)
        return created

    def status(self) -> dict:
        return {
            "mode": "auto",
            "timeframes": list(self.timeframes),
            "candidate_limit": int(self.candidate_limit),
            "publish_limit": int(self.publish_limit),
            "min_quote_volume": float(
                self.min_quote_volume
            ),
            "latest_rankings": [
                dict(row)
                for row in self.latest_rankings
            ],
        }
