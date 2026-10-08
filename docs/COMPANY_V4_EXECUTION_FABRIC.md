# Company V4 — Execution Fabric

Status: **COMPLETE on `feature/trade-company`**

## Goal

Create one explicit, venue-agnostic execution language between strategy research and execution:

```text
Strategy
   |
   v
StrategyDecision
   |
   v
TargetPosition
   |
   v
ExecutionPlan
   |
   +------> Research / Backtest trace
   |
   +------> C.A.O.S Paper
   |
   +------> Trade Company Paper
   |
   +------> Human-gated Binance Spot TESTNET
   |
   +------> future LIVE adapter (not implemented)
```

The objective is to reduce semantic drift between what research intended and what execution actually did.

## Version

```text
execution-fabric/v1
```

Defined in:

```text
src/caos/execution_fabric.py
```

## Core domain

### StrategyDecision

A strategy does not create a broker order.

It creates a venue-independent decision:

```text
symbol
strategy_id
signal = long | flat
requested_weight
as_of
reason
decision_id
```

The ID is deterministic for the same canonical decision payload.

Example:

```text
BTCUSDT
momentum
LONG
requested weight = 0.08
```

### TargetPosition

Risk/capital resolution transforms the decision into a target:

```text
symbol
strategy_id
side
target_weight
target_notional
decision_id
```

The target represents desired final exposure, not an order.

Example:

```text
Trader equity              $10.00
requested weight              8%
requested target            $0.80
hard exposure ceiling       $2.00

TargetPosition             $0.80
```

If requested exposure exceeds the allowed maximum:

```text
requested target            $2.00
hard ceiling                $1.50

TargetPosition             $1.50
```

### ExecutionPlan

The planner compares current marked exposure with the target.

```text
current position
      +
target position
      |
      v
ExecutionPlan
```

Plan actions:

```text
hold
increase
reduce
close
```

Plan fields include:

```text
plan_id
decision_id
symbol
strategy_id
action
side
current_notional
desired_target_notional
effective_target_notional
order_notional
reference_price
risk_reducing
allow_new_risk
```

`order_notional` is the delta to execute.

## Delta execution

Example:

```text
current             $0.00
target              $2.00
-------------------------
plan              increase
delta               $2.00
```

Later:

```text
current             $2.00
target              $1.00
-------------------------
plan                reduce
delta               $1.00
```

The system does not need to close and reopen the full position merely because sizing changed.

For a flat target:

```text
current             $1.00
target              $0.00
-------------------------
plan                 close
delta               $1.00
risk reducing         true
```

## Aggregate target risk

For increases, risk is checked against the **final effective target**, not only the incremental order.

This prevents:

```text
existing exposure   $1.90
new delta           $0.50
hard ceiling        $2.00
```

from being incorrectly accepted merely because the new order itself is below the cap.

Company Risk remains above execution.

## Pause semantics

The planner supports:

```text
allow_new_risk = false
```

When a Company Cell is paused:

- a target above current exposure is clamped to current exposure;
- no new entry/increase occurs;
- reductions remain permitted;
- flat targets remain permitted;
- stop-floor and emergency exits remain possible.

This is the V4 execution-level enforcement behind Company V3 pause semantics.

## Risk-reducing safety

CompanyRiskGovernor now checks `risk_reducing` before requiring Trader status `ACTIVE`.

An assigned Trader that is:

- PAUSED;
- HALTED;

may still be reduced/flattened.

A RETIRED Trader remains invalid.

This fixes the previous failure mode where a safety action could be blocked solely because the Trader was no longer ACTIVE.

## C.A.O.S research / backtest

Research now exposes the same execution vocabulary.

### current_decision

```text
current_decision(...)
    ->
StrategyDecision
```

### target_position_series

Produces one `TargetPosition` per historical bar.

### execution_plan_series

Produces one `ExecutionPlan` per historical bar using the same resolver/planner used by Paper.

It is intended for state-transition diagnostics.

### backtest_execution_trace

Maps the exact existing C.A.O.S backtest trade log into:

```text
entry:
  StrategyDecision
  TargetPosition
  ExecutionPlan

exit:
  StrategyDecision
  TargetPosition
  ExecutionPlan
  exit reason
```

This preserves exact backtest exits such as:

- stop;
- target;
- signal;
- end.

The normal BacktestResult remains available and compatible.

## C.A.O.S PaperRunner

The original C.A.O.S PaperRunner now uses:

```text
current_decision
      ->
resolve_target_position
      ->
plan_execution
      ->
PaperBroker
```

Actions can now include:

```text
open_long
increase_long
reduce_long
close_long
emergency_close
```

Returned action records include:

- decision;
- target;
- plan;
- fill.

Existing hard RiskEngine gates remain active.

## Trade Company Paper

CompanyPaperBook uses the same Execution Fabric.

Each Trader cycle now records:

```text
decision
target
plan
fill
```

The Company-specific resolver constrains target notional using:

```text
requested Trader sizing
CompanyRisk max target
per-account C.A.O.S Risk max position
```

The smallest valid ceiling wins.

### Rebalancing

Changing:

```text
Trader A
requested size 20%
        ->
requested size 10%
```

while the long strategy remains active produces:

```text
reduce_long
```

instead of:

```text
close_long
open_long
```

## Execution price and delta quantity

Plans use a reference/mark price.

Venue execution may include modeled cost/slippage.

For sells, the fabric converts target delta to quantity at the reference price and then uses the execution price for the actual quote notional. This prevents a worse sell execution price from accidentally requesting more quantity than the position owns.

## Plan identity and future idempotency

ExecutionPlan has a deterministic `plan_id`.

The same canonical plan produces the same ID.

This provides the basis for future durable execution/idempotency.

Current Binance Spot TESTNET translation uses:

```text
newClientOrderId = plan_id
```

within Binance client-order-ID length boundaries.

Durable external-broker intent storage is still a later production-readiness concern.

## Human-gated TESTNET

`HumanTestnetExecutor` now supports:

```text
execute_plan(plan)
```

The plan is converted into a Binance Spot TESTNET order:

```text
buy plan  -> Buy
sell plan -> Sell
risk_reducing SELL -> allowed Spot reduction
plan_id -> orderLinkId
```

The existing human gate is unchanged:

```text
ARM TESTNET
```

Without the gate, execution is rejected.

The client remains hard-locked to:

```text
https://testnet.binance.vision
```

The TESTNET client rejects production Binance hosts. The separate production-readonly client cannot submit orders.

## LIVE

Company V4 does **not** implement a LIVE execution adapter.

There is deliberately no:

```text
LiveExecutor
execute_live_plan
auto_arm_live
```

A future LIVE adapter must consume ExecutionPlan behind Company Risk, C.A.O.S Risk, Compliance and explicit production-readiness gates.

## Observability

Trade Company status now includes:

```text
execution_fabric:
  version
  last_plans
```

Read-only inspection is exposed through:

```text
CompanyControlPort.get_execution_plans()
```

CLI:

```text
caos company execution-plans
```

The Themed City Trader detail shows:

- Execution Fabric version;
- latest plan action;
- desired target;
- effective target;
- order delta;
- risk-reducing flag;
- plan ID.

No broker credential/raw-order surface is added.

## Persistence

The last per-Trader execution plans are included in Company Paper checkpoint state.

Older checkpoints without `last_plans` restore with an empty plan registry.

## Compatibility

Existing interfaces remain available:

- `current_signal`;
- normal `backtest`;
- raw human TESTNET CLI surface;
- PaperBroker;
- CompanyControlPort;
- Company Cell Protocol;
- Themed City.

The Execution Fabric is added underneath/alongside these surfaces rather than forcing unrelated callers to migrate immediately.

## Acceptance criteria

Company V4 is complete when:

1. Execution Fabric has an explicit version;
2. StrategyDecision exists and is venue-independent;
3. TargetPosition exists and represents final desired exposure;
4. ExecutionPlan represents delta execution;
5. decision and plan IDs are deterministic;
6. target resolution enforces requested size and hard ceiling;
7. planner supports hold/increase/reduce/close;
8. planner can block new risk while allowing reductions;
9. Company Risk validates aggregate final targets for increases;
10. risk-reducing exits work for assigned PAUSED/HALTED Traders;
11. quant research exposes StrategyDecision;
12. historical target series uses TargetPosition;
13. historical plan series uses ExecutionPlan;
14. exact backtest trade logs map into entry/exit Execution Fabric traces;
15. C.A.O.S PaperRunner uses the Execution Fabric;
16. Trade Company Paper uses the Execution Fabric;
17. Company Paper supports partial rebalance by delta;
18. Company pause cannot create new risk through the Fabric;
19. Binance Spot TESTNET can translate/execute the same ExecutionPlan;
20. TESTNET still requires explicit human arming;
21. TESTNET remains hard-locked to Binance Spot Testnet;
22. LIVE remains unavailable;
23. plan IDs are propagated as TESTNET idempotency/link IDs;
24. latest plans are visible in Company status/control/CLI;
25. latest plan is visible in the Themed City Trader detail;
26. plan state restores safely from Company checkpoints;
27. old checkpoints without plan data remain compatible;
28. all previous Company V2/V3/Themed City/C.A.O.S tests remain green;
29. dedicated Execution Fabric tests are green;
30. CLI smoke includes the Execution Plan inspection surface;
31. no merge to `main` occurs without explicit user approval.

## Non-goals

V4 does not implement:

- autonomous LIVE execution;
- exchange reconciliation for real money;
- durable broker intent/outbox;
- broker retry/idempotency recovery across network failures;
- short execution;
- multi-leg orders;
- smart order routing;
- exchange-specific lot-size/step-size discovery;
- automatic TESTNET execution by the Company daemon.

These belong to later production-readiness work.


## Validation result

Final validated implementation:

```text
Ran 110 tests
OK

CI: SUCCESS
CLI smoke: SUCCESS
Company execution-plans smoke: SUCCESS
Binance Spot TESTNET plan adapter tests: SUCCESS
Backtest Execution Fabric trace tests: SUCCESS
Company Paper delta rebalance tests: SUCCESS
Checkpoint compatibility tests: SUCCESS
```

The validated branch remains `feature/trade-company`.

No merge to `main` has occurred.

**COMPANY V4 — EXECUTION FABRIC: COMPLETE**
