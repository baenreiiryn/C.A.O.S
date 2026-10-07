# C.A.O.S Trade Company architecture

## Core rule

**Company capital belongs to the Trade Company Treasury, never to a Trader and never to a parent-child tree.**

Traders receive independent operating buckets from the Treasury/Capital Allocator. A Trader can be created, halted, retired or replaced without breaking ownership or routing of capital.

A field such as `spawnedFrom` may exist only for genealogy, experiment analysis and attribution. It must never define who owns the money or where residual capital is returned.

## Company topology

```text
                       TRADE COMPANY
                               |
                    +----------+----------+
                    |                     |
                 Treasury              Supervisor
                    |                     |
             Capital Allocator        Oversight
                    |                     |
                    |              Improvement Manager
                    |
          +---------+---------+
          |                   |
     Market Scout       Market Regime
          |
 Opportunity Registry
          |
     Market Allocator
          |
 +--------+--------+--------+--------+
 |        |        |        |        |
 v        v        v        v        v
Trader A Trader B Trader C Trader D ...
 |        |        |        |
Strategy Strategy Strategy Strategy
 |        |        |        |
 +--------+----+---+--------+
              |
      Company Risk Governor
              |
       Strategy Diversity
              |
          Risk Engine
              |
            Broker
```

## Treasury and Capital Allocator

The Treasury owns the official Company equity.

The Capital Allocator is the only component allowed to move capital between:

- Treasury Reserve;
- Trader operating buckets;
- training/experiment budgets;
- other explicitly authorized Company buckets.

The Ledger/Treasury is the source of truth for capital, realized PnL, fees, positions and transfers.

### Example

Company starts with 10 USD:

```text
Treasury equity: 10
Reserve: 0
Trader A bucket: 10
```

If A grows to 20 USD and spawn conditions are satisfied:

```text
Before:
Trader A: 20

Capital Allocator:
- keeps 10 with A
- allocates 10 to new Trader B

After:
Trader A: 10
Trader B: 10
Company equity: 20
```

This is **not** A giving money to a child. The Treasury records a Company allocation event.

If A later exits, B is unaffected.

## Trader lifecycle

Suggested states:

```text
CANDIDATE
  -> ACTIVE
  -> PAUSED
  -> EVALUATING
  -> RETIRED

ACTIVE
  -> HALTED  (risk/stop-floor/failure)
```

A Trader does not own descendants.

A Trader record may contain:

```text
trader_id
spawned_from        # analytics only
generation          # analytics only
status
mode                 # PRODUCTION / TRAINING / PAPER
bucket_equity
strategy_id
market
direction
performance
created_at
retired_at
```

`spawned_from` must never be consulted for capital settlement.

## Stop floor and retirement

If a Trader falls below the configured stop floor (example: 3 USD):

```text
Trader equity < 3
       |
       v
     HALTED
       |
       v
close/reconcile positions
       |
       v
residual bucket
       |
       v
Treasury Reserve
```

The residual capital does **not** return to the Trader that triggered its creation.

The Company may later create a replacement Trader if:

- Treasury has enough allocatable capital;
- a slot is available;
- Risk/Policy allow it;
- the Market Allocator has a valid opportunity.

## Spawn policy

Example policy retained from the Drizzt Trade Company design:

```text
spawnThreshold = 20 USD
newTraderInitialBucket = 10 USD
hardMaxActiveTraders = 6
```

When one Trader reaches the threshold, that is merely a **trigger condition** for the Capital Allocator to consider creating another Trader.

The Trader that reached the threshold is not the owner of the new Trader.

The allocator must verify Company-wide constraints before spawning:

```text
company equity
treasury reserve
active trader count
effective max traders
market availability
risk state
diversity
training/production mode
```

`hardMaxActiveTraders` is user-authorized policy and cannot be increased by an agent.

## Market Scout and Opportunity Registry

Market Scout continuously ranks potential opportunities.

Market Regime provides regime context.

Opportunity Registry stores normalized candidates such as:

```text
opportunity_id
symbol
direction
regime
quant_score
forecast_score
news_context
estimated_cost
liquidity
risk_score
status
reserved_by
mode
expires_at
```

## Market Allocator

Production and training use different occupancy rules.

### PRODUCTION

An occupied market/setup cannot be duplicated according to Company policy.

Example:

```text
BTCUSDT LONG -> Trader A

Trader B requests BTCUSDT LONG
-> DENY / allocate another opportunity
```

### TRAINING

Multiple Traders may deliberately use the same market with different strategies or model stacks:

```text
BTCUSDT
  A -> momentum
  B -> breakout
  C -> mean reversion
  D -> momentum + Kronos
  E -> momentum + Chronos
  F -> Kronos + Chronos filter
```

This is an experiment, not an ownership conflict.

## Company Risk Governor

The Company Risk Governor acts above per-Trader Risk Engines.

Order path:

```text
Trader proposal
     |
Policy / Mandate
     |
Capital Ledger / Treasury
     |
Company Risk Governor
     |
Strategy Diversity
     |
Trader Risk Engine
     |
ALLOW / DENY
     |
Broker
```

Per-trade exposure is calculated from the **current Trader bucket equity**, not initial capital and not a high-water mark:

```text
max_notional = currentTraderEquity * maxTradePercent
```

## Supervisor and Improvement Manager

Supervisor observes Company-wide health:

- trader performance;
- risk events;
- strategy degradation;
- expected vs realized divergence;
- stale data;
- execution faults;
- capital concentration;
- model qualification.

Improvement Manager proposes changes such as:

- replace a weak strategy;
- run a new training experiment;
- compare Kronos/Chronos filters;
- retire a degraded Trader;
- recommend a new effective active-Trader count;
- suggest code/model improvements.

It may recommend but must not bypass Treasury, Risk, Compliance or user hard limits.

## Why there is no financial ROOT tree

The old model:

```text
ROOT
  -> A
     -> B
        -> C
```

creates an ownership ambiguity: if A disappears before B, there is no stable settlement path for A's residual capital or B's lifecycle.

The Company model removes that problem:

```text
Treasury
  -> bucket A
  -> bucket B
  -> bucket C
```

A, B and C are peers from a capital-ownership perspective.

Their genealogy can still be recorded:

```text
B.spawned_from = A
C.spawned_from = B
```

but this is historical metadata only.

## Invariants

The implementation must preserve these invariants:

1. Company equity is owned by Treasury.
2. Trader buckets are allocations, not ownership branches.
3. Trader removal cannot orphan capital.
4. Residual capital returns to Treasury Reserve.
5. Spawn lineage never determines settlement.
6. No agent may raise the user hard maximum of active Traders.
7. Production market exclusivity and training overlap are distinct policies.
8. Company Risk Governor can veto every Trader.
9. Broker execution occurs only after capital and risk authorization.
10. Failure of one Trader must not stop the Company.
