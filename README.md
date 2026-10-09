# C.A.O.S

**Cognitive Autonomous Orchestration System** — a clean-room, local-first quantitative research and paper-trading platform whose orchestrator is a **local LLM**, not a hosted assistant.

The design goal is **"fazer igual, mas não copiar"**: reproduce useful observable architectural ideas (specialized desks, deterministic quantitative tools, hard risk/compliance gates, paper execution and expected-vs-real supervision) with original code and a different internal architecture.

> Current milestone: **v0.8.9 standalone Trade Company with managed Forecast/Sentiment Oracles, GitHub self-update, autonomous market/timeframe/strategy selection, live Trader charts, editable Company policy, lateral natural-language LLM chat, managed Ollama and human-confirmed REAL execution**. The Arcane Nexus can now configure Kronos-small and Chronos-2 forecast specialists plus ModernFinBERT sentiment through a separate managed runtime. Forecast evidence may conservatively reduce AUTO rankings when it contradicts a long setup; it never creates an order or increases exposure by itself. ModernFinBERT feeds the existing News Intelligence sentiment path when loaded.

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

The LLM chooses what to inspect or run. Python computes the numbers and enforces rules. Broker credentials are never part of the LLM context, execution mode cannot be changed by the LLM, production order confirmations are not exposed through the Company Cell, and a kill-switch can always make the system safer.

## Requirements

- Python 3.11+
- Optional: Ollama, LM Studio, llama.cpp server, vLLM, LocalAI, or another OpenAI-compatible local server

## Windows installer

For normal Windows use, Python is not required. The Windows build bundles its own runtime and installs:

- `CAOS-Trade-Company.exe` — graphical launcher, first-run wizard, manually started PAPER operations loop and Arcane Trading City;
- `caos.exe` — administrative CLI using the same installed Company state;
- `ollama\` — the official portable Ollama runtime used only by the Trade Company managed LLM service;
- Start Menu shortcuts, with optional desktop shortcut and optional sign-in autostart.

The managed Ollama server uses `http://127.0.0.1:11435`, separate from the normal Ollama default port `11434`. Its models are stored under `%LOCALAPPDATA%\CAOS\ollama-models`.

Install flow:

```text
CAOS-Setup.exe
    -> install under %LOCALAPPDATA%\Programs\CAOS
    -> launch C.A.O.S Trade Company
    -> complete the Founding Charter
    -> city opens automatically in the browser
```

On first launch the **Founding Charter** configures Company capital, Trader bucket/stop floor, exposure limits, operational Trader cap, markets, daemon cadence and the optional local AI provider.

Runtime state is stored outside the program directory:

```text
%LOCALAPPDATA%\CAOS\caos.db
%LOCALAPPDATA%\CAOS\launcher.json
```

This means uninstalling/reinstalling the application does not automatically delete the Company state. The packaged `caos.exe` also defaults to this same database.

Broker credentials are intentionally **not stored by the installer or first-run wizard**. Binance profiles created later in the Broker Embassy store secrets in Windows Credential Manager. Production execution is available only through the local **REAL · MANUAL** gate and still requires a separate human confirmation for every submitted order.

The current installer is unsigned, so Windows SmartScreen may show a warning until code signing is added.

### GitHub self-update

Starting with **v0.8.8**, the installed Windows application has **⚙ Settings → Update Center · GitHub Releases**.

The updater:

- checks the stable `latest` release of `baenreiiryn/C.A.O.S`;
- downloads `CAOS-Update.zip`, not the full Ollama-bearing installer;
- verifies the package against the SHA-256 in `CAOS-Update.json`;
- refuses to install while the Company is not **STOPPED**, while a PAPER order/position is open, or while external/REAL execution is unresolved;
- closes the Trade Company, backs up the currently installed executables, replaces `CAOS-Trade-Company.exe` and `caos.exe`, and relaunches;
- rolls the two executables back if the replacement step fails.

The update package deliberately does **not** replace:

```text
%LOCALAPPDATA%\CAOS\caos.db
%LOCALAPPDATA%\CAOS\launcher.json
%LOCALAPPDATA%\CAOS\ollama-models
Windows Credential Manager
```

The portable Ollama runtime under the program directory is also left untouched by normal lightweight updates. The full `CAOS-Setup.exe` remains attached to every GitHub Release for cases where the bundled runtime itself must be refreshed.

**v0.8.8 is the one-time bridge release:** installations older than v0.8.8 must install v0.8.8 normally once. Future releases can then be pulled from GitHub by the application itself.

### Persistent settings after onboarding

The Founding Charter is only the first-run onboarding. After installation, configuration remains available from the **⚙ Settings** button in the Arcane Trading City.

**Arcane Nexus / LLM settings** supports:

- `static`, managed `ollama`, and `openai-compatible` providers;
- Start/Stop controls for the Ollama runtime bundled with Trade Company;
- a native Windows picker for local `.gguf` files;
- one-click GGUF import, registration and selection inside the managed Ollama model store;
- model and base-URL changes without resetting the Company;
- model discovery for Ollama (`/api/tags`) and OpenAI-compatible servers (`/models`);
- connection testing;
- optional OpenAI-compatible API key stored in Windows Credential Manager.

**Broker Embassy** supports Binance Japan / Spot profiles. `spot-testnet` can be used for autonomous test execution after you explicitly select TESTNET mode. `production-readonly` authenticates a real account without allowing order submission. `production-manual` enables the REAL proposal workflow: agents can prepare production orders, but each intent must be individually confirmed in the local Execution Gate before it is submitted.

Broker API keys and secrets are stored in **Windows Credential Manager**, not in `launcher.json` or `caos.db`. The packaged `caos.exe` automatically loads credentials from the active Binance Spot Testnet profile, so PowerShell environment-variable setup is not required when that profile is configured in the installed application.

**Whispering Tankard / News Sources** is also persistent after onboarding. Fresh installations start with enabled feeds from CoinDesk, Cointelegraph, Decrypt, CryptoSlate, Nasdaq Markets, Investing.com Market News, U.S. SEC press releases, Federal Reserve press releases, Bank of Japan updates and Japan Financial Services Agency updates. Settings can enable/disable/remove sources, restore defaults, test a feed, preview headlines, or paste a normal HTTPS news-site URL and let C.A.O.S discover its RSS/Atom feed.

Changing the active broker is blocked while unresolved external execution intents exist.

Installing v0.8.0 over v0.7.3 or v0.7.2 preserves:

```text
%LOCALAPPDATA%\CAOS\caos.db
%LOCALAPPDATA%\CAOS\launcher.json
```

so existing Treasury, Traders, research, rollout and reliability state remain intact. Existing installations without a `news_sources` field automatically receive the shipped default news catalog.

## Development install

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

The Windows Trade Company installer includes a managed Ollama runtime. In the Arcane Trading City open **⚙ Settings → Arcane Nexus · Managed Ollama**, choose a local `.gguf`, click **Apply Local Model**, then use **Start Ollama** / **Stop Ollama** as needed. No separate Ollama installation or terminal is required.

For CLI/development use, an external Ollama server is still supported:

```bash
ollama serve
ollama pull qwen3:8b
caos --provider ollama --model qwen3:8b chat "analise o regime de DEMOUSDT"
```

External Ollama defaults to `http://127.0.0.1:11434`; the Trade Company managed runtime uses `http://127.0.0.1:11435`.

## Managed Forecast / Sentiment Oracles

Windows v0.8.9 adds **⚙ Settings → Arcane Nexus · Oracles**.

Available specialists:

- **Kronos-small** — finance-specific OHLCV/K-line forecast evidence; recommended.
- **Chronos-2** — independent general time-series baseline; optional.
- **ModernFinBERT** — financial-news sentiment; recommended.

The specialist runtime is isolated from the main application and runs on localhost port `11436`. The runtime uses CPU/RAM by default so the managed LLM can retain GPU VRAM. Model weights are cached under:

```text
%LOCALAPPDATA%\CAOS\expert-models
```

Fresh launcher configurations enable Kronos + FinBERT by default, while Chronos-2 remains optional. Enabling an oracle only configures it; **Download / Load Enabled** explicitly downloads/loads model weights for that session. If FinBERT is not loaded, Company News Intelligence falls back to its existing deterministic heuristic. If forecast oracles are not loaded, AUTO selection continues using technical/backtest/news evidence normally.

When forecast oracles are loaded, the Scout consults them only for a small set of top AUTO candidates. A bearish forecast ensemble may reduce an opportunity score; bullish oracle evidence does not create an opportunity, increase the requested position, bypass technical validation, or bypass any risk/execution gate.

The full v0.8.9 installer contains the expert sidecar. Users updating from v0.8.8 through the lightweight updater can install the sidecar separately from the same GitHub Release using **Install Expert Runtime**, without reinstalling C.A.O.S.

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

## News intelligence

The **Whispering Tankard / Bard of Rumors** reads configured RSS/Atom sources on a bounded cache interval and maps relevant headlines to Company markets.

Default sources cover:

- crypto: CoinDesk, Cointelegraph, Decrypt, CryptoSlate;
- stocks/markets: Nasdaq Markets, Investing.com Market News;
- official regulation/macro: U.S. SEC, Federal Reserve, Bank of Japan, Japan Financial Services Agency.

Users can add a direct RSS/Atom URL or paste a normal HTTPS news-site URL; C.A.O.S attempts feed discovery through HTML alternate-feed metadata and common feed paths.

News is deliberately asymmetric:

```text
positive news  -> context only; never increases exposure
negative news  -> may reduce opportunity confidence
trusted critical negative news -> may block NEW risk for that symbol
existing position reduction/exit -> remains allowed
news by itself -> never creates an opportunity or order
```

A custom user-added feed cannot trigger the hard new-risk block by itself; custom-source critical headlines are downgraded to caution/penalty unless the source is part of the built-in trusted catalog.

See [`docs/NEWS_INTELLIGENCE.md`](docs/NEWS_INTELLIGENCE.md).

## Public market data and paper automation

C.A.O.S uses the public Binance Spot REST API for candles and order-book data with no API key, plus a local SQLite store, portfolio scoring and a deterministic paper runner/daemon. The LLM is not called on every market tick.

## Trade Company standalone

C.A.O.S includes a standalone Trade Company layer above the core engine. It owns Treasury, Trader lifecycle, market allocation, Company risk, per-Trader paper accounts, recovery and autonomous daemon operation. Drizzt is not required.

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

Binance Spot Testnet can consume an ExecutionPlan only through the existing explicit human gate. Spot SELL plans must be risk-reducing; opening naked shorts is not supported. LIVE execution remains unavailable.

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

## Strategy Rollout (Company V6)

Research champions do not jump directly into production assignments. They pass through a controlled rollout:

```text
Research champion
    -> shadow
    -> paper_canary
    -> eligible
    -> explicit active
    -> future new assignments
```

Shadow produces decisions only. Paper canary uses an isolated virtual account and consumes no Treasury capital or Trader slot. Canary drawdown can automatically roll a release back.

An `eligible` release still cannot be assigned until an operator explicitly activates it. Once active, it is prioritized only for new opportunities on its symbol; existing Traders are never hot-swapped.

Rollback immediately blocks new risk/assignments for that research strategy. Existing positions are not force-closed; they may only drain/reduce and the assignment is released once flat.

Standalone inspection and controls:

```bash
caos --provider static company rollout
caos --provider static company rollout-sync
caos --provider static company rollout-process --symbol BTCUSDT
caos --provider static company rollout-activate <release-id>
caos --provider static company rollout-rollback <release-id>
```

The Tournament Arena in the themed city displays shadow/canary/eligible/active releases and exposes safe activate/rollback controls.

See [`docs/COMPANY_V6_STRATEGY_ROLLOUT.md`](docs/COMPANY_V6_STRATEGY_ROLLOUT.md).

## Production Reliability / Broker Reconciliation (Company V7)

ExecutionPlan-based external TESTNET submission now has a durable SQLite intent/outbox layer:

```text
ExecutionPlan
   -> PREPARED
   -> SUBMITTING (persisted before network)
   -> ACKNOWLEDGED
   -> RECONCILED
```

Ambiguous network outcomes become `UNCERTAIN` and are never automatically resent. Recovery queries Binance Spot Testnet by the same deterministic `plan_id` propagated as `newClientOrderId`, then resolves it through `origClientOrderId`.

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

## Binance Japan / Spot

Binance is the supported broker family in v0.8.0.

- `spot-testnet` — human-gated Binance Spot Testnet order submission and durable recovery;
- `production-readonly` — authenticate a real Binance Japan account and read safe account metadata; production order submission is blocked in code.

TESTNET orders still require the exact confirmation `ARM TESTNET`.

For development/CLI use without a Broker Embassy profile:

```bash
# Windows PowerShell
$env:BINANCE_TESTNET_API_KEY="..."
$env:BINANCE_TESTNET_API_SECRET="..."
caos --provider static testnet-order --confirm "ARM TESTNET" BTCUSDT BUY LIMIT 0.001 --price 50000
```

The TESTNET client is hard-locked to `https://testnet.binance.vision`. The production profile uses Binance Spot account APIs read-only; C.A.O.S refuses production order creation.

Because this adapter is Spot-only, a SELL ExecutionPlan is accepted only when it reduces an existing long position. Naked short positions are not supported.

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

## Safety boundaries in v0.8.0

- research, paper trading and explicitly armed Binance Spot TESTNET only;
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
