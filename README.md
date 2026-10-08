# C.A.O.S

**Cognitive Autonomous Orchestration System** — a clean-room, local-first quantitative research and paper-trading platform whose orchestrator is a **local LLM**, not a hosted assistant.

The design goal is **"fazer igual, mas não copiar"**: reproduce useful observable architectural ideas (specialized desks, deterministic quantitative tools, hard risk/compliance gates, paper execution and expected-vs-real supervision) with original code and a different internal architecture.

> Current milestone: **v0.5 specialist-assisted autonomous paper desk**. Research, public market/order-book data, multi-family strategy mining, correlation-aware portfolio construction, optional Hugging Face specialists, local-LLM Goal orchestration, crash recovery, autonomous paper cycles and a human-gated Bybit TESTNET path are implemented. Production LIVE remains deliberately unavailable.

## Why it is built this way

C.A.O.S separates reasoning from money-moving mechanics:

```text
Ollama / local OpenAI-compatible LLM
              |
              v
      local orchestrator
              |
    deterministic tools
  QUANT · MACRO · RISK · COMPLIANCE
              |
         paper broker
              |
          supervisor
              |
     localhost dashboard
```

The LLM chooses what to inspect or run. Python computes the numbers and enforces rules. Broker credentials are never part of the LLM context, live mode cannot be armed by the LLM, and a kill-switch can always make the system safer.

## Requirements

- Python 3.11+
- Optional: Ollama, LM Studio, llama.cpp server, vLLM, LocalAI, or another OpenAI-compatible local server

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
```

## Run without any LLM

```bash
caos --provider static status
caos --provider static demo
```

## Ollama

```bash
ollama serve
ollama pull qwen3:8b
caos --provider ollama --model qwen3:8b chat "analise o regime de DEMOUSDT"
```

The default Ollama endpoint is `http://127.0.0.1:11434`.

## OpenAI-compatible local server

```bash
caos --provider openai-compatible \
  --model your-local-model \
  --base-url http://127.0.0.1:1234/v1 \
  chat "mostre o status"
```

This works with local servers that implement `/v1/chat/completions`.

## Goal mode

Give the local model a result to pursue across multiple safe tool calls:

```bash
caos --provider ollama --model qwen3:8b goal "baixe BTCUSDT, analise, mine estratégias e monte uma carteira paper"
```

The loop is bounded by a maximum step budget and can only call tools exposed by C.A.O.S. It cannot arm LIVE, set broker credentials or reset the kill-switch.

## Logical desks

The same local model can be multiplexed into specialized roles, so a single GPU does not need six model copies:

- QUANT — research, backtests and robustness
- MACRO — regime and volatility context
- NEWS — qualitative context only
- RISK — exposure and emergency stop
- COMPLIANCE — policy boundary audit
- SUPERVISOR — system-wide health and divergence monitoring

Example:

```bash
caos --provider ollama --model qwen3:8b desk risk "audite o estado atual"
```

## Specialist models

C.A.O.S can optionally use three small local specialists as evidence:

- **Kronos-small** — finance-specific OHLCV/K-line forecasting;
- **Chronos-2** — independent general time-series forecast baseline;
- **ModernFinBERT** — financial NEWS sentiment.

They do not replace the orchestrator and cannot place orders. See [`docs/MODELS.md`](docs/MODELS.md).

```bash
caos models
caos --experts kronos,chronos2,finbert status
```

Before forecast evidence is promoted into portfolio logic, C.A.O.S can walk-forward evaluate it against a naive last-price baseline.

## Public market data and paper automation

C.A.O.S includes a public Bybit kline client that requires no API key, a local SQLite store, portfolio scoring and a deterministic paper runner/daemon. The LLM is not called on every market tick.

## Trade Company standalone

The `feature/trade-company` branch adds a standalone Company layer above C.A.O.S. It owns Treasury, Trader lifecycle, market allocation, Company risk, per-Trader paper accounts, recovery and autonomous daemon operation. Drizzt is not required.

Initialize once:

```bash
caos --provider static company init \
  --company-capital 20 \
  --targets "BTCUSDT:long:momentum,ETHUSDT:long:trend"
```

Then restore and operate from the saved checkpoint:

```bash
caos --provider static company status
caos --provider static company once
caos --provider static company run
caos --provider static company dashboard
```

The standalone dashboard defaults to `http://127.0.0.1:5191`. The existing technical C.A.O.S dashboard remains on port 5190.

Safe operator controls include Trader pause/resume, runtime Trader concurrency limit, per-Trader exposure configuration and emergency stop. The Company surface does not expose broker credentials, raw broker orders, LIVE arming or kill-switch reset.

## Company Cell Protocol (V3)

Trade Company is also exposed as the first generic autonomous **Company Cell**. This is the future integration boundary for Drizzt and for other independent companies.

Generic cell inspection:

```bash
caos --provider static company cell-manifest
caos --provider static company cell-status
caos --provider static company cell-health
caos --provider static company cell-metrics
caos --provider static company cell-alerts
caos --provider static company cell-report
```

Generic safe controls:

```bash
caos --provider static company cell-pause
caos --provider static company cell-resume
```

The themed city HTTP server also exposes the versioned protocol under `/api/cell/v1/*`.

Cell-wide pause blocks new opportunities, assignments, new risk entries and Trader expansion while continuing market refresh, audits, stop-floor handling and risk-reducing exits. Resume cannot bypass active Company or C.A.O.S kill switches.

The Cell Protocol never exposes broker credentials, raw orders, LIVE arming or kill-switch reset.

See [`docs/COMPANY_V3_CELL_PROTOCOL.md`](docs/COMPANY_V3_CELL_PROTOCOL.md).

## Execution Fabric (Company V4)

Trade Company and the original C.A.O.S paper runner share a versioned, venue-agnostic execution pipeline:

```text
StrategyDecision
      ->
TargetPosition
      ->
ExecutionPlan
      -> paper / human-gated TESTNET / future venue adapters
```

`ExecutionPlan` expresses only the delta between current exposure and the allowed target. It supports hold, increase, reduce and close, with deterministic plan IDs.

Research/backtest can produce target/plan traces using the same schema. Company Paper stores the latest plan per Trader and exposes it through:

```bash
caos --provider static company execution-plans
```

The fantasy city Trader detail also shows the latest Execution Plan.

Bybit TESTNET can consume an ExecutionPlan only through the existing explicit human gate. LIVE execution remains unavailable.

See [`docs/COMPANY_V4_EXECUTION_FABRIC.md`](docs/COMPANY_V4_EXECUTION_FABRIC.md).

## Research Factory (Company V5)

Trade Company includes a controlled autonomous strategy-research pipeline:

```text
Hypothesis
   -> Candidate Generator
   -> C.A.O.S Backtest + Robustness
   -> Execution Fabric research trace
   -> Training Arena
   -> Champion / Challenger decision
   -> Promote or Reject
```

The built-in generator works fully offline. Optional bridge adapters are defined for Qlib and RD-Agent callbacks without making either project a required dependency.

Standalone commands:

```bash
caos --provider static company research
caos --provider static company research-hypothesis --symbol BTCUSDT --family momentum --thesis "test a momentum variant"
caos --provider static company research-run <hypothesis-id>
caos --provider static company research-from-improvements --symbol BTCUSDT --family momentum
```

Promotion only registers a qualified strategy/champion. It does not spawn Traders, allocate Treasury capital, assign markets or execute orders.

The Arcane Workshop in the themed city displays hypotheses, candidates, champions and promotion decisions.

See [`docs/COMPANY_V5_RESEARCH_FACTORY.md`](docs/COMPANY_V5_RESEARCH_FACTORY.md).

## Strategy Rollout (Company V6)\n\nResearch champions do not jump directly into production assignments. They pass through a controlled rollout:\n\n```text\nResearch champion\n    -> shadow\n    -> paper_canary\n    -> eligible\n    -> explicit active\n    -> future new assignments\n```\n\nShadow produces decisions only. Paper canary uses an isolated virtual account and consumes no Treasury capital or Trader slot. Canary drawdown can automatically roll a release back.\n\nAn `eligible` release still cannot be assigned until an operator explicitly activates it. Once active, it is prioritized only for new opportunities on its symbol; existing Traders are never hot-swapped.\n\nRollback immediately blocks new risk/assignments for that research strategy. Existing positions are not force-closed; they may only drain/reduce and the assignment is released once flat.\n\nStandalone inspection and controls:\n\n```bash\ncaos --provider static company rollout\ncaos --provider static company rollout-sync\ncaos --provider static company rollout-process --symbol BTCUSDT\ncaos --provider static company rollout-activate <release-id>\ncaos --provider static company rollout-rollback <release-id>\n```\n\nThe Tournament Arena in the themed city displays shadow/canary/eligible/active releases and exposes safe activate/rollback controls.\n\nSee [`docs/COMPANY_V6_STRATEGY_ROLLOUT.md`](docs/COMPANY_V6_STRATEGY_ROLLOUT.md).\n\n## Production Reliability / Broker Reconciliation (Company V7)

ExecutionPlan-based external TESTNET submission now has a durable SQLite intent/outbox layer:

```text
ExecutionPlan
   -> PREPARED
   -> SUBMITTING (persisted before network)
   -> ACKNOWLEDGED
   -> RECONCILED
```

Ambiguous network outcomes become `UNCERTAIN` and are never automatically resent. Recovery queries Bybit TESTNET by the same deterministic `plan_id` propagated as `orderLinkId`, checking real-time orders and then order history.

```bash
caos --provider static company reliability
caos --provider static execution-intents
caos --provider static testnet-recover
```

If both broker lookups confirm no order, an operator may explicitly resolve the stuck intent without retrying:

```bash
caos --provider static testnet-abandon-missing <intent-id> --confirm "ABANDON MISSING TESTNET INTENT"
```

The journal stores order intent/payload state but never API credentials. It is independent from the normal Company checkpoint so crash recovery cannot erase external execution history.

The Chronicle Vault in the themed city displays execution intents and raises attention when broker reconciliation is required. Its HTTP reliability endpoint is read-only; broker credentials and submit controls remain absent.

Company V7 does not enable autonomous TESTNET or LIVE deployment. Human TESTNET arming is still required for any money-moving submit, and LIVE remains unavailable.

See [`docs/COMPANY_V7_PRODUCTION_RELIABILITY.md`](docs/COMPANY_V7_PRODUCTION_RELIABILITY.md).

## Bybit TESTNET

TESTNET is a separate human-only execution surface. The client rejects production Bybit hosts in code and TESTNET orders require the exact confirmation `ARM TESTNET`.

Set credentials in environment variables; do not pass secrets to the LLM:

```bash
# Windows PowerShell
$env:BYBIT_TESTNET_API_KEY="..."
$env:BYBIT_TESTNET_API_SECRET="..."
caos --provider static testnet-order --confirm "ARM TESTNET" BTCUSDT Buy Limit 0.001 --price 50000
```

The `testnet-order` command can only target `https://api-testnet.bybit.com`.

## Dashboard

```bash
caos --provider static dashboard
```

Open `http://127.0.0.1:5190`.

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions executes the same suite on every push and pull request.

## Safety boundaries in v0.5

- research, paper trading and explicitly armed Bybit TESTNET only;
- configurable position cap (20% default);
- drawdown guard;
- kill-switch;
- human-only LIVE gate exists in the architecture but no production broker adapter is shipped;
- raw paper orders, TESTNET arming/orders and LIVE actions are excluded from the LLM tool surface;
- LLM tool list cannot arm live, set broker secrets, or reset a kill-switch.

## Project documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/GOAL.md`](docs/GOAL.md)
- [`docs/GOAL_V2.md`](docs/GOAL_V2.md)
- [`docs/MODELS.md`](docs/MODELS.md)
- [`docs/COMPANY_ARCHITECTURE.md`](docs/COMPANY_ARCHITECTURE.md)

## License

MIT for the original C.A.O.S code in this repository.
