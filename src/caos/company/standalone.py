from __future__ import annotations

from dataclasses import dataclass

from ..domain import StrategySpec
from .adapter import CAOSAdapter
from .company import TradeCompany, TradeCompanyError
from .daemon import CompanyDaemon, ScanTarget
from .domain import CompanyPolicy, TraderMode


class CompanyStandaloneError(RuntimeError):
    pass


BUILTIN_STRATEGIES: dict[str, StrategySpec] = {
    "trend": StrategySpec(
        "trend",
        "trend",
        5,
        34,
        threshold=1.0,
    ),
    "momentum": StrategySpec(
        "momentum",
        "momentum",
        5,
        34,
        threshold=0.5,
    ),
    "breakout": StrategySpec(
        "breakout",
        "breakout",
        10,
        50,
        threshold=1.0,
    ),
    "mean_reversion": StrategySpec(
        "mean_reversion",
        "mean_reversion",
        8,
        40,
        threshold=1.5,
    ),
}


def parse_scan_targets(value: str) -> list[ScanTarget]:
    """Parse SYMBOL[:direction[:strategy+strategy]] entries.

    Examples:
      BTCUSDT
      BTCUSDT:long:momentum
      BTCUSDT:long:momentum+trend,ETHUSDT:long:trend
    """
    targets: list[ScanTarget] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split(":")]
        symbol = parts[0].upper()
        direction = (
            parts[1].lower()
            if len(parts) >= 2 and parts[1]
            else "long"
        )
        strategies = (
            tuple(
                item.strip()
                for item in parts[2].split("+")
                if item.strip()
            )
            if len(parts) >= 3 and parts[2]
            else ("momentum",)
        )
        key = (symbol, direction, strategies)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            ScanTarget(
                symbol=symbol,
                direction=direction,
                strategy_candidates=strategies,
            )
        )
    if not targets:
        raise CompanyStandaloneError("at_least_one_scan_target_required")
    return targets


def register_builtin_strategies(
    company: TradeCompany,
    targets: list[ScanTarget],
) -> list[str]:
    required = {
        strategy
        for target in targets
        for strategy in target.strategy_candidates
    }
    unknown = sorted(required - BUILTIN_STRATEGIES.keys())
    if unknown:
        raise CompanyStandaloneError(
            "unknown_builtin_strategies:" + ",".join(unknown)
        )
    registered = []
    for strategy_id in sorted(required):
        company.register_strategy(
            BUILTIN_STRATEGIES[strategy_id],
            strategy_id=strategy_id,
        )
        registered.append(strategy_id)
    return registered


def build_policy(
    *,
    initial_company_capital: float,
    trader_initial_bucket: float,
    trader_stop_floor: float,
    default_trader_max_exposure_pct: float,
    operational_trader_cap: int,
    company_max_drawdown_pct: float,
) -> CompanyPolicy:
    return CompanyPolicy(
        initial_company_capital=float(initial_company_capital),
        trader_initial_bucket=float(trader_initial_bucket),
        trader_stop_floor=float(trader_stop_floor),
        default_trader_max_exposure_pct=float(
            default_trader_max_exposure_pct
        ),
        operational_trader_cap=int(operational_trader_cap),
        company_max_drawdown_pct=float(company_max_drawdown_pct),
    )


def build_standalone_company(
    caos,
    policy: CompanyPolicy,
    *,
    restore: bool = True,
) -> tuple[TradeCompany, bool]:
    company = TradeCompany(
        CAOSAdapter(caos),
        policy,
        store=caos.store,
    )
    restored = bool(restore and company.restore_checkpoint())
    return company, restored


def initialize_company(
    company: TradeCompany,
    targets: list[ScanTarget],
    *,
    mode: TraderMode = TraderMode.PRODUCTION,
    max_trade_exposure_pct: float | None = None,
    trade_exposure_pct: float | None = None,
) -> dict:
    if company.registry.slot_count() != 0:
        raise CompanyStandaloneError("company_already_initialized")
    strategies = register_builtin_strategies(company, targets)
    trader = company.bootstrap(
        mode=mode,
        max_trade_exposure_pct=max_trade_exposure_pct,
        trade_exposure_pct=trade_exposure_pct,
    )
    company.checkpoint()
    return {
        "initialized": True,
        "first_trader": trader.to_dict(),
        "strategies": strategies,
        "targets": [
            {
                "symbol": target.symbol,
                "direction": target.direction,
                "strategy_candidates": list(
                    target.strategy_candidates
                ),
            }
            for target in targets
        ],
    }


def require_initialized(company: TradeCompany) -> None:
    if company.registry.slot_count() == 0:
        raise CompanyStandaloneError(
            "company_not_initialized_run_company_init_first"
        )


def build_daemon(
    company: TradeCompany,
    targets: list[ScanTarget],
    *,
    interval: str = "60",
    candle_limit: int = 500,
    opportunity_ttl_ms: int = 3_600_000,
) -> CompanyDaemon:
    return CompanyDaemon(
        company,
        targets,
        interval=interval,
        candle_limit=int(candle_limit),
        opportunity_ttl_ms=int(opportunity_ttl_ms),
    )
