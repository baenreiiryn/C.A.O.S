from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Literal


class TraderMode(str, Enum):
    PRODUCTION = "production"
    TRAINING = "training"


class TraderStatus(str, Enum):
    CANDIDATE = "candidate"
    WAITING_ASSIGNMENT = "waiting_assignment"
    ACTIVE = "active"
    PAUSED = "paused"
    EVALUATING = "evaluating"
    HALTED = "halted"
    RETIRED = "retired"


class OpportunityStatus(str, Enum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    AVAILABLE = "available"
    RESERVED = "reserved"
    ACTIVE = "active"
    EXPIRED = "expired"


@dataclass(slots=True, frozen=True)
class CompanyPolicy:
    initial_company_capital: float = 10.0
    trader_initial_bucket: float = 10.0
    trader_stop_floor: float = 3.0
    default_trader_max_exposure_pct: float = 20.0
    company_max_drawdown_pct: float = 30.0
    production_market_exclusivity: bool = True
    training_market_overlap: bool = True
    allow_paper: bool = True
    allow_testnet: bool = True
    allow_live: bool = False

    def __post_init__(self) -> None:
        positive = {
            "initial_company_capital": self.initial_company_capital,
            "trader_initial_bucket": self.trader_initial_bucket,
            "trader_stop_floor": self.trader_stop_floor,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.initial_company_capital < self.trader_initial_bucket:
            raise ValueError(
                "initial_company_capital must fund the first trader"
            )
        if not 0 < self.default_trader_max_exposure_pct <= 100:
            raise ValueError(
                "default_trader_max_exposure_pct must be in (0, 100]"
            )
        if not 0 < self.company_max_drawdown_pct <= 100:
            raise ValueError("company_max_drawdown_pct must be in (0, 100]")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Trader:
    id: str
    status: TraderStatus = TraderStatus.WAITING_ASSIGNMENT
    mode: TraderMode = TraderMode.PRODUCTION
    strategy_id: str | None = None
    market: str | None = None
    direction: Literal["long", "short"] | None = None
    max_trade_exposure_pct: float = 20.0
    trade_exposure_pct: float | None = None
    spawned_from: str | None = None
    generation: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 < self.max_trade_exposure_pct <= 100:
            raise ValueError("max_trade_exposure_pct must be in (0, 100]")
        if self.trade_exposure_pct is not None:
            if not 0 < self.trade_exposure_pct <= self.max_trade_exposure_pct:
                raise ValueError(
                    "trade_exposure_pct must be in (0, max_trade_exposure_pct]"
                )

    def requested_trade_exposure_pct(self) -> float:
        """Desired size is separate from the hard ceiling.

        Until a sizing policy is attached, the legacy/default behavior is to
        request the ceiling. A Trader/strategy may set trade_exposure_pct lower.
        """
        return (
            self.max_trade_exposure_pct
            if self.trade_exposure_pct is None
            else self.trade_exposure_pct
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        out["status"] = self.status.value
        out["mode"] = self.mode.value
        return out


@dataclass(slots=True)
class Opportunity:
    id: str
    symbol: str
    direction: Literal["long", "short"]
    score: float
    regime: str = "unknown"
    strategy_candidates: tuple[str, ...] = ()
    estimated_cost_bps: float | None = None
    liquidity_score: float | None = None
    risk_score: float | None = None
    status: OpportunityStatus = OpportunityStatus.DISCOVERED
    reserved_by: str | None = None
    expires_at: int | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = self.symbol.upper()
        if not self.symbol:
            raise ValueError("symbol required")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.expires_at is not None and self.expires_at < 0:
            raise ValueError("expires_at cannot be negative")

    def expired(self, now: int | None) -> bool:
        return (
            now is not None
            and self.expires_at is not None
            and now >= self.expires_at
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        out["status"] = self.status.value
        out["strategy_candidates"] = list(self.strategy_candidates)
        return out
