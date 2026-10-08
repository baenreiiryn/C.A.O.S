# News Intelligence — Whispering Tankard

Status: **IMPLEMENTED for v0.7.3 on `feature/news-intelligence`**

## Purpose

Give the standalone Trade Company continuously available market-news context without allowing news headlines to bypass deterministic strategy, risk or execution gates.

The flow is:

```text
Configured RSS / Atom sources
        |
        v
RSSNewsClient
        |
dedupe / timestamp / filtering
        |
        v
NewsAnalyzer
        |
ModernFinBERT when configured
or deterministic keyword fallback
        |
        v
CompanyNewsIntelligence
        |
        +--> opportunity score caution
        |
        +--> critical trusted negative news:
             block NEW risk for that symbol
        |
        +--> city / audit visibility
```

News can never directly place an order.

## Default source catalog

Fresh Windows installations start with these sources enabled:

| Source | Category | Type |
| --- | --- | --- |
| CoinDesk | crypto | editorial |
| Cointelegraph | crypto | editorial |
| Decrypt | crypto | editorial |
| CryptoSlate | crypto | editorial |
| Nasdaq Markets | stocks | editorial |
| Investing.com Market News | stocks | editorial |
| U.S. SEC Press Releases | regulation | official |
| Federal Reserve Press Releases | macro | official |
| Bank of Japan | macro-japan | official |

The catalog is versioned in:

```text
src/caos/news.py
```

and is represented as source records rather than scattered hardcoded UI strings.

## Installation and migration

The Windows launcher configuration now contains:

```json
{
  "news_sources": [
    {
      "id": "...",
      "name": "...",
      "category": "...",
      "url": "https://...",
      "kind": "official|editorial|custom",
      "enabled": true,
      "built_in": true
    }
  ]
}
```

A fresh installation receives the built-in catalog.

An older v0.7.2 `launcher.json` without `news_sources` receives the default catalog during normal configuration validation. Existing Treasury, Traders, research, rollout and execution-reliability state are unaffected.

Once a user saves a custom source list, that list is persisted and used instead of silently re-adding removed defaults.

## HTTPS-only source boundary

News source URLs must use HTTPS.

The URL validator rejects:

- HTTP;
- missing hosts;
- localhost;
- `.local` hosts;
- loopback literal IPs;
- private literal IPs;
- link-local literal IPs;
- reserved/multicast literal IPs.

The news tool is not exposed as an arbitrary URL fetcher to the LLM. URLs are persisted operator settings.

## Direct feed or normal site URL

Settings accepts:

1. a direct RSS/Atom feed URL; or
2. a normal HTTPS news-site URL.

For a normal site, **Discover & Add** attempts:

```text
HTML <link rel="alternate" type="application/rss+xml|application/atom+xml">
then common feed paths:
/feed
/rss
/rss.xml
/feed.xml
```

The discovered feed is tested before it is offered for persistence.

## Runtime Settings

The Arcane Trading City Settings page contains:

```text
🍺 Whispering Tankard · News Sources
```

Per source:

- enabled/disabled toggle;
- name;
- category;
- type;
- URL;
- Test;
- Remove.

Operator actions:

- Discover & Add;
- Test URL;
- Save Sources;
- Restore Defaults;
- Preview Latest.

Saving sources immediately replaces the live `NewsAnalyzer`; restarting the Trade Company is not required.

HTTP settings surfaces:

```text
POST /api/settings/news/save
POST /api/settings/news/discover
POST /api/settings/news/test
POST /api/settings/news/defaults
POST /api/settings/news/preview
```

These are configuration/read surfaces and expose no broker controls.

## Collection behavior

`RSSNewsClient`:

- reads only configured feeds;
- parses RSS 2.0 and Atom;
- normalizes publication timestamps;
- deduplicates by title/link;
- sorts newest first;
- supports query filtering;
- records per-feed failures without failing the complete collection.

A failing news feed therefore does not stop market refresh or the Company daemon.

## Sentiment

If the optional financial sentiment specialist is configured, NewsAnalyzer classifies:

```text
headline + bounded summary
```

and attaches a signed sentiment score.

If no specialist is configured, CompanyNewsIntelligence uses a small deterministic keyword fallback only for risk context.

The fallback is intentionally conservative and is not a trading strategy.

## Market relevance

CompanyNewsIntelligence maps headlines to symbols.

Current direct aliases include major crypto assets such as:

```text
BTC / Bitcoin
ETH / Ethereum / Ether
XRP / Ripple
SOL / Solana
BNB
DOGE / Dogecoin
ADA / Cardano
```

Other symbols fall back to their base asset token.

Macro terms such as Federal Reserve, FOMC, inflation, interest rates and Bank of Japan can create lower-strength broad context.

## Trust model

Built-in source URLs are recognized as trusted catalog sources.

User-added custom URLs are useful context but do **not** have the same authority.

A custom source can:

- appear in the Tavern;
- influence context;
- add a score penalty for negative relevant news;
- raise a warning.

A custom source alone cannot produce the hard critical-news new-risk block.

If a custom headline appears critical, it is capped at medium severity for automatic risk gating.

This prevents a random blog/feed added by the operator from becoming a direct risk-control oracle.

## Risk policy

News is asymmetric by design.

### Positive news

Positive news:

- never creates an opportunity;
- never creates an order;
- never raises requested exposure;
- never raises the maximum risk ceiling.

It is context only.

### Negative news

Direct relevant negative news may reduce opportunity score.

Current deterministic penalties:

```text
low negative context      -8 points
medium negative context  -20 points
trusted critical negative -40 points + block new risk
```

### Trusted critical negative news

Examples include direct asset headlines containing strong terms such as:

- hack/exploit/breach;
- withdrawals suspended;
- trading halt;
- insolvency/bankruptcy;
- delisting/ban;
- major attack/stolen funds.

When both direct relevance and trusted critical negative severity are present:

```text
block_new_risk = true
```

The daemon will not publish a new opportunity for that symbol.

For an already active Trader on the symbol, its paper cycle is called with:

```text
allow_new_risk = false
```

The V4 Execution Fabric still permits risk-reducing actions, so an existing position can reduce or close.

## Failure behavior

News failure is fail-open with visibility, not fail-closed trading paralysis.

If feeds are unavailable:

- the error is recorded;
- the Tavern shows attention;
- the daemon records `news:intelligence` / feed errors;
- C.A.O.S does not invent a negative headline;
- markets are not blocked merely because news collection failed.

This is deliberate: an RSS outage is not evidence of market danger.

## Cache

The Company news intelligence layer defaults to a five-minute refresh interval.

Repeated daemon cycles inside the interval use the cached context rather than hitting every source every minute.

The core market-price loop remains deterministic and does not require an LLM call each tick.

## Themed City

The **Whispering Tankard / Bard of Rumors** now displays:

- configured feed count;
- sentiment oracle status;
- markets under news ward;
- feed error count;
- last refresh;
- market-specific severity/sentiment/score penalty;
- whether new risk is blocked;
- latest collected dispatches;
- messenger/feed errors.

The Tavern explicitly states:

> News never creates an order.

## Company state

`TradeCompany.status()` includes:

```text
news_intelligence:
  version
  configured
  feeds
  last_refresh_ms
  contexts
  latest_items
  errors
  policy
```

`CompanyDaemonCycle` also includes the news snapshot.

Daemon audit events record:

- blocked symbols;
- news error count.

## Safety invariants

1. News cannot create an opportunity by itself.
2. News cannot create an order.
3. Positive news cannot increase exposure.
4. Critical negative news can only restrict new risk.
5. Existing risk-reducing exits remain available.
6. A custom feed cannot hard-block new risk by itself.
7. Feed failure does not fabricate a risk event.
8. News URLs remain operator-configured.
9. Broker credentials are unrelated to news collection.
10. LIVE remains unavailable.
