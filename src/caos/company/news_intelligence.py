from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..news import DEFAULT_NEWS_SOURCES


NEWS_INTELLIGENCE_VERSION = "news-intelligence/v1"

_CRYPTO_ALIASES = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "ether", "eth"),
    "XRP": ("xrp", "ripple"),
    "SOL": ("solana", "sol"),
    "BNB": ("bnb", "binance coin"),
    "DOGE": ("dogecoin", "doge"),
    "ADA": ("cardano", "ada"),
}
_NEGATIVE_HIGH = (
    "hack",
    "hacked",
    "exploit",
    "breach",
    "bankrupt",
    "insolven",
    "suspend withdrawals",
    "withdrawals suspended",
    "trading halt",
    "halt trading",
    "delist",
    "ban ",
    "fraud",
    "attack",
    "outage",
    "stolen",
)
_NEGATIVE_MEDIUM = (
    "lawsuit",
    "charges",
    "charged",
    "investigation",
    "probe",
    "warning",
    "selloff",
    "plunge",
    "crash",
    "outflow",
    "liquidation",
)
_POSITIVE = (
    "approved",
    "approval",
    "record inflow",
    "inflows",
    "launch",
    "adoption",
    "partnership",
    "surge",
    "rally",
)
_MACRO = (
    "federal reserve",
    "fomc",
    "interest rate",
    "inflation",
    "bank of japan",
    "boj",
    "monetary policy",
    "treasury yield",
)

_TRUSTED_SOURCE_KIND = {
    str(row["url"]): str(row["kind"])
    for row in DEFAULT_NEWS_SOURCES
}



@dataclass(slots=True)
class NewsContext:
    symbol: str
    relevance: float = 0.0
    sentiment: float = 0.0
    severity: str = "none"
    block_new_risk: bool = False
    score_penalty: float = 0.0
    headlines: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class CompanyNewsIntelligence:
    """Deterministic news context for Company risk gating.

    News never creates an opportunity or order. Negative, directly relevant
    high-severity news may block only new risk; risk-reducing exits remain
    available through the existing Execution Fabric.
    """

    def __init__(
        self,
        caos,
        *,
        poll_interval_ms: int = 300_000,
        item_limit: int = 80,
    ):
        self.caos = caos
        self.poll_interval_ms = int(poll_interval_ms)
        self.item_limit = int(item_limit)
        self.last_refresh_ms: int | None = None
        self.contexts: dict[str, NewsContext] = {}
        self.last_items: list[dict] = []
        self.last_errors: list[str] = []

    @staticmethod
    def _base_asset(symbol: str) -> str:
        value = str(symbol).upper()
        for suffix in (
            "USDT",
            "USDC",
            "USD",
            "JPY",
            "EUR",
            "BTC",
            "ETH",
        ):
            if value.endswith(suffix) and len(value) > len(suffix):
                return value[: -len(suffix)]
        return value

    @classmethod
    def _relevance(
        cls,
        symbol: str,
        text: str,
    ) -> tuple[float, bool]:
        base = cls._base_asset(symbol)
        lowered = text.lower()
        direct = False
        aliases = _CRYPTO_ALIASES.get(
            base,
            (base.lower(),),
        )
        for alias in aliases:
            if len(alias) <= 3:
                if re.search(
                    r"(?<![a-z0-9])"
                    + re.escape(alias.lower())
                    + r"(?![a-z0-9])",
                    lowered,
                ):
                    direct = True
                    break
            elif alias.lower() in lowered:
                direct = True
                break
        if direct:
            return 1.0, True
        if any(term in lowered for term in _MACRO):
            return 0.35, False
        return 0.0, False

    @staticmethod
    def _sentiment(item: dict, text: str) -> float:
        raw = item.get("sentiment")
        if isinstance(raw, dict):
            try:
                return max(
                    -1.0,
                    min(
                        1.0,
                        float(raw["signed_score"]),
                    ),
                )
            except (KeyError, TypeError, ValueError):
                pass
        lowered = text.lower()
        negative = sum(
            term in lowered
            for term in (
                *_NEGATIVE_HIGH,
                *_NEGATIVE_MEDIUM,
            )
        )
        positive = sum(
            term in lowered
            for term in _POSITIVE
        )
        if negative > positive:
            return -0.6
        if positive > negative:
            return 0.4
        return 0.0

    @staticmethod
    def _severity(
        text: str,
        sentiment: float,
        direct: bool,
    ) -> str:
        lowered = text.lower()
        if direct and any(
            term in lowered
            for term in _NEGATIVE_HIGH
        ):
            return "high"
        if direct and (
            sentiment <= -0.45
            or any(
                term in lowered
                for term in _NEGATIVE_MEDIUM
            )
        ):
            return "medium"
        if direct or any(
            term in lowered
            for term in _MACRO
        ):
            return "low"
        return "none"

    def refresh(
        self,
        symbols,
        *,
        now: int,
        force: bool = False,
    ) -> dict:
        analyzer = getattr(
            self.caos,
            "news_analyzer",
            None,
        )
        normalized = sorted(
            {str(symbol).upper() for symbol in symbols}
        )
        if analyzer is None:
            self.contexts = {
                symbol: NewsContext(symbol)
                for symbol in normalized
            }
            self.last_items = []
            self.last_errors = []
            self.last_refresh_ms = now
            return self.snapshot()

        if (
            not force
            and self.last_refresh_ms is not None
            and now - self.last_refresh_ms
            < self.poll_interval_ms
        ):
            for symbol in normalized:
                self.contexts.setdefault(
                    symbol,
                    NewsContext(symbol),
                )
            return self.snapshot()

        result = analyzer.latest(
            limit=self.item_limit,
            with_sentiment=True,
        )
        items = list(result.get("items", []))
        contexts: dict[str, NewsContext] = {
            symbol: NewsContext(symbol)
            for symbol in normalized
        }
        for item in items:
            text = (
                str(item.get("title", ""))
                + " "
                + str(item.get("summary", ""))
            ).strip()
            for symbol in normalized:
                relevance, direct = self._relevance(
                    symbol,
                    text,
                )
                if relevance <= 0:
                    continue
                sentiment = self._sentiment(
                    item,
                    text,
                )
                severity = self._severity(
                    text,
                    sentiment,
                    direct,
                )
                source_url = str(
                    item.get("source", "")
                )
                source_kind = (
                    _TRUSTED_SOURCE_KIND.get(
                        source_url
                    )
                )
                trusted_source = (
                    source_kind is not None
                )
                if (
                    severity == "high"
                    and not trusted_source
                ):
                    severity = "medium"
                ctx = contexts[symbol]
                ctx.relevance = max(
                    ctx.relevance,
                    relevance,
                )
                if abs(sentiment) > abs(ctx.sentiment):
                    ctx.sentiment = sentiment
                rank = {
                    "none": 0,
                    "low": 1,
                    "medium": 2,
                    "high": 3,
                }
                if rank[severity] > rank[ctx.severity]:
                    ctx.severity = severity
                if severity == "high" and sentiment < 0:
                    ctx.block_new_risk = True
                    ctx.score_penalty = max(
                        ctx.score_penalty,
                        40.0,
                    )
                elif severity == "medium" and sentiment < 0:
                    ctx.score_penalty = max(
                        ctx.score_penalty,
                        20.0,
                    )
                elif sentiment < 0:
                    ctx.score_penalty = max(
                        ctx.score_penalty,
                        8.0,
                    )
                ctx.headlines.append(
                    {
                        "title": item.get("title"),
                        "link": item.get("link"),
                        "published": item.get("published"),
                        "source": item.get("source"),
                        "sentiment": sentiment,
                        "severity": severity,
                        "direct": direct,
                        "trusted_source": trusted_source,
                        "source_kind": (
                            source_kind or "custom"
                        ),
                    }
                )
                ctx.headlines = ctx.headlines[:8]

        self.contexts = contexts
        self.last_items = items[:20]
        self.last_errors = list(
            result.get("errors", [])
        )
        self.last_refresh_ms = now
        return self.snapshot()

    def context_for(self, symbol: str) -> dict:
        ctx = self.contexts.get(
            str(symbol).upper()
        )
        return (
            ctx.to_dict()
            if ctx is not None
            else NewsContext(
                str(symbol).upper()
            ).to_dict()
        )

    def snapshot(self) -> dict:
        analyzer = getattr(
            self.caos,
            "news_analyzer",
            None,
        )
        return {
            "version": NEWS_INTELLIGENCE_VERSION,
            "configured": analyzer is not None,
            "feeds": (
                len(analyzer.client.feed_urls)
                if analyzer is not None
                else 0
            ),
            "last_refresh_ms": self.last_refresh_ms,
            "contexts": {
                symbol: ctx.to_dict()
                for symbol, ctx in self.contexts.items()
            },
            "latest_items": list(self.last_items),
            "errors": list(self.last_errors),
            "policy": {
                "news_can_create_trades": False,
                "positive_news_can_increase_risk": False,
                "critical_negative_news_blocks_new_risk": True,
                "custom_source_can_block_new_risk_alone": False,
                "risk_reducing_actions_remain_allowed": True,
            },
        }
