# Company V7 — Production Reliability / Broker Reconciliation

Status: **COMPLETE — current broker implementation updated for Binance Spot in v0.7.2**

## Goal

Make external ExecutionPlan submission crash-safe and duplicate-resistant before any future autonomous production rollout.

The current reliability path is:

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

No uncertain intent is automatically resent.

## Current broker scope

v0.7.2 uses:

```text
venue       = binance
environment = spot-testnet
```

for money-moving test execution.

A second Binance environment is available in the Broker Embassy:

```text
production-readonly
```

It authenticates a real Binance Japan Spot account and exposes safe account metadata. Production order creation is rejected in code.

LIVE remains unavailable.

## Intent identity

Each durable intent is unique by:

```text
venue
environment
plan_id
```

For Binance Spot Testnet, the deterministic Execution Fabric `plan_id` is propagated as:

```text
newClientOrderId
```

and later queried as:

```text
origClientOrderId
```

The ID is limited to the exchange-supported client-order identifier length.

## Durable SQLite outbox

The `execution_intents` table persists:

- intent ID;
- plan ID;
- venue;
- environment;
- symbol;
- canonical order payload;
- payload hash;
- status;
- broker order ID;
- broker client-order ID;
- reconciliation status/payload;
- last error;
- timestamps.

The database enforces:

```text
UNIQUE(venue, environment, plan_id)
```

The journal is separate from the normal Trade Company checkpoint so restoring an internal Company snapshot cannot erase external execution history.

## Broker credentials

The durable journal never accepts or stores API keys or secrets.

On Windows, Broker Embassy secrets are stored in Windows Credential Manager. The SQLite journal stores only order intent and reconciliation data.

## Spot semantics

The current adapter is Spot-only.

```text
BUY   -> open/increase a long Spot position
SELL  -> allowed only when the ExecutionPlan is risk-reducing
```

A SELL intended to create naked short exposure fails closed with:

```text
binance_spot_shorting_not_supported
```

No derivatives or leveraged-short semantics are implied by the Spot adapter.

## PREPARED

`prepare_plan()` translates the venue-agnostic ExecutionPlan into a Binance Spot order payload and persists it before any submit.

Preparation is not money-moving and does not require TESTNET arming.

## SUBMITTING

Immediately before the network call:

```text
PREPARED -> SUBMITTING
```

is claimed atomically.

A second process cannot submit the same durable plan while it is already SUBMITTING, UNCERTAIN, ACKNOWLEDGED, RECONCILED or ABANDONED.

## Crash window protection

The critical case is:

```text
persist SUBMITTING
      |
POST order
      |
broker accepts
      |
process/network dies before local ACK persistence
```

After restart the executor does not resend the order.

It reconciles by the original client-order ID.

## Binance Spot Testnet client

The test execution client is hard-locked to:

```text
https://testnet.binance.vision
```

Signed requests use the Binance Spot REST contract:

```text
X-MBX-APIKEY
timestamp
recvWindow
HMAC-SHA256 signature
```

Unknown/cross-environment hosts are rejected.

## ACKNOWLEDGED

An order ACK must contain:

- non-empty broker `orderId`;
- non-empty `clientOrderId`;
- `clientOrderId` equal to the expected plan-derived ID.

Invalid ACK identity becomes UNCERTAIN rather than trusted success.

## Reconciliation

Recovery queries:

```text
GET /api/v3/order
  symbol=<symbol>
  origClientOrderId=<plan-derived-id>
```

The local intent is compared with the normalized broker order:

- client-order ID;
- symbol;
- side;
- order type;
- original quantity.

If all identity fields match:

```text
RECONCILED
reconciliation_status = matched
```

The returned broker status, executed quantity and average-price evidence are kept in the reconciliation payload.

## Not found

Binance error code `-2013` is treated as order not found.

The intent remains:

```text
UNCERTAIN
reconciliation_status = not_found
```

No retry happens automatically.

A confirmed missing intent may be explicitly resolved as ABANDONED. The same plan ID remains recorded and therefore cannot be accidentally replayed.

## Mismatch

If broker identity conflicts with the durable payload, the intent remains UNCERTAIN with explicit issues such as:

```text
qty_mismatch
side_mismatch
order_type_mismatch
```

No automatic corrective order is submitted.

## Human TESTNET gate

Money-moving test submission still requires exact confirmation:

```text
ARM TESTNET
```

If TESTNET is not armed:

- no broker POST is performed;
- no execution intent is created as a side effect of submit.

Reconciliation/recovery is read-only and may run without arming TESTNET.

## Broker Embassy environments

### spot-testnet

- authenticated Binance Spot Testnet;
- human-gated order submission;
- durable V7 journal/recovery;
- no naked shorting.

### production-readonly

Uses the production Binance Spot REST host:

```text
https://api.binance.com
```

C.A.O.S may authenticate the account and read safe metadata such as:

- account type;
- permissions;
- non-zero balances;
- trading capability flags.

Calling `place_order()` in this environment raises:

```text
binance_production_trading_forbidden
```

Therefore adding a real Binance Japan profile does not enable real-money orders.

## Broker switching

Switching active Binance profiles is blocked if any Binance execution intent in any environment is still:

- SUBMITTING;
- UNCERTAIN;
- ACKNOWLEDGED.

This prevents changing broker context while external execution state still requires reconciliation.

## Legacy venue history

Older durable rows from previous broker adapters are preserved in SQLite for audit history.

The active Binance reliability journal is scoped by:

```text
venue = binance
environment = <active environment>
```

so legacy rows do not contaminate current Binance recovery counts.

## CLI

Inspect current Company reliability:

```bash
caos company reliability
```

Inspect the active Binance Spot Testnet intent journal:

```bash
caos execution-intents
```

Recover one or all pending Spot Testnet intents:

```bash
caos testnet-recover
caos testnet-recover --intent-id <intent-id>
```

Development/CLI credentials can be supplied through:

```powershell
$env:BINANCE_TESTNET_API_KEY="..."
$env:BINANCE_TESTNET_API_SECRET="..."
```

Installed Windows users can instead save the Spot Testnet profile in Broker Embassy; the packaged CLI loads that profile from Windows Credential Manager.

## Company / City observability

TradeCompany exposes read-only reliability status:

```text
version
venue
environment
counts
total
recovery_required
recent_intents
```

The Company Cell advertises:

```text
domain.trade.execution_reliability
```

When recovery is pending:

```text
Cell health      -> attention
Chronicle Vault -> attention
City mood        -> attention
```

The themed UI never exposes raw broker credentials or a production-order endpoint.

## Safety boundary

The current architecture permits:

```text
PAPER                         yes
Binance public market data    yes
Binance Spot Testnet          human-gated
Binance Japan account read    yes
Binance Japan production buy  no
Binance Japan production sell no
LIVE                          no
naked Spot short              no
```

A later production milestone must add separate explicit production authorization and further position/fill reconciliation before real-money order submission can exist.

## Validation requirements

The Binance migration preserves the original V7 invariants:

1. intent preparation is durable and idempotent;
2. venue/environment/plan ID uniqueness prevents duplicates;
3. credentials never enter the journal;
4. SUBMITTING is persisted before the network call;
5. crash/restart never causes automatic resend;
6. reconciliation uses the deterministic client-order ID;
7. invalid ACK identity fails closed;
8. quantity/side/type mismatches fail closed;
9. not-found never retries automatically;
10. explicit abandonment performs no submit;
11. human TESTNET arming is still required for money-moving calls;
12. recovery is read-only and can run unarmed;
13. production-readonly cannot submit orders;
14. Spot naked shorts are rejected;
15. legacy venue rows remain isolated from the active Binance journal;
16. Company/Cell/Chronicle reliability visibility remains read-only;
17. LIVE remains unavailable.
