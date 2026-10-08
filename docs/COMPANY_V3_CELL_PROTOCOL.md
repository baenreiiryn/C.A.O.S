# Company V3 — Cell Protocol

Status: **COMPLETE on `feature/trade-company`**

## Goal

Turn Trade Company + C.A.O.S into the first autonomous **Company Cell** that can be supervised externally through a stable, generic protocol without exposing trading internals.

The future architecture is:

```text
                         DRIZZT
                  Company Supervisor
                         |
                  Company Cell Protocol
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     Trade Cell      Content Cell    Future Cell
          |
   Trade Company
          |
       C.A.O.S
```

Drizzt is not required to run the Trade Cell.

## Core rule

Drizzt and any future global supervisor must not need to know:

- Treasury internals;
- Trader Registry internals;
- BTC/ETH symbols;
- C.A.O.S internal classes;
- broker adapters;
- domain-specific databases.

A supervisor interacts with every Company through the same generic contract.

## Protocol version

```text
company-cell/v1
```

The version is explicit in every Cell manifest.

## Generic interface

Every Company Cell must implement:

```text
get_manifest()
get_status()
get_health()
get_metrics()
get_alerts()
get_recent_events()
get_report()
execute_command()
```

Defined in:

```text
src/caos/cell_protocol.py
```

The Trade Company implementation is:

```text
src/caos/company/cell.py
TradeCompanyCell
```

## Manifest

The manifest is domain-independent.

Example:

```json
{
  "cell_id": "trade-company",
  "cell_type": "trading",
  "name": "Trade Company",
  "protocol_version": "company-cell/v1",
  "autonomy": "autonomous",
  "capabilities": [
    "status",
    "health",
    "metrics",
    "alerts",
    "events",
    "report",
    "themed_ui",
    "domain.trade.summary"
  ],
  "commands": [
    "pause",
    "resume",
    "emergency_stop"
  ],
  "ui": {
    "kind": "themed_city",
    "path": "/",
    "label": "Arcane Trading City"
  }
}
```

A future Content Cell could expose completely different domain capabilities while preserving the same generic fields.

## Status

Generic status answers:

- who this Cell is;
- whether it is running/paused/emergency-stopped;
- overall health;
- autonomy mode;
- a small summary.

Trade-specific detail remains behind Trade Company surfaces and is not required for generic supervision.

## Health

Health returns:

```text
healthy
attention
critical
emergency
```

plus named checks.

For Trade Company, checks currently include:

- Company Supervisor state;
- Company kill switch;
- C.A.O.S kill switch;
- reconciliation state;
- operational pause state.

Future cells can expose different checks.

## Generic metrics

Metrics use two simultaneous representations.

### Fast lookup

```json
{
  "values": {
    "company_equity": 10.0,
    "treasury_reserve": 0.0
  }
}
```

### Generic descriptor list

```json
{
  "items": [
    {
      "id": "company_equity",
      "label": "Company Equity",
      "value": 10.0,
      "unit": "USD",
      "category": "finance"
    }
  ]
}
```

A global supervisor can render `items` without knowing the metric names in advance.

The `metrics` field currently mirrors `items` for compatibility.

## Generic alerts

Domain alerts are normalized to:

```json
{
  "id": "trade-company:funded_trader_unassigned:0",
  "cell_id": "trade-company",
  "severity": "warning",
  "code": "funded_trader_unassigned",
  "title": "Funded Trader Unassigned",
  "message": "A funded Trader is waiting for a valid market assignment. Target: A.",
  "target": "A",
  "data": {
    "cell_id": "trade-company",
    "target": "A",
    "raw": {}
  }
}
```

A future Drizzt UI can display alert severity/title/message without understanding the raw Trade Company structure.

## Recent events

Events are normalized to:

```text
cell_id
id
kind
created_at
payload
```

The raw event payload remains domain-specific, but the envelope is common.

## Report

`get_report()` is the primary future Drizzt briefing surface.

It returns:

- Cell identity;
- operational state;
- health;
- headline;
- short human-readable highlights;
- up to five current alerts;
- latest activity/events;
- current metric values;
- UI location.

This is intentionally concise enough for a kingdom-level supervisor.

## Commands

The generic v1 Trade Cell exposes only:

```text
pause
resume
emergency_stop
```

### pause

Pause is a **Cell-wide operational pause**.

It does not:

- destroy Traders;
- liquidate Treasury;
- rewrite strategy state;
- reset a kill switch.

While paused, Trade Company blocks:

- new Opportunity creation;
- new Trader assignment;
- new risk entry;
- Trader expansion/spawn.

It continues:

- market refresh;
- health/audit;
- mark-to-market;
- stop-floor monitoring;
- risk-reducing exits.

This prevents a pause command from trapping an existing position that needs to exit.

### resume

Resume returns autonomous operations to normal only when:

- Company kill switch is not active;
- C.A.O.S kill switch is not active.

Resume cannot bypass Emergency Stop.

### emergency_stop

Emergency Stop is risk-reducing.

It activates the existing Company/C.A.O.S kill path.

The generic protocol intentionally exposes no reset command.

## Persistence

Cell operational pause state is stored in the normal Trade Company checkpoint.

After restart:

```text
paused -> restore -> still paused
```

No Drizzt connection is required for recovery.

## HTTP transport

The standalone Trade Company server exposes the protocol at:

```text
GET  /api/cell/v1/manifest
GET  /api/cell/v1/status
GET  /api/cell/v1/health
GET  /api/cell/v1/metrics
GET  /api/cell/v1/alerts
GET  /api/cell/v1/events
GET  /api/cell/v1/report

POST /api/cell/v1/command
```

Example command:

```json
{
  "name": "pause"
}
```

The protocol is available on the same local server as the Trade Company themed city.

## CLI

Standalone inspection is also available through:

```text
caos company cell-manifest
caos company cell-status
caos company cell-health
caos company cell-metrics
caos company cell-alerts
caos company cell-report
caos company cell-pause
caos company cell-resume
```

Emergency Stop remains available through the existing Company command and the generic Cell command surface.

## Security boundary

The Company Cell protocol does not expose:

- broker credentials;
- raw broker order placement;
- LIVE arming;
- TESTNET credential handling;
- kill-switch reset;
- direct C.A.O.S internals;
- direct Treasury mutation;
- direct Trader spawning.

Drizzt future must not bypass:

```text
Company Cell Protocol
        |
CompanyControlPort
        |
Company Policy / Risk
        |
C.A.O.S Risk / Compliance
        |
Broker
```

## Themed City integration

The fantasy city remains the Trade Cell's own UI.

Its pause state is represented visually as a quiet city state.

Future Drizzt may use the manifest's UI metadata to open the city directly.

The themed UI is not part of the generic business logic.

## Future Company compatibility

A future cell can implement the same protocol without importing Trade Company code.

For example:

```text
ContentCompanyCell

get_manifest()
get_status()
get_health()
get_metrics()
get_alerts()
get_recent_events()
get_report()
execute_command()
```

Its metrics could be:

```text
videos_published
queue_depth
approval_backlog
engagement
```

Drizzt can still consume them through generic `CellMetric` descriptors.

## Acceptance criteria

Company V3 is complete when:

1. a generic runtime-checkable CompanyCell contract exists;
2. Cell protocol has an explicit version;
3. Trade Company implements the generic contract through an adapter;
4. manifest does not require Drizzt;
5. generic status exposes operational state and health;
6. health contains domain-neutral state plus checks;
7. metrics provide lookup values and generic descriptors;
8. alerts use a stable generic envelope;
9. recent events are exposed through a common envelope;
10. a concise supervisor report includes health, metrics, alerts and recent activity;
11. pause/resume/emergency_stop are the only generic Trade Cell commands;
12. pause state persists through restart;
13. paused Trade Cell creates no new risk, assignments, opportunities or spawn;
14. paused Trade Cell still permits risk-reducing exits and stop-floor handling;
15. resume cannot bypass Company/C.A.O.S kill switches;
16. versioned HTTP transport exposes the complete protocol;
17. CLI can inspect the protocol without domain-internal calls;
18. themed city reflects paused state;
19. no broker credential/raw-order/LIVE/reset surface exists in Cell protocol;
20. all existing C.A.O.S, Company V2 and Themed City regressions remain green;
21. CI and CLI smoke are green;
22. no merge to `main` occurs without explicit user approval.

## Non-goals

Company V3 does not:

- integrate Drizzt itself;
- implement a kingdom map;
- create other Company types;
- implement service discovery across machines;
- implement authentication/remote exposure;
- enable LIVE trading;
- allow generic supervisors to mutate domain internals.

Those can be built above the stable Cell Protocol later.


## Validation result

Final validated implementation:

```text
Ran 95 tests
OK

CI: SUCCESS
CLI smoke: SUCCESS
Cell manifest smoke: SUCCESS
Cell report smoke: SUCCESS
```

The validated branch still remains `feature/trade-company`.

No merge to `main` has occurred.

**COMPANY V3 — CELL PROTOCOL: COMPLETE**
