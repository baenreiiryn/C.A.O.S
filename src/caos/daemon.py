from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .runner import PaperRunner
from .supervisor import audit_portfolio


@dataclass(slots=True)
class DaemonCycle:
    refreshed: dict[str, int]
    actions: list[dict]
    skipped: list[dict]
    errors: dict[str, str]
    supervisor: dict


class PaperDaemon:
    """Deterministic continuous paper loop with per-symbol fault isolation."""

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
        errors: dict[str, str] = {}
        symbols = sorted(
            {entry.symbol for entry in self.caos.portfolio}
        )
        for symbol in symbols:
            try:
                bars = self.caos.market_client.klines(
                    symbol,
                    self.interval,
                    self.candle_limit,
                    "linear",
                )
                if not bars:
                    raise RuntimeError("empty_market_data")
                self.caos.load_bars(symbol, bars)
                refreshed[symbol] = len(bars)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"

        safe_portfolio = [
            entry
            for entry in self.caos.portfolio
            if entry.symbol not in errors
        ]
        result = PaperRunner(self.caos).cycle(safe_portfolio)
        supervisor = audit_portfolio(self.caos)
        self.caos.checkpoint()

        if self.caos.store is not None:
            self.caos.store.event(
                "daemon_cycle",
                {
                    "refreshed": refreshed,
                    "actions": len(result.actions),
                    "skipped": len(result.skipped),
                    "errors": errors,
                    "supervisor_status": supervisor["status"],
                },
            )

        return DaemonCycle(
            refreshed=refreshed,
            actions=result.actions,
            skipped=result.skipped,
            errors=errors,
            supervisor=supervisor,
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
