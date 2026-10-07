from __future__ import annotations

import html
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime


@dataclass(slots=True)
class NewsItem:
    title: str
    link: str
    published: str | None
    summary: str
    source: str
    sentiment: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RSSNewsClient:
    """Fetch only user-configured RSS/Atom feeds.

    URLs are configured outside the LLM tool call, preventing the orchestrator from
    turning this client into an arbitrary URL fetcher.
    """

    def __init__(
        self,
        feed_urls: list[str] | tuple[str, ...],
        timeout: float = 10.0,
        user_agent: str = "caos-news/0.5",
    ):
        self.feed_urls = [u.strip() for u in feed_urls if u.strip()]
        self.timeout = timeout
        self.user_agent = user_agent

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    @staticmethod
    def _text(node, *names: str) -> str:
        for name in names:
            found = node.find(name)
            if found is not None and found.text:
                return html.unescape(found.text.strip())
        return ""

    @staticmethod
    def _published(value: str) -> str | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).isoformat()
        except Exception:
            return value

    def _parse(self, url: str, payload: bytes) -> list[NewsItem]:
        root = ET.fromstring(payload)
        items: list[NewsItem] = []

        # RSS 2.0
        for node in root.findall(".//item"):
            title = self._text(node, "title")
            link = self._text(node, "link")
            summary = self._text(node, "description", "summary")
            published = self._published(
                self._text(node, "pubDate", "published", "updated")
            )
            if title:
                items.append(
                    NewsItem(
                        title=title,
                        link=link,
                        published=published,
                        summary=summary,
                        source=url,
                    )
                )

        # Atom (namespaced or plain)
        if not items:
            for node in root.findall(".//{*}entry"):
                title = self._text(node, "{*}title", "title")
                summary = self._text(
                    node,
                    "{*}summary",
                    "{*}content",
                    "summary",
                )
                published = self._published(
                    self._text(
                        node,
                        "{*}published",
                        "{*}updated",
                        "published",
                        "updated",
                    )
                )
                link = ""
                link_node = node.find("{*}link")
                if link_node is not None:
                    link = link_node.attrib.get("href", "") or (
                        link_node.text or ""
                    )
                if title:
                    items.append(
                        NewsItem(
                            title=title,
                            link=link.strip(),
                            published=published,
                            summary=summary,
                            source=url,
                        )
                    )

        return items

    def latest(
        self,
        limit: int = 20,
        query: str | None = None,
    ) -> list[NewsItem]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not self.feed_urls:
            return []

        items: list[NewsItem] = []
        errors: list[str] = []
        for url in self.feed_urls:
            try:
                items.extend(self._parse(url, self._get(url)))
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")

        if query:
            q = query.lower()
            items = [
                item
                for item in items
                if q in item.title.lower()
                or q in item.summary.lower()
            ]

        seen: set[tuple[str, str]] = set()
        deduped: list[NewsItem] = []
        for item in items:
            key = (item.title, item.link)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        # ISO/RFC timestamps generally sort adequately after normalization. Unknown
        # timestamps remain stable at the end.
        deduped.sort(
            key=lambda x: x.published or "",
            reverse=True,
        )
        return deduped[:limit]


class NewsAnalyzer:
    def __init__(self, client: RSSNewsClient, sentiment_expert=None):
        self.client = client
        self.sentiment_expert = sentiment_expert

    def latest(
        self,
        limit: int = 20,
        query: str | None = None,
        with_sentiment: bool = True,
    ) -> dict:
        items = self.client.latest(limit=limit, query=query)
        for item in items:
            if with_sentiment and self.sentiment_expert is not None:
                text = item.title
                if item.summary:
                    text += ". " + item.summary[:1000]
                try:
                    item.sentiment = self.sentiment_expert.classify(text).to_dict()
                except Exception as exc:
                    item.sentiment = {
                        "error": f"{type(exc).__name__}: {exc}"
                    }

        signed = [
            float(item.sentiment["signed_score"])
            for item in items
            if item.sentiment
            and "signed_score" in item.sentiment
        ]
        aggregate = (
            sum(signed) / len(signed)
            if signed
            else None
        )
        return {
            "items": [item.to_dict() for item in items],
            "count": len(items),
            "aggregate_sentiment": aggregate,
        }
