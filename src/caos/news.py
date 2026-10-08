from __future__ import annotations

import html
import ipaddress
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


DEFAULT_NEWS_SOURCES = (
    {
        "id": "coindesk",
        "name": "CoinDesk",
        "category": "crypto",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "kind": "editorial",
    },
    {
        "id": "cointelegraph",
        "name": "Cointelegraph",
        "category": "crypto",
        "url": "https://cointelegraph.com/rss",
        "kind": "editorial",
    },
    {
        "id": "decrypt",
        "name": "Decrypt",
        "category": "crypto",
        "url": "https://decrypt.co/feed",
        "kind": "editorial",
    },
    {
        "id": "cryptoslate",
        "name": "CryptoSlate",
        "category": "crypto",
        "url": "https://cryptoslate.com/feed/",
        "kind": "editorial",
    },
    {
        "id": "nasdaq-markets",
        "name": "Nasdaq Markets",
        "category": "stocks",
        "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
        "kind": "editorial",
    },
    {
        "id": "investing-markets",
        "name": "Investing.com Market News",
        "category": "stocks",
        "url": "https://www.investing.com/rss/news_25.rss",
        "kind": "editorial",
    },
    {
        "id": "sec-press",
        "name": "U.S. SEC Press Releases",
        "category": "regulation",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "kind": "official",
    },
    {
        "id": "fed-press",
        "name": "Federal Reserve Press Releases",
        "category": "macro",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "kind": "official",
    },
    {
        "id": "boj-news",
        "name": "Bank of Japan",
        "category": "macro-japan",
        "url": "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "kind": "official",
    },
)


def default_news_sources() -> list[dict]:
    return [
        {**row, "enabled": True, "built_in": True}
        for row in DEFAULT_NEWS_SOURCES
    ]


def validate_news_url(value: str) -> str:
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("news_url_must_use_https")
    if not parsed.hostname:
        raise ValueError("news_url_host_required")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("private_news_host_forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise ValueError("private_news_host_forbidden")
    return url


def normalize_news_sources(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("news_sources_must_be_list")
    result: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        url = validate_news_url(row.get("url", ""))
        if url in seen:
            continue
        seen.add(url)
        source_id = str(
            row.get("id", f"custom-{index + 1}")
        ).strip() or f"custom-{index + 1}"
        result.append(
            {
                "id": source_id[:100],
                "name": (
                    str(row.get("name", "")).strip()
                    or urlparse(url).hostname
                    or source_id
                )[:160],
                "category": (
                    str(row.get("category", "custom")).strip()
                    or "custom"
                )[:80],
                "url": url,
                "kind": (
                    str(row.get("kind", "custom")).strip()
                    or "custom"
                )[:40],
                "enabled": bool(row.get("enabled", True)),
                "built_in": bool(row.get("built_in", False)),
            }
        )
    return result


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


class _FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        data = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        rel = data.get("rel", "").lower()
        typ = data.get("type", "").lower()
        href = data.get("href", "").strip()
        if (
            href
            and "alternate" in rel
            and typ in {
                "application/rss+xml",
                "application/atom+xml",
                "application/feed+json",
            }
        ):
            self.links.append(href)


class RSSNewsClient:
    """Fetch only human-configured RSS/Atom feeds."""

    def __init__(
        self,
        feed_urls: list[str] | tuple[str, ...],
        timeout: float = 10.0,
        user_agent: str = "caos-news/0.7.3",
    ):
        self.feed_urls = []
        seen = set()
        for raw in feed_urls:
            if not str(raw).strip():
                continue
            url = validate_news_url(str(raw))
            if url not in seen:
                seen.add(url)
                self.feed_urls.append(url)
        self.timeout = timeout
        self.user_agent = user_agent
        self.last_errors: list[str] = []

    def _request(self, url: str):
        url = validate_news_url(url)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": (
                    "application/rss+xml, application/atom+xml, "
                    "application/xml, text/xml, text/html;q=0.8"
                ),
            },
        )
        return urllib.request.urlopen(
            req,
            timeout=self.timeout,
        )

    def _get(self, url: str) -> bytes:
        with self._request(url) as resp:
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

    def test_feed(self, url: str) -> dict:
        url = validate_news_url(url)
        try:
            items = self._parse(url, self._get(url))
        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "ok": bool(items),
            "url": url,
            "count": len(items),
            "sample": [
                {
                    "title": item.title,
                    "published": item.published,
                }
                for item in items[:3]
            ],
            "error": None if items else "feed_has_no_items",
        }

    def discover_feed(self, site_url: str) -> dict:
        site_url = validate_news_url(site_url)
        candidates: list[str] = []
        try:
            with self._request(site_url) as resp:
                payload = resp.read()
                final_url = validate_news_url(resp.geturl())
                content_type = (
                    resp.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
            if (
                "xml" in content_type
                or "rss" in content_type
                or "atom" in content_type
            ):
                tested = self.test_feed(final_url)
                if tested["ok"]:
                    return {
                        "ok": True,
                        "site_url": site_url,
                        "feed_url": final_url,
                        "method": "direct",
                        "sample": tested["sample"],
                    }
            parser = _FeedLinkParser()
            try:
                parser.feed(payload.decode("utf-8", "replace"))
            except Exception:
                pass
            candidates.extend(
                urljoin(final_url, href)
                for href in parser.links
            )
        except Exception as exc:
            direct_error = f"{type(exc).__name__}: {exc}"
        else:
            direct_error = None

        root = site_url.rstrip("/")
        candidates.extend(
            [
                root + "/feed",
                root + "/rss",
                root + "/rss.xml",
                root + "/feed.xml",
            ]
        )
        seen: set[str] = set()
        for candidate in candidates:
            try:
                candidate = validate_news_url(candidate)
            except ValueError:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            tested = self.test_feed(candidate)
            if tested["ok"]:
                return {
                    "ok": True,
                    "site_url": site_url,
                    "feed_url": candidate,
                    "method": "discovered",
                    "sample": tested["sample"],
                }
        return {
            "ok": False,
            "site_url": site_url,
            "feed_url": None,
            "method": None,
            "error": direct_error or "rss_or_atom_feed_not_found",
        }

    def latest(
        self,
        limit: int = 20,
        query: str | None = None,
    ) -> list[NewsItem]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not self.feed_urls:
            self.last_errors = []
            return []

        items: list[NewsItem] = []
        errors: list[str] = []
        for url in self.feed_urls:
            try:
                items.extend(
                    self._parse(url, self._get(url))
                )
            except Exception as exc:
                errors.append(
                    f"{url}: {type(exc).__name__}: {exc}"
                )
        self.last_errors = errors

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
                    item.sentiment = (
                        self.sentiment_expert
                        .classify(text)
                        .to_dict()
                    )
                except Exception as exc:
                    item.sentiment = {
                        "error": (
                            f"{type(exc).__name__}: {exc}"
                        )
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
            "errors": list(self.client.last_errors),
        }
