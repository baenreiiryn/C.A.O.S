# Trade Company development goal

Status: **IN DEVELOPMENT on `feature/trade-company`**.

Nothing in this Goal should be merged to `main` merely because the architecture compiles. The branch must prove the Company invariants and C.A.O.S integration first.

## Dependency rule

```text
future Drizzt -> Trade Company -> C.A.O.S -> Broker
```

Trade Company works without Drizzt. C.A.O.S remains usable without Trade Company. Drizzt must never bypass the Company/C.A.O.S control path to reach broker credentials or raw execution.

## Company responsibilities

- CompanyPolicy: user safety policy, including the operational concurrency cap and default Trader risk ceiling;
- Treasury: Company-owned equity and append-only ledger;
- CapitalAllocator: operating buckets and expansion;
- TraderRegistry: A/B/C/... workers, not financial parents;
- MarketScout + MarketRegime: opportunity discovery using C.A.O.S evidence;
- OpportunityRegistry: expiring normalized opportunities;
- MarketAllocator: production exclusivity and training overlap;
- StrategyDiversity: company-wide concentration observations;
- CompanyRiskGovernor: risk gate above the C.A.O.S RiskEngine;
- TrainingArena: fair same-market/same-period deterministic experiments;
- Supervisor: company-wide invariant and health audit;
- ImprovementManager: proposals only, never policy bypass;
- CompanyControlPort: standalone CLI/UI seam and future Drizzt integration seam.

## Financial invariant

`spawned_from` is analytics only.

Capital always belongs to Treasury. A Trader receives an operating bucket. If a Trader is retired, residual capital settles to Treasury Reserve regardless of who triggered that Trader's creation.

Example:

```text
Treasury already has 10 available
  -> B may receive a new 10 bucket without touching A

or

Treasury is short
A has capital above its minimum operating bucket
  -> Capital Allocator may harvest only the missing amount
  -> Treasury reaches the minimum funding required
  -> B receives its initial bucket

A later retires
  -> A residual returns to Treasury
  -> B remains independent
```

## Initial policy carried from the Drizzt Trade Company design

- initial example capital: 10 USD;
- initial Trader bucket: 10 USD;
- stop floor: 3 USD;
- default per-Trader maximum trade exposure: 20% of that Trader's current equity;
- actual requested trade size may be lower than the Trader's maximum;
- exposure ceilings are configurable independently per Trader;
- operational Trader cap: configurable resource-safety limit (default 6), not an economic rule;
- spawn requires enough Treasury funding for the new Trader's minimum initial bucket;
- production: whole-symbol exclusivity by default;
- training: same-market overlap allowed;
- LIVE remains disabled by default.

## Merge gate

Before merge to `main`:

1. existing C.A.O.S tests remain green;
2. all Trade Company tests are green;
3. A-retired-before-B cannot orphan or redirect B capital;
4. ledger accounting preserves Company equity across internal transfers;
5. stop-floor settlement returns residual to Treasury;
6. Company runtime cannot exceed its configured operational Trader cap;
7. Company Risk Governor enforces each Trader's own current-equity exposure ceiling;
8. production market duplication is rejected;
9. training overlap works in isolated experiment semantics;
10. Company control surface exposes no raw broker credentials/order bypass;
11. integration tests prove Market Scout/Training use the shared C.A.O.S engine;
12. no merge is performed until explicitly reviewed after branch validation.
