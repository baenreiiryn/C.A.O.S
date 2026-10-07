from __future__ import annotations

from .domain import Trader, TraderMode, TraderStatus


class TraderRegistryError(RuntimeError):
    pass


def _alpha_id(index: int) -> str:
    if index < 0:
        raise ValueError("index cannot be negative")
    out = ""
    n = index
    while True:
        n, rem = divmod(n, 26)
        out = chr(ord("A") + rem) + out
        if n == 0:
            return out
        n -= 1


class TraderRegistry:
    def __init__(self):
        self.traders: dict[str, Trader] = {}
        self._next_index = 0

    def create(
        self,
        *,
        mode: TraderMode = TraderMode.PRODUCTION,
        spawned_from: str | None = None,
        metadata: dict | None = None,
    ) -> Trader:
        if spawned_from is not None and spawned_from not in self.traders:
            raise TraderRegistryError("unknown_spawn_source")
        generation = (
            self.traders[spawned_from].generation + 1
            if spawned_from is not None
            else 0
        )
        trader_id = _alpha_id(self._next_index)
        self._next_index += 1
        trader = Trader(
            id=trader_id,
            mode=mode,
            spawned_from=spawned_from,
            generation=generation,
            metadata=dict(metadata or {}),
        )
        self.traders[trader_id] = trader
        return trader

    def get(self, trader_id: str) -> Trader:
        try:
            return self.traders[trader_id]
        except KeyError as exc:
            raise TraderRegistryError("unknown_trader") from exc

    @staticmethod
    def occupies_slot(trader: Trader) -> bool:
        return trader.status != TraderStatus.RETIRED

    def slot_count(self) -> int:
        return sum(self.occupies_slot(t) for t in self.traders.values())

    def active(self) -> list[Trader]:
        return [
            t
            for t in self.traders.values()
            if t.status == TraderStatus.ACTIVE
        ]

    def assign(
        self,
        trader_id: str,
        *,
        symbol: str,
        direction: str,
        strategy_id: str | None = None,
    ) -> Trader:
        trader = self.get(trader_id)
        if trader.status in {TraderStatus.HALTED, TraderStatus.RETIRED}:
            raise TraderRegistryError("trader_not_assignable")
        if direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        trader.market = symbol.upper()
        trader.direction = direction
        trader.strategy_id = strategy_id
        trader.status = TraderStatus.ACTIVE
        return trader

    def pause(self, trader_id: str) -> Trader:
        trader = self.get(trader_id)
        if trader.status != TraderStatus.ACTIVE:
            raise TraderRegistryError("trader_not_active")
        trader.status = TraderStatus.PAUSED
        return trader

    def resume(self, trader_id: str) -> Trader:
        trader = self.get(trader_id)
        if trader.status != TraderStatus.PAUSED:
            raise TraderRegistryError("trader_not_paused")
        trader.status = TraderStatus.ACTIVE
        return trader

    def halt(self, trader_id: str) -> Trader:
        trader = self.get(trader_id)
        if trader.status == TraderStatus.RETIRED:
            raise TraderRegistryError("trader_retired")
        trader.status = TraderStatus.HALTED
        return trader

    def retire(self, trader_id: str) -> Trader:
        trader = self.get(trader_id)
        if trader.status not in {
            TraderStatus.HALTED,
            TraderStatus.WAITING_ASSIGNMENT,
            TraderStatus.PAUSED,
            TraderStatus.EVALUATING,
        }:
            raise TraderRegistryError("trader_must_be_stopped_before_retirement")
        trader.status = TraderStatus.RETIRED
        trader.market = None
        trader.direction = None
        trader.strategy_id = None
        return trader

    def snapshot(self) -> dict:
        return {
            "slot_count": self.slot_count(),
            "traders": {
                trader_id: trader.to_dict()
                for trader_id, trader in self.traders.items()
            },
        }
