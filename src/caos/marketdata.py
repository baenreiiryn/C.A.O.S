from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .domain import MarketBar


class MarketDataError(RuntimeError):
    pass


@dataclass(slots=True)
class BybitPublicClient:
    base_url: str = "https://api.bybit.com"
    timeout: float = 15.0

    def _get_json(self, path: str, params: dict[str, str | int]) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url.rstrip('/')}{path}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "caos/0.2"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise MarketDataError(str(exc)) from exc

    def klines(
        self,
        symbol: str,
        interval: str = "60",
        limit: int = 500,
        category: str = "linear",
    ) -> list[MarketBar]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        payload = self._get_json(
            "/v5/market/kline",
            {
                "category": category,
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
            },
        )
        if payload.get("retCode") != 0:
            raise MarketDataError(str(payload.get("retMsg", "bybit error")))
        rows = payload.get("result", {}).get("list", [])
        bars = [
            MarketBar(
                ts=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
        bars.sort(key=lambda b: b.ts)
        return bars
