# Themed City UI Goal

Status: **COMPLETE**

Branch: `feature/trade-company`

## Objective

Replace the standalone Trade Company technical-card dashboard with a high-magic medieval city interface while preserving the existing standalone Company runtime and safety boundaries.

## Completion criteria

### 1. Keep the standalone Trade Company UI

Complete.

The existing command remains:

```text
caos company dashboard
```

The fantasy interface continues to run locally on the standalone Trade Company HTTP server, default port `5191`.

It still uses `CompanyControlPort` as its safe Company boundary.

### 2. Replace technical cards with a high-fantasy medieval city

Complete.

The primary page is now an interactive illustrated city scene rather than the old Overview/Traders/Treasury/Markets card dashboard.

The city includes:

- mountains, walls, roads and magical ley lines;
- high-magic city lighting and state effects;
- healthy / attention / critical / emergency visual language;
- city-wide emergency ward when Emergency Stop is active;
- minimal top HUD for Company equity, Treasury, Trader capacity and risk;
- reduced-motion support.

The technical JSON view is no longer the primary experience. Technical truth remains available only inside collapsible detail sections.

### 3. Every current function appears as a location or character

Complete.

The implemented first city contains:

- **Citadel of Oversight** — Royal Steward / Company Supervisor;
- **Grand Vault** — Royal Treasurer / Treasury + Capital Allocator;
- **Tower of Wards** — Archmage / Company Risk Governor + Strategy Diversity;
- **Grand Trading Guild** — Traders + Market Allocator + Strategy Registry;
- **Quest Board** — Opportunity Registry;
- **Scout Lodge** — Royal Pathfinder / Market Scout;
- **Arcane Observatory** — Market Seer / C.A.O.S quant and regime analysis;
- **The Whispering Tankard** — Bard / News and Sentiment;
- **Grand Tournament Arena** — Training Arena;
- **Arcane Workshop** — Royal Arcanist / Improvement Manager;
- **Arcane Nexus** — C.A.O.S shared engine and specialist models;
- **Chronicle Vault** — checkpoints, Store and recent persisted events.

Trader workers also appear directly around the Guild as clickable adventurer figures with their current real status/market.

No fake activity is invented. If a subsystem has no real data, its location explicitly shows that it is quiet or unconfigured.

### 4. Clicking opens real details

Complete.

Every city location opens an interactive side drawer backed by current Company state.

Examples:

- Tower of Wards -> real drawdown, gross exposure, kill switch, diversity and reconciliation state;
- Grand Vault -> real Treasury reserve, Company equity, balances, spawn capacity and ledger;
- Trading Guild -> real Trader Registry, assignments and registered strategies;
- Quest Board -> real opportunities and reservation state;
- Scout Lodge -> real loaded markets and execution-cost data;
- Observatory -> real C.A.O.S symbols, portfolio, approvals and experts;
- Tavern -> real news configuration and sentiment specialist state;
- Arena -> real TrainingArena experiments;
- Workshop -> real ImprovementManager proposals;
- Nexus -> real C.A.O.S health and specialist qualifications;
- Chronicle Vault -> real recent Store events and recovery state.

Clicking a visible Trader opens the real Trader details:

- lifecycle state;
- market/direction;
- strategy;
- capital;
- open exposure;
- requested sizing;
- maximum exposure;
- requested/max notional;
- paper/assignment technical state.

Safe controls remain functional:

- pause/resume Trader;
- configure Trader requested/max exposure;
- reduce operational Trader limit;
- Emergency Stop.

The themed UI still exposes no:

- raw broker order;
- broker credential;
- LIVE arm;
- kill-switch reset.

### 5. No Drizzt dependency

Complete.

The interface opens directly into Trade Company City.

There is:

- no required Drizzt process;
- no fake King Drizzt agent;
- no kingdom map dependency;
- no import or runtime dependency on Drizzt.

The current city is explicitly labeled:

```text
Trade Company
Arcane Trading City
Standalone Company Cell
```

Future Drizzt/Kingdom integration can sit above this UI without changing the Trade Company backend.

## Presentation architecture

The implementation keeps presentation separate from business logic:

```text
Trade Company + C.A.O.S
          |
          v
CompanyControlPort
          |
          v
CityPresentationMapper
          |
          v
Fantasy City UI
```

`CityPresentationMapper` converts real Company state into presentation-only:

- city mood;
- location state;
- attention markers;
- character activity summaries;
- visible Trader states.

It cannot change Company financial/risk/execution state.

## Validation

Automated validation covers:

- all 12 required fantasy city locations;
- city ViewModel endpoint;
- city HTML landmarks;
- removal of the old card-navigation interface;
- visible Trader adventurer layer;
- real Trader exposure control through the safe endpoint;
- Emergency Stop -> emergency city state;
- no broker endpoint exposed through the dashboard;
- existing Company/C.A.O.S regression tests;
- CLI smoke.

Latest validated suite:

```text
Ran 88 tests
OK
CI: SUCCESS
CLI smoke: SUCCESS
```

## Goal result

All user-defined completion points are implemented and validated.

**THEMED CITY UI GOAL: COMPLETE**
