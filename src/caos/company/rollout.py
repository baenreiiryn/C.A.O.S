from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..domain import MarketBar
from ..execution_fabric import (
    EXECUTION_FABRIC_VERSION,
    plan_execution,
    resolve_target_position,
)
from ..quant import current_decision
from .research import ResearchFactory
from .strategy import CompanyStrategyRegistry


STRATEGY_ROLLOUT_VERSION = "strategy-rollout/v1"
RolloutStage = Literal[
    "shadow",
    "paper_canary",
    "eligible",
    "active",
    "rolled_back",
]


class StrategyRolloutError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class StrategyRolloutPolicy:
    min_shadow_observations: int = 3
    min_canary_observations: int = 20
    min_canary_trades: int = 1
    canary_starting_capital: float = 10.0
    canary_exposure_pct: float = 5.0
    canary_fee_bps: float = 8.0
    max_canary_drawdown_pct: float = 10.0
    min_canary_pnl_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.min_shadow_observations < 1:
            raise ValueError("min_shadow_observations_must_be_positive")
        if self.min_canary_observations < 1:
            raise ValueError("min_canary_observations_must_be_positive")
        if self.min_canary_trades < 0:
            raise ValueError("min_canary_trades_cannot_be_negative")
        if self.canary_starting_capital <= 0:
            raise ValueError("canary_starting_capital_must_be_positive")
        if not 0 < self.canary_exposure_pct <= 100:
            raise ValueError("canary_exposure_pct_must_be_in_0_100")
        if self.canary_fee_bps < 0:
            raise ValueError("canary_fee_bps_cannot_be_negative")
        if not 0 < self.max_canary_drawdown_pct <= 100:
            raise ValueError("max_canary_drawdown_pct_must_be_in_0_100")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CanaryAccount:
    starting_capital: float
    cash: float
    quantity: float = 0.0
    equity: float = 0.0
    peak_equity: float = 0.0
    pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    observations: int = 0
    trades: int = 0
    last_ts: int | None = None
    last_plan_id: str | None = None

    @classmethod
    def create(cls, starting_capital: float) -> "CanaryAccount":
        capital = float(starting_capital)
        return cls(
            starting_capital=capital,
            cash=capital,
            equity=capital,
            peak_equity=capital,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class StrategyRelease:
    id: str
    symbol: str
    strategy_id: str
    research_decision_id: str
    stage: RolloutStage = "shadow"
    shadow_observations: int = 0
    shadow_long_signals: int = 0
    shadow_last_ts: int | None = None
    canary: CanaryAccount | None = None
    rollback_reason: str | None = None
    stage_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "research_decision_id": self.research_decision_id,
            "stage": self.stage,
            "shadow_observations": self.shadow_observations,
            "shadow_long_signals": self.shadow_long_signals,
            "shadow_last_ts": self.shadow_last_ts,
            "canary": (
                self.canary.to_dict()
                if self.canary is not None
                else None
            ),
            "rollback_reason": self.rollback_reason,
            "stage_history": list(self.stage_history),
        }


def _release_id(
    symbol: str,
    strategy_id: str,
    research_decision_id: str,
) -> str:
    raw = json.dumps(
        {
            "symbol": symbol.upper(),
            "strategy_id": strategy_id,
            "research_decision_id": research_decision_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "release-" + hashlib.sha256(raw).hexdigest()[:24]


class StrategyRolloutManager:
    """Controlled bridge from research champion to future assignments.

    Rollout never allocates Treasury capital and never creates a Trader.
    """

    def __init__(
        self,
        strategies: CompanyStrategyRegistry,
        *,
        policy: StrategyRolloutPolicy | None = None,
    ):
        self.strategies = strategies
        self.policy = policy or StrategyRolloutPolicy()
        self.releases: dict[str, StrategyRelease] = {}
        self.production_catalog: dict[str, str] = {}

    def _transition(
        self,
        release: StrategyRelease,
        stage: RolloutStage,
        reason: str,
    ) -> None:
        if release.stage == stage:
            return
        release.stage_history.append(
            {
                "from": release.stage,
                "to": stage,
                "reason": reason,
            }
        )
        release.stage = stage

    def sync_research(
        self,
        research: ResearchFactory,
    ) -> list[StrategyRelease]:
        created: list[StrategyRelease] = []
        known_decisions = {
            row.research_decision_id
            for row in self.releases.values()
        }
        for decision in research.decisions:
            if (
                decision.status != "promoted"
                or not decision.candidate_strategy_id
                or decision.id in known_decisions
            ):
                continue
            # Promotion must already have registered the strategy.
            self.strategies.get(decision.candidate_strategy_id)
            release = StrategyRelease(
                id=_release_id(
                    decision.symbol,
                    decision.candidate_strategy_id,
                    decision.id,
                ),
                symbol=decision.symbol.upper(),
                strategy_id=decision.candidate_strategy_id,
                research_decision_id=decision.id,
                stage_history=[
                    {
                        "from": None,
                        "to": "shadow",
                        "reason": "research_champion_promoted",
                    }
                ],
            )
            self.releases[release.id] = release
            created.append(release)
            known_decisions.add(decision.id)
        return created

    def get(self, release_id: str) -> StrategyRelease:
        try:
            return self.releases[release_id]
        except KeyError as exc:
            raise StrategyRolloutError(
                "unknown_strategy_release"
            ) from exc

    def releases_for_symbol(
        self,
        symbol: str,
    ) -> list[StrategyRelease]:
        symbol = symbol.upper()
        return [
            row
            for row in self.releases.values()
            if row.symbol == symbol
        ]

    def _shadow_step(
        self,
        release: StrategyRelease,
        bars: list[MarketBar],
    ) -> list[dict]:
        events: list[dict] = []
        strategy = self.strategies.get(release.strategy_id)
        for index, bar in enumerate(bars):
            if (
                release.shadow_last_ts is not None
                and bar.ts <= release.shadow_last_ts
            ):
                continue
            decision = current_decision(
                strategy,
                bars[: index + 1],
                symbol=release.symbol,
                requested_weight=(
                    self.policy.canary_exposure_pct / 100.0
                ),
            )
            release.shadow_observations += 1
            release.shadow_long_signals += int(
                decision.signal == "long"
            )
            release.shadow_last_ts = bar.ts
            events.append(
                {
                    "release_id": release.id,
                    "stage": "shadow",
                    "ts": bar.ts,
                    "signal": decision.signal,
                    "decision_id": decision.decision_id,
                }
            )
            if (
                release.shadow_observations
                >= self.policy.min_shadow_observations
            ):
                release.canary = CanaryAccount.create(
                    self.policy.canary_starting_capital
                )
                self._transition(
                    release,
                    "paper_canary",
                    "shadow_observation_gate_passed",
                )
                break
        return events

    def _canary_step(
        self,
        release: StrategyRelease,
        bars: list[MarketBar],
    ) -> list[dict]:
        if release.canary is None:
            raise StrategyRolloutError("canary_account_missing")
        account = release.canary
        strategy = self.strategies.get(release.strategy_id)
        events: list[dict] = []
        fee_rate = self.policy.canary_fee_bps / 10_000.0

        for index, bar in enumerate(bars):
            if account.last_ts is not None and bar.ts <= account.last_ts:
                continue

            price = float(bar.close)
            marked_equity = account.cash + account.quantity * price
            decision = current_decision(
                strategy,
                bars[: index + 1],
                symbol=release.symbol,
                requested_weight=(
                    self.policy.canary_exposure_pct / 100.0
                ),
            )
            max_notional = (
                marked_equity
                * self.policy.canary_exposure_pct
                / 100.0
            )
            target = resolve_target_position(
                decision,
                equity=max(0.0, marked_equity),
                max_notional=max(0.0, max_notional),
            )
            plan = plan_execution(
                target,
                current_notional=account.quantity * price,
                reference_price=price,
                allow_new_risk=True,
                tolerance=max(1e-8, max_notional * 0.01),
            )

            if plan.executable and plan.side == "buy":
                order = min(
                    plan.order_notional,
                    max(
                        0.0,
                        account.cash / (1.0 + fee_rate),
                    ),
                )
                if order > 1e-9:
                    fee = order * fee_rate
                    account.cash -= order + fee
                    account.quantity += order / price
                    account.trades += 1
            elif plan.executable and plan.side == "sell":
                qty = min(
                    account.quantity,
                    plan.order_notional / price,
                )
                if qty > 1e-12:
                    proceeds = qty * price
                    fee = proceeds * fee_rate
                    account.cash += proceeds - fee
                    account.quantity -= qty
                    if account.quantity <= 1e-12:
                        account.quantity = 0.0
                    account.trades += 1

            account.observations += 1
            account.last_ts = bar.ts
            account.last_plan_id = plan.plan_id
            account.equity = (
                account.cash + account.quantity * price
            )
            account.peak_equity = max(
                account.peak_equity,
                account.equity,
            )
            if account.peak_equity > 0:
                drawdown = (
                    (account.peak_equity - account.equity)
                    / account.peak_equity
                    * 100.0
                )
                account.max_drawdown_pct = max(
                    account.max_drawdown_pct,
                    drawdown,
                )
            account.pnl_pct = (
                account.equity / account.starting_capital - 1.0
            ) * 100.0

            events.append(
                {
                    "release_id": release.id,
                    "stage": "paper_canary",
                    "ts": bar.ts,
                    "signal": decision.signal,
                    "plan": plan.to_dict(),
                    "equity": account.equity,
                    "pnl_pct": account.pnl_pct,
                    "max_drawdown_pct": account.max_drawdown_pct,
                    "trades": account.trades,
                }
            )

            if (
                account.max_drawdown_pct
                > self.policy.max_canary_drawdown_pct
            ):
                release.rollback_reason = (
                    "canary_drawdown_gate_failed"
                )
                self._transition(
                    release,
                    "rolled_back",
                    release.rollback_reason,
                )
                break

            if (
                account.observations
                >= self.policy.min_canary_observations
                and account.trades
                >= self.policy.min_canary_trades
                and account.pnl_pct
                >= self.policy.min_canary_pnl_pct
            ):
                self._transition(
                    release,
                    "eligible",
                    "paper_canary_gate_passed",
                )
                break

        return events

    def process_market(
        self,
        symbol: str,
        bars: list[MarketBar],
    ) -> list[dict]:
        if not bars:
            return []
        symbol = symbol.upper()
        events: list[dict] = []
        for release in self.releases_for_symbol(symbol):
            if release.stage == "shadow":
                events.extend(
                    self._shadow_step(release, bars)
                )
            elif release.stage == "paper_canary":
                events.extend(
                    self._canary_step(release, bars)
                )
        return events

    def activate(
        self,
        release_id: str,
    ) -> StrategyRelease:
        release = self.get(release_id)
        if release.stage != "eligible":
            raise StrategyRolloutError(
                "release_not_eligible_for_activation"
            )

        previous_strategy = self.production_catalog.get(
            release.symbol
        )
        if previous_strategy is not None:
            for other in self.releases_for_symbol(
                release.symbol
            ):
                if (
                    other.strategy_id == previous_strategy
                    and other.stage == "active"
                ):
                    other.rollback_reason = (
                        "superseded_by_new_active_release"
                    )
                    self._transition(
                        other,
                        "rolled_back",
                        other.rollback_reason,
                    )

        self.production_catalog[release.symbol] = (
            release.strategy_id
        )
        self._transition(
            release,
            "active",
            "explicit_activation",
        )
        return release

    def rollback(
        self,
        release_id: str,
        *,
        reason: str = "manual_rollback",
    ) -> StrategyRelease:
        release = self.get(release_id)
        if release.stage == "rolled_back":
            return release
        if (
            self.production_catalog.get(release.symbol)
            == release.strategy_id
        ):
            self.production_catalog.pop(release.symbol, None)
        release.rollback_reason = reason
        self._transition(release, "rolled_back", reason)
        return release

    def is_strategy_assignable(
        self,
        symbol: str,
        strategy_id: str,
    ) -> bool:
        symbol = symbol.upper()
        managed = [
            row
            for row in self.releases.values()
            if row.strategy_id == strategy_id
        ]
        if not managed:
            # Research strategies fail closed until a release is synced.
            return not strategy_id.startswith("research:")
        return any(
            row.symbol == symbol and row.stage == "active"
            for row in managed
        )

    def production_candidates(
        self,
        symbol: str,
        configured: tuple[str, ...],
    ) -> tuple[str, ...]:
        active = self.production_catalog.get(symbol.upper())
        if active is None:
            return tuple(configured)
        return (
            active,
            *tuple(
                item
                for item in configured
                if item != active
            ),
        )

    def summary(self) -> dict:
        stages: dict[str, int] = {}
        for release in self.releases.values():
            stages[release.stage] = (
                stages.get(release.stage, 0) + 1
            )
        return {
            "version": STRATEGY_ROLLOUT_VERSION,
            "policy": self.policy.to_dict(),
            "releases": len(self.releases),
            "stages": stages,
            "production_catalog": dict(
                self.production_catalog
            ),
            "execution_fabric_version": (
                EXECUTION_FABRIC_VERSION
            ),
        }

    def snapshot(self) -> dict:
        return {
            "version": STRATEGY_ROLLOUT_VERSION,
            "policy": self.policy.to_dict(),
            "releases": {
                key: row.to_dict()
                for key, row in self.releases.items()
            },
            "production_catalog": dict(
                self.production_catalog
            ),
        }

    def restore(self, snapshot: dict) -> None:
        if not snapshot:
            return
        if snapshot.get("version") != STRATEGY_ROLLOUT_VERSION:
            raise StrategyRolloutError(
                "unsupported_strategy_rollout_version"
            )
        self.policy = StrategyRolloutPolicy(
            **snapshot.get("policy", {})
        )
        self.releases = {}
        for key, row in snapshot.get("releases", {}).items():
            payload = dict(row)
            canary = payload.get("canary")
            payload["canary"] = (
                CanaryAccount(**canary)
                if canary is not None
                else None
            )
            self.releases[key] = StrategyRelease(**payload)
        self.production_catalog = {
            str(symbol).upper(): str(strategy_id)
            for symbol, strategy_id in snapshot.get(
                "production_catalog",
                {},
            ).items()
        }
