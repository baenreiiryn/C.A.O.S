from __future__ import annotations

from dataclasses import asdict

from ..domain import StrategySpec


class CompanyStrategyError(RuntimeError):
    pass


class CompanyStrategyRegistry:
    """Company-visible deterministic strategies backed by C.A.O.S specs."""

    def __init__(self):
        self.strategies: dict[str, StrategySpec] = {}

    def register(
        self,
        spec: StrategySpec,
        *,
        strategy_id: str | None = None,
    ) -> str:
        key = strategy_id or spec.name
        if not key:
            raise ValueError("strategy_id required")
        existing = self.strategies.get(key)
        if existing is not None and existing != spec:
            raise CompanyStrategyError("strategy_id_conflict")
        self.strategies[key] = spec
        return key

    def get(self, strategy_id: str) -> StrategySpec:
        try:
            return self.strategies[strategy_id]
        except KeyError as exc:
            raise CompanyStrategyError("unknown_strategy") from exc

    def snapshot(self) -> dict:
        return {
            key: asdict(spec)
            for key, spec in sorted(self.strategies.items())
        }

    def restore(self, snapshot: dict) -> None:
        self.strategies = {
            str(key): StrategySpec(**value)
            for key, value in snapshot.items()
        }
