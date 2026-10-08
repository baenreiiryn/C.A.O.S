from __future__ import annotations

from dataclasses import dataclass

from .domain import TraderMode, TraderStatus
from .registry import TraderRegistry


@dataclass(slots=True, frozen=True)
class DiversityReport:
    active_production: int
    long_share: float
    short_share: float
    strategy_family_shares: dict[str, float]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "active_production": self.active_production,
            "long_share": self.long_share,
            "short_share": self.short_share,
            "strategy_family_shares": dict(self.strategy_family_shares),
            "warnings": list(self.warnings),
        }


class StrategyDiversity:
    """Company-wide concentration observer.

    It reports concentration now; hard thresholds can later be promoted into
    CompanyPolicy without changing Trader or C.A.O.S internals.
    """

    def __init__(self, registry: TraderRegistry):
        self.registry = registry

    def audit(self) -> DiversityReport:
        traders = [
            t for t in self.registry.traders.values()
            if t.mode == TraderMode.PRODUCTION
            and t.status == TraderStatus.ACTIVE
        ]
        total = len(traders)
        if not total:
            return DiversityReport(0, 0.0, 0.0, {}, ())

        long_count = sum(t.direction == "long" for t in traders)
        short_count = sum(t.direction == "short" for t in traders)
        families: dict[str, int] = {}
        for trader in traders:
            family = str(trader.metadata.get("strategy_family", "unknown"))
            families[family] = families.get(family, 0) + 1

        family_shares = {
            family: count / total
            for family, count in sorted(families.items())
        }
        warnings: list[str] = []
        if total >= 3 and max(long_count, short_count) / total >= 0.8:
            warnings.append("direction_concentration")
        if total >= 3 and family_shares and max(family_shares.values()) >= 0.8:
            warnings.append("strategy_family_concentration")

        return DiversityReport(
            active_production=total,
            long_share=long_count / total,
            short_share=short_count / total,
            strategy_family_shares=family_shares,
            warnings=tuple(warnings),
        )
