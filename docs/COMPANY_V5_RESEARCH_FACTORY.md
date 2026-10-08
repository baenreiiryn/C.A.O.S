# Company V5 — Research Factory

Status: **COMPLETE on `feature/trade-company`**

## Goal

Turn C.A.O.S + Trade Company into a controlled autonomous research pipeline:

```text
Hypothesis
   |
   v
Candidate Generator
   |
   v
C.A.O.S Backtest + Robustness
   |
   v
Execution Fabric Research Trace
   |
   v
Training Arena
   |
   v
Champion / Challenger
   |
   +--> Promote
   |
   +--> Reject
```

Research may discover and promote strategies, but it must never bypass Company safety or execute trades merely because a strategy won a research tournament.

## Version

```text
research-factory/v1
```

Implementation:

```text
src/caos/company/research.py
```

## Core entities

### ResearchHypothesis

Represents a research question:

- symbol;
- strategy family;
- thesis;
- source;
- optional parent strategy;
- lifecycle status.

### ResearchCandidate

Represents a generated StrategySpec before production registration.

Candidates remain isolated from the normal Company Strategy Registry until promotion.

### ResearchEvaluation

Uses the deterministic C.A.O.S stack:

- backtest;
- robustness;
- walk-forward;
- Monte Carlo tail;
- stressed costs;
- Execution Fabric trace summary.

A candidate can be:

```text
generated
qualified
rejected
promoted
```

### PromotionDecision

Records:

- symbol;
- challenger;
- prior champion;
- promoted/rejected;
- reason;
- Training Arena experiment ID when applicable.

## Candidate generators

### BuiltinGridGenerator

The default generator requires no external service or model.

It creates bounded variants for:

- trend;
- momentum;
- mean reversion;
- breakout.

It can also mutate around a parent StrategySpec.

Candidate count is bounded to avoid unbounded research workloads.

### External generator protocol

External research systems implement:

```text
ResearchCandidateGenerator.generate(...)
```

The generator can only return StrategySpec candidates.

It does not:

- approve candidates;
- register champions;
- assign Traders;
- allocate capital;
- execute trades.

### Qlib bridge

```text
QlibResearchGeneratorAdapter
provider id = qlib
```

This is a dependency-free callback bridge. Qlib is not imported or required by C.A.O.S.

### RD-Agent bridge

```text
RDAgentResearchGeneratorAdapter
provider id = rd_agent
```

This is also dependency-free. RD-Agent can be connected later without changing the Research Factory evaluation contract.

## Evaluation

Every candidate is evaluated with the existing deterministic quant stack.

A ResearchEvaluation contains:

```text
BacktestResult
RobustnessResult
Research score
Execution Fabric trace summary
Pass / fail
Reasons
```

The score is only a ranking aid.

A high score cannot override a failed robustness result.

## Execution Fabric integration

Research records the same execution representation introduced by Company V4.

For each candidate, the exact backtest trade log is mapped into:

```text
StrategyDecision
TargetPosition
ExecutionPlan
```

The Research Factory stores summary counts of entry/exit plans and the Fabric version.

Research never submits those plans to a broker.

## Training Arena integration

When a champion already exists, the best qualified challenger is compared in the existing TrainingArena using:

- same symbol;
- same market bars;
- same period;
- same starting capital;
- same cost assumptions;
- same drawdown mandate;
- same position ceiling.

The experiment contains only two named variants:

```text
champion
challenger
```

Promotion requires the challenger to:

- rank first in the fair tournament;
- pass robustness;
- meet the configured profit-factor requirement;
- stay within the allowed drawdown regression.

Otherwise the champion remains active in the research catalog.

## First champion

If no champion exists for a symbol, the highest-scoring qualified candidate may become the initial champion.

This registers its StrategySpec in CompanyStrategyRegistry and records the champion mapping.

It does not assign the new strategy to an existing Trader.

## Promotion safety boundary

Promotion means only:

```text
qualified candidate
      ->
CompanyStrategyRegistry
      +
research.champions[symbol]
```

Promotion does not:

- create a Trader;
- spawn an agent;
- move Treasury capital;
- create an Opportunity;
- change a live market assignment;
- create an ExecutionPlan for production;
- place a Paper order;
- place a TESTNET order;
- arm TESTNET;
- arm LIVE.

A separate future policy may decide when a champion becomes eligible for production use.

## Improvement Manager integration

The Improvement Manager can seed research hypotheses from relevant proposals.

Currently:

```text
run_diversity_experiment
       ->
ResearchHypothesis
```

The generated hypothesis records its source as:

```text
improvement:<proposal-id>
```

Seeding is idempotent for the same proposal.

Critically:

```text
Improvement proposal
      ->
Hypothesis only
```

It does not automatically run candidates or promote anything.

## Standalone research cycle

The Company exposes:

```text
submit_research_hypothesis(...)
run_research_cycle(...)
seed_research_from_improvements(...)
```

A research cycle performs:

1. generate bounded candidates;
2. evaluate each candidate;
3. select qualified challengers;
4. run champion/challenger tournament when required;
5. record promotion/rejection;
6. persist state.

If the symbol is not already loaded in a standalone process, the Company attempts to refresh public market data before research.

## Persistence

Research state is part of the normal Company checkpoint:

- hypotheses;
- candidates;
- evaluations;
- champions;
- promotion decisions.

Runtime generator objects are not serialized.

After restart, the built-in generator remains available and persisted research state is restored.

Older V2/V3/V4 checkpoints without a `research` field restore an empty Research Factory.

## Checkpoint integrity

Restore fails closed if:

- champion points to a missing registered strategy;
- candidate points to a missing hypothesis;
- candidate references a missing evaluation;
- evaluation references a missing candidate.

This prevents restoring a corrupted research lineage.

## Company Cell Protocol

Trade Company advertises:

```text
domain.trade.research
```

Generic Cell metrics now include:

- research_hypotheses;
- research_candidates;
- research_champions.

The supervisor report can mention Research Factory activity without understanding Trade Company internals.

## Standalone CLI

Inspect:

```text
caos company research
```

Create a hypothesis:

```text
caos company research-hypothesis \
  --symbol BTCUSDT \
  --family momentum \
  --thesis "test a lower-threshold momentum challenger"
```

Run the autonomous research cycle:

```text
caos company research-run <hypothesis-id>
```

Options include:

- generator;
- candidate limit;
- starting capital;
- cost bps.

Seed from Improvement Manager:

```text
caos company research-from-improvements \
  --symbol BTCUSDT \
  --family momentum
```

## Themed City

The Arcane Workshop now represents:

```text
ResearchFactory + ImprovementManager
```

It shows:

- hypothesis count;
- candidate count;
- evaluations;
- champions;
- recent promotion/rejection decisions;
- hypothesis scrolls;
- Improvement Manager proposals.

The Grand Tournament Arena continues to show actual TrainingArena experiments.

## Observability

Company status exposes:

```text
research
research_summary
```

Summary includes:

- version;
- hypothesis count;
- candidate count;
- candidate statuses;
- evaluation count;
- champions;
- promotion-decision count;
- registered generator IDs.

## Acceptance criteria

Company V5 is complete when:

1. Research Factory has an explicit version;
2. research hypotheses are first-class persisted objects;
3. candidates remain isolated from production Strategy Registry before promotion;
4. builtin candidate generation works without external dependencies;
5. generation is bounded;
6. parent-strategy mutation is supported;
7. external generator protocol is runtime-checkable;
8. Qlib has an optional dependency-free bridge;
9. RD-Agent has an optional dependency-free bridge;
10. external generators cannot bypass deterministic evaluation;
11. candidate evaluation uses C.A.O.S backtest;
12. candidate evaluation uses robustness gates;
13. evaluation records Execution Fabric research traces;
14. failed robustness cannot be promoted;
15. qualified candidates are ranked deterministically;
16. first qualified champion can be established;
17. existing champion is challenged through TrainingArena;
18. champion/challenger uses identical market/capital/cost assumptions;
19. promotion and rejection are persisted decisions;
20. promotion registers only the strategy/champion;
21. promotion does not create Traders, allocate capital or execute fills;
22. Improvement Manager can seed research hypotheses;
23. Improvement seeding is idempotent;
24. Improvement seeding does not automatically run research;
25. Company exposes safe research controls;
26. standalone CLI can inspect/create/run research;
27. standalone research can refresh public market data when needed;
28. Research Factory state survives checkpoint/restore;
29. old checkpoints without research restore safely;
30. corrupted research lineage fails closed on restore;
31. Company Cell advertises research capability and generic metrics;
32. Themed City Arcane Workshop displays real research state;
33. existing Training Arena remains the tournament engine;
34. existing Execution Fabric remains the research/execution vocabulary;
35. no raw broker or LIVE capability is added;
36. previous V2/V3/V4/Themed City regressions remain green;
37. dedicated V5 tests are green;
38. CLI smoke covers Research Factory inspection/hypothesis creation;
39. no merge to `main` occurs without explicit user approval.

## Non-goals

Company V5 does not:

- install Qlib;
- install RD-Agent;
- allow an LLM to promote a strategy by text alone;
- automatically replace strategies on active Traders;
- automatically allocate real capital to a champion;
- execute TESTNET/LIVE from research;
- train neural models from scratch;
- implement feature-store infrastructure;
- perform distributed research jobs;
- implement production strategy rollout/canary logic.

Those remain later stages after the research catalog is reliable.


## Validation result

Final validated implementation:

```text
Ran 120 tests
OK

CI: SUCCESS
CLI smoke: SUCCESS
Research Factory inspection smoke: SUCCESS
Research hypothesis creation smoke: SUCCESS
Builtin generator tests: SUCCESS
Qlib/RD-Agent bridge tests: SUCCESS
Backtest/robustness evaluation tests: SUCCESS
Execution Fabric research trace tests: SUCCESS
Champion/challenger promotion tests: SUCCESS
Promotion rejection tests: SUCCESS
Improvement Manager seeding tests: SUCCESS
Checkpoint compatibility/integrity tests: SUCCESS
```

The validated branch remains `feature/trade-company`.

No merge to `main` has occurred.

**COMPANY V5 — RESEARCH FACTORY: COMPLETE**
