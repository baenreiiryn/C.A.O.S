from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Literal


class Mode(str, Enum):
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


@dataclass(slots=True)
class Mandate:
    capital: float
    max_drawdown_pct: float
    objective: str = "consistency"
    horizon_months: int = 6
    max_position_pct: float = 20.0

    def __post_init__(self) -> None:
        if self.capital <= 0:
            raise ValueError("capital must be positive")
        if not 0 < self.max_drawdown_pct <= 100:
            raise ValueError("max_drawdown_pct must be in (0, 100]")
        if not 0 < self.max_position_pct <= 100:
            raise ValueError("max_position_pct must be in (0, 100]")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class MarketBar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True, frozen=True)
class StrategySpec:
    name: str
    family: str
    fast: int
    slow: int
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    threshold: float = 1.5

    def __post_init__(self) -> None:
        if self.fast <= 0 or self.slow <= 0 or self.fast >= self.slow:
            raise ValueError("strategy requires 0 < fast < slow")
        if self.family not in {"trend", "mean_reversion", "breakout", "momentum"}:
            raise ValueError("unsupported strategy family")
        if self.stop_loss_pct <= 0 or self.take_profit_pct <= 0:
            raise ValueError("stop/target must be positive")
        if self.threshold < 0:
            raise ValueError("threshold cannot be negative")


@dataclass(slots=True)
class Trade:
    entry_ts: int
    exit_ts: int
    side: Literal["long", "short"]
    entry: float
    exit: float
    pnl_pct: float
    reason: str


@dataclass(slots=True)
class BacktestResult:
    strategy: str
    trades: int
    pnl_pct: float
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    expectancy_pct: float
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[Trade] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trade_log"] = [asdict(t) for t in self.trade_log]
        return d


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: Literal["buy", "sell"]
    notional: float
    price: float
    strategy: str


@dataclass(slots=True)
class Fill:
    symbol: str
    side: Literal["buy", "sell"]
    notional: float
    price: float
    fee: float
    strategy: str


@dataclass(slots=True)
class PendingOrder:
    id: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float
    order_type: Literal["limit", "stop"]
    trigger_price: float
    strategy: str
    status: str = "open"


@dataclass(slots=True)
class Position:
    symbol: str
    notional: float = 0.0
    avg_price: float = 0.0
    quantity: float = 0.0
    fees_paid: float = 0.0
    realized_pnl: float = 0.0
    strategy: str = ""


@dataclass(slots=True)
class DivergenceReport:
    expected_win_rate_pct: float
    realized_win_rate_pct: float
    expected_profit_factor: float
    realized_profit_factor: float
    score: float
    status: Literal["insufficient_data", "aligned", "watch", "diverged"]
