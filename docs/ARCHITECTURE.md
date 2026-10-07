# C.A.O.S architecture

C.A.O.S is a clean-room implementation of a local-first quantitative trading laboratory. It reproduces observable product ideas — specialized desks, strategy research, risk gates, paper execution, expected-vs-real supervision, and a local control panel — without using proprietary source code.

## Design rule

The LLM is an orchestrator, not the trading kernel.

```text
Local LLM (Ollama / OpenAI-compatible)
             |
             v
      C.A.O.S Orchestrator
             |
   +---------+----------+-------------+
   |                    |             |
 Quant/Macro         Risk         Compliance
   |                    |             |
 deterministic      hard limits    human live gate
   +---------+----------+-------------+
             |
         Paper Broker
             |
        Supervisor
             |
     local HTTP dashboard
```

## Desks

- **QUANT** — backtest, candidate mining, walk-forward, Monte Carlo and cost stress.
- **MACRO** — local market-regime classifier. No LLM is required for numerical classification.
- **NEWS** — reserved context surface for locally supplied headlines or a future user-selected connector. It must not be allowed to bypass risk.
- **RISK** — position cap, drawdown guard and kill-switch.
- **COMPLIANCE** — blocks live mode unless an explicit human-only control surface arms it.
- **SUPERVISOR** — compares expected backtest behaviour against realized results.

## Security boundary

The local LLM never receives broker credentials. The list of LLM-callable tools intentionally excludes `human_arm_live`, broker credential operations and kill-switch reset. The LLM may activate the kill-switch because that only reduces risk.

## Local LLM providers

- Ollama: `POST /api/chat`
- OpenAI-compatible servers: `POST /v1/chat/completions`

The orchestration contract is strict JSON: one tool and one argument object. Deterministic code validates every tool call.

## Agent topology

The six visible desks are logical agents, not six mandatory LLM processes. They share one `LocalLLM` instance by default and receive different role prompts plus desk-specific tool allowlists. This is designed for single-GPU local deployments.

## Goal loop

`CAOS.run_goal()` repeatedly asks the local orchestrator for one safe next action, executes the deterministic tool, feeds state/results back, and stops when the model returns an explicit `finish` object or the bounded step budget is exhausted.

## Continuous paper loop

`PaperDaemon` refreshes public candles and evaluates already-approved strategies without invoking the LLM on every tick. This keeps execution deterministic and allows the supervisor/LLM to be reserved for anomalies and higher-level decisions.

## v0.3 scope

This milestone deliberately ships paper trading only, plus public Bybit market data, local persistence, logical desk agents, portfolio construction and bounded Goal orchestration. A real broker adapter belongs behind the same compliance boundary and should be added only after replay, fault-injection and exchange-sandbox tests exist.


## Specialist evidence plane

Optional Hugging Face specialists sit beside the deterministic engine, not above it:

```text
                  local general LLM
                         |
                  Goal orchestrator
                         |
       +-----------------+-----------------+
       |                                   |
deterministic tools                 specialist evidence
QUANT/RISK/COMPLIANCE      Kronos / Chronos-2 / ModernFinBERT
       |                                   |
       +-----------------+-----------------+
                         |
             robustness / qualification
                         |
                 portfolio + paper
```

A forecast expert is not allowed to create an order. Its first promotion gate is a walk-forward scorecard against a naive last-price baseline. NEWS sentiment is context-only.

## Execution realism

Public Bybit order-book depth is sampled to estimate spread, VWAP market impact and fees. The measured round-trip cost feeds strategy mining/cost stress and the non-fee portion is applied to paper fills.

## Persistence and fault isolation

Runtime checkpoints store mandate, portfolio, paper positions/fills/P&L, pending orders, kill-switch and measured costs in SQLite. The daemon refreshes each symbol independently; a failed symbol is excluded from that execution cycle rather than traded with stale data.

## TESTNET boundary

The authenticated Bybit adapter is hard-locked to `https://api-testnet.bybit.com`. A separate `ARM TESTNET` human gate is required. The testnet executor is not registered as an LLM tool. Production LIVE has no exchange adapter in this milestone.


## Planned Company layer

The current v0.5 engine is the shared trading substrate. The next Company layer must use **Treasury-owned capital**, not a parent-child financial tree.

```text
Trade Company
  Treasury / Capital Allocator
  Supervisor / Improvement Manager
  Market Scout / Market Regime
  Opportunity Registry
  Market Allocator
  Traders A-F
  Company Risk Governor
  Strategy Diversity
  Risk Engine
  Broker
```

Trader creation may keep genealogical metadata such as `spawned_from`, but capital settlement is always through Treasury. When a Trader is halted or retired, its residual bucket is reconciled and returned to Treasury Reserve. See [`COMPANY_ARCHITECTURE.md`](COMPANY_ARCHITECTURE.md).
