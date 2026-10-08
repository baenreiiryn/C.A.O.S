from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .domain import MarketBar


class MarketDataError(RuntimeError):
    pass


_INTERVALS = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "120": "2h",
    "240": "4h",
    "360": "6h",
    "720": "12h",
    "D": "1d",
    "W": "1w",
    "M": "1M",
}
_BINANCE_INTERVALS = {
    "1s",
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}
_DEPTH_LIMITS = {5, 10, 20, 50, 100, 500, 1000, 5000}


@dataclass(slots=True)
class BinancePublicClient:
    """Public Binance Spot market-data client.

    No API key is required. The same public endpoints are used by the
    standalone Trade Company for candles and order-book cost estimation.
    """

    base_url: str = "https://api.binance.com"
    timeout: float = 15.0

    def _get_json(
        self,
        path: str,
        params: dict[str, str | int],
    ):
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            url += "?" + query
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "caos/0.7.2",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                req,
                timeout=self.timeout,
            ) as resp:
                return json.loads(
                    resp.read().decode("utf-8")
                )
        except Exception as exc:
            raise MarketDataError(str(exc)) from exc

    @staticmethod
    def normalize_interval(interval: str) -> str:
        raw = str(interval)
        if raw in _BINANCE_INTERVALS:
            return raw
        if raw in _INTERVALS:
            return _INTERVALS[raw]
        upper = raw.upper()
        if upper in _INTERVALS:
            return _INTERVALS[upper]
        raise ValueError(
            f"unsupported Binance interval: {interval}"
        )

    def orderbook(
        self,
        symbol: str,
        limit: int = 50,
        category: str = "spot",
    ) -> dict:
        del category
        limit = int(limit)
        if limit not in _DEPTH_LIMITS:
            raise ValueError(
                "Binance depth limit must be one of "
                "5,10,20,50,100,500,1000,5000"
            )
        payload = self._get_json(
            "/api/v3/depth",
            {
                "symbol": symbol.upper(),
                "limit": limit,
            },
        )
        return {
            "symbol": symbol.upper(),
            "bids": [
                [float(x[0]), float(x[1])]
                for x in payload.get("bids", [])
            ],
            "asks": [
                [float(x[0]), float(x[1])]
                for x in payload.get("asks", [])
            ],
            "ts": int(time.time() * 1000),
            "last_update_id": int(
                payload.get("lastUpdateId", 0) or 0
            ),
        }

    def klines(
        self,
        symbol: str,
        interval: str = "60",
        limit: int = 500,
        category: str = "spot",
    ) -> list[MarketBar]:
        del category
        limit = int(limit)
        if not 1 <= limit <= 1000:
            raise ValueError(
                "Binance kline limit must be between 1 and 1000"
            )
        payload = self._get_json(
            "/api/v3/klines",
            {
                "symbol": symbol.upper(),
                "interval": self.normalize_interval(interval),
                "limit": limit,
            },
        )
        if not isinstance(payload, list):
            raise MarketDataError(
                "unexpected_binance_kline_response"
            )
        return [
            MarketBar(
                ts=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in payload
        ]
