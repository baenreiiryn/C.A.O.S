# Company V6 — Strategy Rollout

Status: **COMPLETE on `feature/trade-company`**

## Goal

Create the controlled deployment bridge between a Research Factory champion and future Company assignments.

A strategy promoted by Company V5 does not immediately become a production candidate.

The rollout path is:

```text
Research champion
      |
      v
    SHADOW
      |
      v
 PAPER_CANARY
      |
      v
   ELIGIBLE
      |
 explicit operator activation
      |
      v
    ACTIVE
      |
 future Company opportunities only
```

Any release can also move to:

```text
ROLLED_BACK
```

The rollout system is implemented in:

```text
src/caos/company/rollout.py
```

## Version

```text
strategy-rollout/v1
```

## Core entities

### StrategyRolloutPolicy

Defines bounded rollout gates.

Current defaults:

```text
minimum shadow observations       3
minimum canary observations      20
minimum canary trades             1
canary starting capital        $10.00
canary exposure                   5%
canary fee model                  8 bps
maximum canary drawdown          10%
minimum canary PnL                0%
```

The policy is persisted with the rollout checkpoint state.

### StrategyRelease

A release records:

- release ID;
- symbol;
- strategy ID;
- Research Factory promotion decision ID;
- current stage;
- shadow observations;
- shadow long-signal count;
- virtual canary account;
- rollback reason;
- complete stage transition history.

Release IDs are deterministic from:

```text
symbol
strategy_id
research_decision_id
```

### CanaryAccount

A canary account is isolated simulation state:

- starting capital;
- virtual cash;
- virtual quantity;
- marked equity;
- peak equity;
- PnL;
- maximum drawdown;
- observation count;
- simulated trade count;
- last market timestamp;
- last ExecutionPlan ID.

It is not a Treasury account.

## Research Factory integration

When Company V5 promotes a candidate:

```text
ResearchCandidate
       |
PromotionDecision = promoted
       |
CompanyStrategyRegistry
       |
StrategyRolloutManager.sync_research()
       |
StrategyRelease(stage=shadow)
```

`TradeCompany.run_research_cycle()` automatically syncs newly promoted strategies into rollout.

Manual sync is also safe and idempotent.

The same research PromotionDecision cannot create duplicate releases.

## Shadow stage

Shadow uses real loaded market bars but does not simulate fills.

For each unseen bar it generates the same current:

```text
StrategyDecision
```

used by the Execution Fabric.

It records:

- observation timestamp;
- signal;
- decision ID.

No:

- Treasury capital;
- Trader slot;
- PaperBroker account;
- market assignment;
- broker call;

is created.

After the configured observation gate, the release moves to `paper_canary`.

The canary starts after the completed shadow window; shadow bars are not replayed as canary trades.

## Paper canary

Paper canary uses a dedicated virtual rollout account.

It consumes:

```text
StrategyDecision
       |
TargetPosition
       |
ExecutionPlan
```

from Company V4.

It models:

- target sizing;
- buy/sell deltas;
- fees;
- virtual cash;
- virtual quantity;
- marked equity;
- PnL;
- max drawdown.

It consumes zero Company Treasury capital and zero operational Trader slots.

## Canary gates

A release becomes `eligible` only when all configured gates are satisfied:

- minimum observation count;
- minimum simulated trade count;
- minimum PnL;
- drawdown not above the configured ceiling.

If drawdown breaches the hard canary ceiling:

```text
paper_canary
      |
      v
rolled_back
```

automatically.

A canary cannot self-activate into production.

## Eligible stage

`eligible` means:

> the rollout gates passed and the strategy may be considered for activation.

It does not mean:

- assign a Trader;
- move Treasury capital;
- create a market Opportunity;
- place a Paper order;
- place a TESTNET order;
- arm LIVE.

Activation remains explicit.

## Active stage

Only:

```text
activate_strategy_release(release_id)
```

can move:

```text
eligible -> active
```

An active release is stored in:

```text
production_catalog[symbol] = strategy_id
```

The active research strategy is then prepended to strategy candidates for **new future opportunities** on that symbol.

Existing Trader assignments are never hot-swapped.

## Assignment safety

Research strategy IDs fail closed.

A research strategy cannot become assignable merely because someone manually inserts its ID into a scan target.

For managed research strategies:

```text
shadow        -> not assignable
paper_canary  -> not assignable
eligible      -> not assignable
active        -> assignable on its release symbol
rolled_back   -> not assignable
```

A research strategy with no synced rollout release also fails closed.

Legacy/builtin strategies keep their existing behavior.

## Production market behavior

When a release is active:

```text
Configured scan candidates:
momentum, trend

Active BTCUSDT release:
research:candidate-xyz

New opportunity candidates:
research:candidate-xyz, momentum, trend
```

The normal MarketAllocator, Company Risk and production market exclusivity gates still apply.

The rollout manager does not assign Traders directly.

## Superseding an active release

If a newer eligible release for the same symbol is explicitly activated:

```text
old ACTIVE
   ->
ROLLED_BACK
(reason = superseded_by_new_active_release)

new ELIGIBLE
   ->
ACTIVE
```

Only one research release is present in the production catalog per symbol.

## Rollback

Rollback immediately removes a release from the production catalog.

It therefore blocks:

- new assignments to that release;
- new risk from the rolled-back research strategy.

Rollback deliberately does **not** force-close an existing Trader position.

For an already assigned Trader:

```text
rollback
   |
new risk disabled
   |
existing position may reduce / exit
   |
position becomes flat
   |
market assignment released
   |
Trader -> WAITING_ASSIGNMENT
```

This avoids replacing or liquidating a Trader by surprise while still preventing the rolled-back strategy from reopening risk.

The rollback response reports impacted Trader IDs.

## Company pause behavior

While the Company Cell is paused:

- daemon rollout progression is frozen;
- no shadow observations advance;
- no canary trades advance;
- manual `rollout-process` is rejected.

Existing Company V3 pause behavior for market observation and risk-reducing Trader exits remains unchanged.

## Daemon integration

CompanyDaemon now refreshes symbols required by:

- configured scan targets;
- current assignments;
- shadow releases;
- paper canary releases.

For each refreshed market, when Company operations are not paused:

```text
market refresh
    |
rollout.process_market()
    |
normal opportunity scan
    |
assignment
    |
Trader paper cycle
```

Rollout events are explicitly included in `CompanyDaemonCycle` and persisted in daemon-cycle observability.

## Standalone data refresh

Manual:

```text
company rollout-process --symbol BTCUSDT
```

uses already loaded bars when available.

If bars are absent, standalone Company attempts to fetch public market data first.

No credentialed broker connection is required.

## Persistence

Normal Company checkpoint now includes:

```text
rollout:
  version
  policy
  releases
  production_catalog
```

It persists:

- stage;
- transition history;
- shadow state;
- canary account;
- active catalog;
- rollback state.

Older V2/V3/V4/V5 checkpoints without `rollout` restore an empty V6 rollout manager.

## Restore integrity

Restore fails closed if:

- a release references a missing strategy;
- a release references a missing Research Factory promotion decision;
- canary accounting contains invalid negative state;
- production catalog points to zero or multiple matching active releases;
- production catalog points to a release that is not `active`.

## Company Cell Protocol

The Trade Company manifest advertises:

```text
domain.trade.rollout
```

Generic metrics include:

```text
rollout_releases
rollout_canaries
rollout_eligible
rollout_active
```

The generic Company report summarizes rollout state without requiring a future Drizzt supervisor to understand rollout internals.

## CompanyControlPort

Safe rollout surfaces:

```text
get_strategy_rollouts()
get_strategy_rollout_summary()
sync_strategy_rollouts()
process_strategy_rollouts(symbol)
activate_strategy_release(release_id)
rollback_strategy_release(release_id)
```

No broker or credential surface is added.

## Standalone CLI

Inspect:

```text
caos company rollout
```

Sync Research Factory promotions:

```text
caos company rollout-sync
```

Advance shadow/canary manually with public market data:

```text
caos company rollout-process --symbol BTCUSDT
```

Explicit activation:

```text
caos company rollout-activate <release-id>
```

Rollback:

```text
caos company rollout-rollback <release-id>
```

Optional rollback reason:

```text
--reason <text>
```

## Themed City

The Grand Tournament Arena now represents:

```text
TrainingArena + StrategyRolloutManager
```

It displays:

- release count;
- shadow count;
- paper-canary count;
- eligible count;
- active count;
- rolled-back count;
- strategy ID;
- virtual canary equity;
- canary PnL;
- canary drawdown;
- simulated trade count;
- production catalog;
- previous Training Arena tournament results.

Safe themed-city controls exist for:

- activate an eligible release;
- rollback an active release.

The themed UI explicitly states that rollback does not force-close existing positions.

HTTP surfaces:

```text
GET  /api/company/rollout
POST /api/company/rollout/<release-id>/activate
POST /api/company/rollout/<release-id>/rollback
```

## Security boundary

V6 still exposes no:

- raw broker order;
- broker credential;
- autonomous TESTNET execution;
- TESTNET arming;
- LIVE arming;
- LIVE execution adapter;
- kill-switch reset.

Rollout activation modifies only future strategy eligibility.

Actual Trader execution still passes through:

```text
MarketAllocator
    |
CompanyRiskGovernor
    |
Execution Fabric
    |
C.A.O.S Risk
    |
PaperBroker / separately human-gated TESTNET
```

## Acceptance criteria

Company V6 is complete when:

1. rollout protocol has an explicit version;
2. Research Factory promotions create shadow releases;
3. release IDs are deterministic;
4. research releases fail closed before activation;
5. shadow observes decisions without fills;
6. shadow consumes no Treasury capital;
7. shadow consumes no Trader slot;
8. shadow does not replay its observation window into canary;
9. paper canary uses Execution Fabric decisions/targets/plans;
10. canary uses an isolated virtual account;
11. canary tracks fees, equity, PnL, drawdown and trades;
12. canary consumes no Treasury capital;
13. canary consumes no Trader slot;
14. canary drawdown breach can automatically roll back;
15. only passing canaries become eligible;
16. eligible releases are still not assignable;
17. activation is explicit;
18. only active release is prioritized for new opportunities;
19. active rollout does not hot-swap existing Traders;
20. manually configured inactive research strategy cannot bypass rollout;
21. one active research release per symbol is enforced;
22. activating a newer release supersedes the previous active release;
23. rollback removes future assignment eligibility immediately;
24. rollback does not force-close existing positions;
25. rolled-back assigned Traders cannot increase/reopen risk;
26. rolled-back assignment is released once the Trader becomes flat;
27. Company pause freezes daemon rollout progression;
28. Company pause blocks manual rollout processing;
29. daemon refreshes markets needed by shadow/canary releases;
30. daemon exposes rollout events;
31. rollout state persists through restart;
32. old checkpoints without rollout restore safely;
33. corrupted rollout lineage/catalog fails closed;
34. Company Cell exposes rollout capability and metrics;
35. standalone CLI exposes safe rollout inspection/control;
36. themed Tournament Arena displays real rollout state;
37. themed Arena activation/rollback uses CompanyControlPort;
38. broker endpoints remain absent from the themed server;
39. previous V2/V3/V4/V5/Themed City regressions remain green;
40. dedicated rollout lifecycle tests remain green;
41. CLI smoke includes rollout inspection and sync;
42. no merge to `main` occurs without explicit user approval.

## Non-goals

Company V6 does not:

- enable autonomous TESTNET deployment;
- implement LIVE rollout;
- allocate real capital to a canary;
- create dedicated real-money canary Traders;
- hot-swap strategies on open positions;
- force-close positions on ordinary rollback;
- implement exchange-side deployment reconciliation;
- implement multi-region/distributed rollout;
- change Research Factory promotion rules;
- let Drizzt bypass CompanyControlPort.

Those remain later production-readiness stages.

## Validation result

Validated branch implementation:

```text
Ran 131 tests
OK

CI: SUCCESS
CLI smoke: SUCCESS
rollout inspection smoke: SUCCESS
rollout sync smoke: SUCCESS
shadow/canary lifecycle tests: SUCCESS
inactive research strategy bypass test: SUCCESS
Company pause rollout tests: SUCCESS
active opportunity priority test: SUCCESS
rollback/drain test: SUCCESS
canary drawdown rollback test: SUCCESS
checkpoint compatibility/integrity tests: SUCCESS
themed Arena HTTP controls test: SUCCESS
```

No merge to `main` has occurred.

**COMPANY V6 — STRATEGY ROLLOUT: COMPLETE**
