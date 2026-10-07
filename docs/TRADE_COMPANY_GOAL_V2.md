# Trade Company Goal V2 — autonomous operating company

Status: **IN DEVELOPMENT on `feature/trade-company`**.

This Goal turns the already-created Trade Company architecture into an operating, recoverable Company that continuously coordinates independent Trader workers through the shared C.A.O.S engine.

Nothing in this Goal is merged to `main` until the full C.A.O.S + Trade Company test suite is green and the merge gate below is reviewed.

## Goal

Make the Trade Company capable of running standalone without Drizzt while preserving a stable future integration boundary:

```text
future Drizzt
     |
CompanyControlPort
     |
Trade Company
     |
C.A.O.S
     |
Broker
```

Drizzt remains optional. The Company must recover and continue operating without Drizzt.

## Scope

### Persistent Company state

Checkpoint and restore:

- immutable CompanyPolicy validation;
- effective operational Trader limit;
- Treasury balances and append-only ledger;
- Trader Registry and lifecycle state;
- Opportunity Registry and TTL state;
- Market reservations/assignments;
- registered deterministic strategies;
- Company Risk state;
- Training experiments;
- per-Trader paper accounts, positions, fills and risk state.

Restore must fail closed when Company state is internally inconsistent.

### Per-Trader paper accounts

Each Trader gets an isolated paper subaccount while sharing the same C.A.O.S analytical engine.

The Company must preserve:

```text
shared:
  C.A.O.S market data
  deterministic quant code
  execution-cost model
  specialist evidence

isolated:
  Trader capital bucket
  positions
  fills
  strategy assignment
  performance
  lifecycle
```

Paper realized equity must reconcile with the corresponding Treasury bucket. Unrealized marked equity is used for live risk calculations without rewriting the realized Treasury ledger.

### Company daemon

One deterministic loop must:

1. expire stale opportunities;
2. refresh required markets with per-symbol fault isolation;
3. run Market Scout over configured scan targets;
4. publish expiring opportunities;
5. assign funded waiting Traders only to opportunities with registered strategies;
6. run isolated paper cycles for ACTIVE Traders;
7. flatten and retire a Trader if marked equity breaches the stop floor;
8. evaluate expansion only when Treasury funding, operational capacity, strategy and opportunity are all valid;
9. preserve production market exclusivity;
10. track Company-wide exposure and reconciliation;
11. run Supervisor audit;
12. save a Company checkpoint.

The daemon does not call an LLM on every market tick.

### Expansion safety

Spawn is Treasury-first. A new Trader is created only when Treasury can provide the configured minimum initial bucket and the operational Trader cap has room.

If Treasury already has enough capital, another Trader may be created without reducing an existing Trader, even while that existing Trader has an open position.

If Treasury is short, the Capital Allocator may harvest only the missing amount from capital above an eligible Trader's minimum operating bucket. In that case the contributing Trader must be flat and reconciled first.

```text
Case A — Treasury already funded

Treasury Reserve = 10
Trader A = 10, position may be open
        |
        v
Trader B receives 10
A is untouched

Case B — Treasury needs capital

Treasury Reserve = 0
Trader A = 20 and flat
        |
        v
10 harvested to Treasury
        |
        v
Trader B receives 10
Trader A remains 10
```

A failed assignment must rollback without losing Company capital. `spawned_from` is analytics-only and is not set merely because a Trader happened to be the first active worker when Treasury independently funded a spawn.


### Two independent limits

The Company must never conflate trade risk with runtime concurrency.

```text
Financial limit per Trader
  maxTradeNotional =
      currentTraderEquity * trader.maxTradeExposurePct

Example:
  A equity 10, max 20% -> ceiling 2
  A equity 20, max 20% -> ceiling 4
  A falls back to 10 -> ceiling 2

Requested trade sizing may be lower than the ceiling.

Operational concurrency limit
  operationalTraderCap = 6 by default

This cap exists to protect CPU/GPU/RAM/latency and may be configured separately from capital. Having enough Treasury capital does not permit the Company to exceed the operational cap.
```

### Stop-floor safety

If marked Trader equity falls below the configured floor:

```text
marked equity < 3
      |
force risk-reducing flatten
      |
reconcile realized paper equity
      |
retire Trader
      |
residual -> Treasury Reserve
```

The market reservation is retained until the position is actually flat.

### Company-wide risk visibility

The Company Risk Governor uses marked Trader equity for per-trade limits and marked Company equity for Company drawdown. Each Trader owns an independent maximum exposure percentage. A Trader or sizing policy may request less than that maximum.

Supervisor must expose:

- gross open notional;
- exposure by Trader;
- exposure by symbol;
- paper/Treasury reconciliation mismatches;
- Company drawdown;
- C.A.O.S health/kill state.

No new Company-wide leverage/concentration limit is invented in this Goal; undefined risk policy remains observable rather than silently fabricated.

### Strategy registry

Operational Traders may only be auto-assigned an opportunity when at least one strategy candidate is registered with the Company.

Training remains capable of comparing deterministic C.A.O.S StrategySpec variants on identical data.

### Future Drizzt seam

CompanyControlPort remains the only intended future Drizzt control surface.

It must not expose:

- broker credentials;
- raw broker order placement;
- LIVE arming bypass;
- kill-switch reset bypass.

## Current execution limitation

C.A.O.S paper execution is currently long/flat. The Company may register and rank short opportunities, but autonomous short paper execution must fail closed until the underlying C.A.O.S execution engine gains tested short-position support.

This limitation must not be hidden by implementing a separate unvalidated short engine inside the Company.

## Acceptance criteria

Goal V2 is complete when:

1. full existing C.A.O.S regression suite remains green;
2. Company checkpoint round-trip restores Treasury, Traders, opportunities, assignments, strategies and paper positions;
3. corrupted reconciliation or reservation state fails restore;
4. daemon market failures are isolated by symbol;
5. daemon Trader execution failures are isolated by Trader;
6. Opportunity TTL expiration is deterministic;
7. waiting Traders are assigned only to registered strategies;
8. production symbol exclusivity survives daemon operation;
9. per-Trader paper positions remain isolated;
10. paper realized equity reconciles into Treasury exactly once;
11. Company risk uses marked current Trader equity and that Trader's configured exposure ceiling;
12. Company drawdown can reflect unrealized paper losses;
13. stop-floor forces flatten before retirement and returns residual to Treasury;
14. a Trader is required to be flat only when its capital must be harvested to fund a spawn;
15. expansion rollback preserves total Company equity;
16. the configurable operational Trader cap is enforced independently from available capital;
17. restart/recovery can continue a previously open paper position;
18. Company Supervisor exposes exposure and reconciliation health;
19. CompanyControlPort still has no broker credential/raw-order/LIVE bypass;
20. CI and CLI smoke are green on the feature branch;
21. no merge to `main` occurs until explicit final review.

## Non-goals

- claiming strategy profitability;
- enabling production LIVE;
- bypassing C.A.O.S Risk/Compliance;
- adding autonomous short execution before C.A.O.S supports it;
- requiring Drizzt;
- loading one C.A.O.S/LLM stack per Trader;
- automatically promoting Kronos/Chronos before real machine benchmarks.
