# Company V7 — Production Reliability / Broker Reconciliation

Status: **IN DEVELOPMENT on `feature/trade-company`**

## Goal

Make external ExecutionPlan submission crash-safe and duplicate-resistant before any future autonomous TESTNET or LIVE rollout.

The reliability path is:

```text
ExecutionPlan
     |
     v
  PREPARED
     |
atomic durable claim
     v
 SUBMITTING
     |
     +-----------------------+
     |                       |
 broker ACK              ambiguous result
     |                       |
     v                       v
ACKNOWLEDGED              UNCERTAIN
     |                       |
     +----------+------------+
                |
        broker reconciliation
                |
        +-------+--------+
        |                |
      match          not found /
        |             mismatch
        v                |
   RECONCILED         UNCERTAIN
                         |
              explicit confirmed-missing
                    abandonment
                         |
                         v
                    ABANDONED
```

The system never automatically resubmits a `SUBMITTING`, `UNCERTAIN`, `ACKNOWLEDGED`, `RECONCILED` or `ABANDONED` intent.

## Versions

Execution reliability contract:

```text
execution-reliability/v1
```

Implementation:

```text
src/caos/execution_reliability.py
```

Durable storage lives in the normal SQLite Store, but in a dedicated table independent from the Trade Company checkpoint.

## Durable execution outbox

The Store migration creates:

```text
execution_intents
```

Each row persists:

- intent ID;
- ExecutionPlan plan ID;
- venue;
- environment;
- symbol;
- canonical order payload;
- payload hash;
- intent status;
- broker order ID;
- broker order-link ID;
- reconciliation status;
- reconciliation payload;
- last error;
- created/updated timestamps.

The database enforces:

```text
UNIQUE(venue, environment, plan_id)
```

This is the durable duplicate-prevention boundary.

## Intent identity

For V7:

```text
venue       = bybit
environment = testnet
```

The intent ID is deterministic from:

```text
venue
environment
plan_id
```

The Bybit `orderLinkId` remains the deterministic Execution Fabric `plan_id`.

A second preparation of the same canonical plan returns the existing intent.

If the same plan ID is presented with a different translated payload, preparation fails closed with a payload conflict.

## Credentials

The durable journal accepts no API key or API secret.

Persisted intent payload contains only order information such as:

- category;
- symbol;
- side;
- order type;
- quantity;
- reduce-only flag;
- orderLinkId;
- optional limit price.

Broker credentials remain runtime-only inputs to the Bybit TESTNET client.

## PREPARED

`prepare_plan()` translates an ExecutionPlan using the existing V4 adapter and writes the intent before any money-moving network call.

Preparation itself does not require TESTNET arming because it does not submit an order.

## SUBMITTING

Before calling the broker, the journal performs an atomic:

```text
PREPARED -> SUBMITTING
```

transition.

Only one caller can claim a PREPARED intent.

Concurrent/restarted callers seeing SUBMITTING are forbidden from submitting the same plan again.

This closes the local duplicate race.

## Crash window

The critical failure case is:

```text
persist SUBMITTING
      |
send request
      |
broker accepts
      |
process/network dies before ACK is persisted
```

On restart, the intent is still SUBMITTING/UNCERTAIN.

The reliable executor does **not** resend it.

It queries the broker by the original `orderLinkId`.

## ACKNOWLEDGED

If Bybit order creation returns a valid response, V7 verifies:

- non-empty broker order ID;
- non-empty orderLinkId;
- returned orderLinkId exactly matches the planned orderLinkId.

Only then:

```text
SUBMITTING -> ACKNOWLEDGED
```

An empty/wrong ACK identity becomes UNCERTAIN and requires reconciliation.

ACKNOWLEDGED remains part of `recovery_required` because an asynchronous broker ACK is not considered final reconciliation.

## Bybit TESTNET reconciliation

The Bybit client remains hard-locked to:

```text
https://api-testnet.bybit.com
```

Reconciliation searches by the persisted orderLinkId.

The lookup order is:

```text
GET /v5/order/realtime
          |
      not found
          v
GET /v5/order/history
```

This follows the current Bybit V5 model where real-time orders can be queried by orderLinkId and older/cleared order records are available through order history.

## Broker identity reconciliation

When a broker order is found, V7 compares persisted intent against broker state:

- orderLinkId;
- symbol;
- side;
- order type;
- quantity;
- reduce-only.

If all identity fields match:

```text
-> RECONCILED
reconciliation_status = matched
```

The broker order state itself is preserved in the reconciliation payload, including fields such as order status, cumulative executed quantity and average price when returned.

`RECONCILED` means the intended order identity is accounted for at the broker. It does not claim that the order necessarily filled.

## Mismatch

If the broker returns the same lookup record but the order identity differs:

```text
status = UNCERTAIN
reconciliation_status = mismatch
```

Mismatch issues are recorded, e.g.:

```text
qty_mismatch
side_mismatch
reduce_only_mismatch
```

No retry occurs.

## Not found

If both real-time and history lookups return no order:

```text
status = UNCERTAIN
reconciliation_status = not_found
```

The system still does not automatically retry.

This deliberately favors duplicate prevention over automatic recovery from a possibly delayed broker record.

## Stable reconciliation

After an intent has been matched and moved to RECONCILED, a later transient broker query returning no record does not downgrade the already reconciled local state.

A real conflicting broker record can still surface as a mismatch.

## Explicit abandonment

A confirmed-not-found intent can be resolved without resubmission:

```text
UNCERTAIN + not_found
        |
 explicit operator action
        v
    ABANDONED
```

Only intents whose latest reconciliation state is exactly `not_found` can be abandoned.

CLI confirmation is exact:

```text
ABANDON MISSING TESTNET INTENT
```

Abandonment does not create a new order.

The same plan ID remains persisted, so replaying that plan is still blocked.

A later strategy decision must produce a genuinely new plan ID before it can create a new intent.

## ReliableHumanTestnetExecutor

V7 adds:

```text
ReliableHumanTestnetExecutor
```

Operations:

```text
prepare_plan(plan)
submit_plan(plan)
reconcile_intent(intent_id)
recover()
```

### Submit boundary

`submit_plan()` still requires:

```text
ARM TESTNET
```

before any network submit.

If TESTNET is not armed:

- no broker request is sent;
- no intent is prepared as a side effect of submit.

### Recovery boundary

Reconciliation/recovery is read-only broker activity.

It does not require TESTNET arming.

This allows recovery after a restart without opening a money-moving execution window.

## Recovery

`recover()` scans durable intents in:

- SUBMITTING;
- UNCERTAIN;
- ACKNOWLEDGED.

It reconciles each one against Bybit TESTNET.

It never calls order creation.

## Audit events

Reliability transitions emit normal Store events including:

- execution_intent_submitting;
- execution_intent_acknowledged;
- execution_intent_uncertain;
- execution_intent_reconciled;
- execution_intent_reconciliation_not_found;
- execution_intent_reconciliation_mismatch;
- execution_intent_abandoned.

These appear in normal Company recent-event/Chronicle history.

## Independent persistence

Execution intents are not serialized inside:

```text
trade_company_checkpoint_v1
```

They live in their own SQLite table.

Therefore:

```text
Company checkpoint restore
Company checkpoint replacement
Company state rollback
```

cannot erase the external execution journal.

Creating a new TradeCompany over the same Store sees the same unresolved execution intents.

## Company observability

TradeCompany status includes:

```text
execution_reliability:
  version
  venue
  environment
  persistent
  counts
  total
  recovery_required
  recent_intents
```

The Company itself receives no broker credentials and no submit method from this integration.

## CompanyControlPort

Read-only surface:

```text
get_execution_reliability()
```

It returns summary + intents.

No order submit/retry endpoint is exposed.

## Company Cell Protocol

Trade Company advertises:

```text
domain.trade.execution_reliability
```

Generic metrics include:

```text
execution_intents
execution_recovery_required
```

If recovery is pending, Cell health becomes:

```text
attention
```

and an alert is emitted:

```text
execution_reconciliation_required
```

A future Drizzt supervisor can therefore report an ambiguous broker execution without knowing Bybit internals.

## Standalone CLI

Read the Company view:

```text
caos company reliability
```

Read the generic intent journal:

```text
caos execution-intents
caos execution-intents --limit 25
```

Reconcile one or all pending TESTNET intents:

```text
caos testnet-recover
caos testnet-recover --intent-id <intent-id>
```

This requires TESTNET credentials to query the private broker account but does not require `ARM TESTNET` because it performs no submit.

Resolve a confirmed-missing intent:

```text
caos testnet-abandon-missing <intent-id> \
  --confirm "ABANDON MISSING TESTNET INTENT"
```

No command automatically retries an uncertain intent.

## Themed City

The Chronicle Vault now represents:

```text
CompanyCheckpoint
+ Store
+ ExecutionReliabilityJournal
```

It displays:

- journal version;
- total intents;
- PREPARED count;
- ACKNOWLEDGED count;
- RECONCILED count;
- recovery-required count;
- recent intent status;
- plan ID;
- reconciliation status;
- last error.

When recovery is required:

```text
Chronicle Vault -> attention
City mood        -> attention
```

The interface explicitly states that credentials are not stored and ambiguous intents require reconciliation before retry.

Read-only HTTP:

```text
GET /api/company/reliability
```

The themed server still exposes no broker credential endpoint and no external submit endpoint.

## Legacy raw TESTNET command

The older:

```text
caos testnet-order
```

remains a direct human-only compatibility/admin surface.

It is not used by Trade Company autonomy and is not the V7 durable ExecutionPlan path.

Future autonomous TESTNET rollout must use ReliableHumanTestnetExecutor or an equivalent durable intent contract.

## LIVE

V7 does not add:

- LIVE broker URL;
- LIVE execution coordinator;
- LIVE credentials;
- autonomous LIVE arming;
- autonomous TESTNET arming.

LIVE remains unavailable to the Trade Company.

## Acceptance criteria

Company V7 is complete when:

1. execution reliability has an explicit version;
2. SQLite migration creates a dedicated durable intent table;
3. intent uniqueness is enforced by venue/environment/plan ID;
4. intent IDs are deterministic;
5. journal stores no API credentials;
6. same plan/payload preparation is idempotent;
7. same plan with conflicting payload fails closed;
8. PREPARED is durable before broker submit;
9. PREPARED -> SUBMITTING is an atomic claim;
10. concurrent journal users cannot claim the same plan twice;
11. SUBMITTING/UNCERTAIN intents cannot auto-resubmit;
12. valid broker ACK is durably recorded;
13. invalid/mismatched ACK identity becomes UNCERTAIN;
14. successful submit replay after restart does not create a second request;
15. ambiguous network failure persists UNCERTAIN;
16. restart recovery reconciles by the original orderLinkId;
17. Bybit reconciliation checks real-time orders;
18. Bybit reconciliation falls back to order history;
19. GET requests use authenticated signed query strings;
20. matched broker identity becomes RECONCILED;
21. broker identity mismatch fails closed as UNCERTAIN;
22. double lookup not-found remains UNCERTAIN;
23. not-found never triggers automatic retry;
24. matched RECONCILED state is not downgraded by a later transient not-found lookup;
25. confirmed-not-found intent can be explicitly abandoned;
26. abandonment performs no submit;
27. abandoned same-plan replay remains blocked;
28. recovery scans SUBMITTING/UNCERTAIN/ACKNOWLEDGED only;
29. recovery performs no order creation;
30. TESTNET submit still requires explicit human arming;
31. read-only recovery does not require TESTNET arming;
32. Bybit client remains hard-locked to TESTNET;
33. reliability transitions are written to audit events;
34. external execution journal survives Company checkpoint restore independently;
35. Company status exposes reliability summary/intents;
36. CompanyControlPort reliability surface is read-only;
37. Company Cell advertises reliability capability;
38. Company Cell exposes reliability metrics;
39. pending recovery creates a generic Cell alert/attention health;
40. Chronicle Vault displays real reliability state;
41. city mood/Chronicle location surface unresolved execution attention;
42. themed HTTP reliability endpoint is read-only;
43. themed broker endpoint remains absent;
44. standalone reliability/intents CLI inspection works without credentials;
45. TESTNET recovery CLI does not submit orders;
46. no autonomous TESTNET execution is enabled;
47. no LIVE execution is enabled;
48. all V2/V3/V4/V5/V6 regressions remain green;
49. dedicated V7 crash/restart/idempotency/reconciliation tests are green;
50. no merge to `main` occurs without explicit user approval.

## Non-goals

Company V7 does not:

- automatically retry ambiguous external orders;
- automatically abandon missing orders;
- enable Company daemon TESTNET trading;
- route rollout ACTIVE strategies to TESTNET;
- implement position-level broker/Company reconciliation;
- implement websocket order streams;
- implement exchange fills ledger/accounting;
- implement cancel/amend reliability;
- implement LIVE execution;
- migrate the legacy raw human `testnet-order` command into the durable plan path.

Those are later production-readiness steps after order-intent reliability is proven.
