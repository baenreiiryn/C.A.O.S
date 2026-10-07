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

## v0.1 scope

This first milestone deliberately ships paper trading only. A real broker adapter belongs behind the same compliance boundary and should be added only after replay, fault-injection and exchange-sandbox tests exist.
