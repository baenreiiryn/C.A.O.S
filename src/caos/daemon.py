from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .runner import PaperRunner


@dataclass(slots=True)
class DaemonCycle:
    refreshed: dict[str, int]
    actions: list[dict]
    skipped: list[dict]


class PaperDaemon:
    """Deterministic continuous paper loop."""

    def __init__(
        self,
        caos,
        interval: str = "60",
        candle_limit: int = 500,
    ):
        self.caos = caos
        self.interval = interval
        self.candle_limit = candle_limit

    def run_once(self) -> DaemonCycle:
        refreshed: dict[str, int] = {}
        symbols = sorted(
            {entry.symbol for entry in self.caos.portfolio}
        )
        for symbol in symbols:
            bars = self.caos.market_client.klines(
                symbol,
                self.interval,
                self.candle_limit,
                "linear",
            )
            self.caos.load_bars(symbol, bars)
            refreshed[symbol] = len(bars)
        result = PaperRunner(self.caos).cycle(
            self.caos.portfolio
        )
        return DaemonCycle(
            refreshed,
            result.actions,
            result.skipped,
        )

    def serve(
        self,
        every_seconds: float = 60.0,
        stop: Callable[[], bool] | None = None,
    ) -> None:
        if every_seconds < 1:
            raise ValueError(
                "every_seconds must be >= 1"
            )
        while True:
            if stop and stop():
                return
            self.run_once()
            time.sleep(every_seconds)
