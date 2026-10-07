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

    def orderbook(
        self,
        symbol: str,
        limit: int = 50,
        category: str = "linear",
    ) -> dict:
        if category in {"linear", "inverse"} and not 1 <= limit <= 200:
            raise ValueError("linear/inverse orderbook limit must be between 1 and 200")
        if category == "spot" and not 1 <= limit <= 50:
            raise ValueError("spot orderbook limit must be between 1 and 50")
        payload = self._get_json(
            "/v5/market/orderbook",
            {
                "category": category,
                "symbol": symbol.upper(),
                "limit": limit,
            },
        )
        if payload.get("retCode") != 0:
            raise MarketDataError(str(payload.get("retMsg", "bybit error")))
        result = payload.get("result", {})
        return {
            "symbol": result.get("s", symbol.upper()),
            "bids": [[float(x[0]), float(x[1])] for x in result.get("b", [])],
            "asks": [[float(x[0]), float(x[1])] for x in result.get("a", [])],
            "ts": int(result.get("ts", payload.get("time", 0)) or 0),
        }

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
