# Specialist models in C.A.O.S

C.A.O.S does **not** use a finance-tuned LLM as the trading brain. The main orchestrator remains a local general-purpose model (Ollama or another OpenAI-compatible local endpoint). Finance models are optional specialists that produce evidence for deterministic research pipelines.

## Selected stack

### 1. Kronos-small — primary market forecast specialist

- Model: `NeoQuasar/Kronos-small`
- Role: OHLCV/K-line forecasting
- Size: about 24.7M parameters
- License: MIT
- Source: https://huggingface.co/NeoQuasar/Kronos-small
- Upstream: https://github.com/shiyu-coder/Kronos

Why selected: Kronos was built specifically for financial candlestick sequences and the upstream project reports training data from more than 45 exchanges. C.A.O.S treats its output as a quantitative feature, never as an order instruction.

Kronos is not packaged as a normal pip library upstream. Clone the official repository and point C.A.O.S at it:

```bash
git clone https://github.com/shiyu-coder/Kronos.git external/Kronos
python -m pip install -e ".[kronos-runtime]"
# Windows PowerShell:
$env:CAOS_KRONOS_PATH="$PWD\external\Kronos"
# Linux/macOS:
export CAOS_KRONOS_PATH="$PWD/external/Kronos"
```

Weights are loaded from Hugging Face on first use.

### 2. Chronos-2 — independent time-series baseline

- Model: `amazon/chronos-2`
- Role: general zero-shot time-series forecasting / probabilistic baseline
- Size: about 120M parameters
- License: Apache-2.0
- Source: https://huggingface.co/amazon/chronos-2

Install:

```bash
python -m pip install -e ".[chronos]"
```

C.A.O.S uses quantiles 0.1/0.5/0.9 so the supervisor can see a forecast interval, not just a point estimate.

### 3. ModernFinBERT — NEWS context

- Model: `neoyipeng/ModernFinBERT-base`
- Role: financial text sentiment
- Size: about 149M parameters
- License: Apache-2.0
- Source: https://huggingface.co/neoyipeng/ModernFinBERT-base

Install:

```bash
python -m pip install -e ".[sentiment]"
```

It is context only. Positive sentiment cannot override RISK, COMPLIANCE, failed robustness gates, or a kill-switch.

## Enable specialists

```bash
caos --experts kronos,chronos2,finbert models
caos --experts kronos,chronos2 --provider ollama --model qwen3:8b forecast BTCUSDT --expert kronos --horizon 12
caos --experts kronos,chronos2 --provider ollama --model qwen3:8b ensemble BTCUSDT --horizon 12
```

The symbol must have market data loaded in the current process. In Goal mode the orchestrator can call `fetch_market` first.

## Promotion gate: a model must earn influence

A model name or finance fine-tune is not evidence of alpha. Before a forecast expert is allowed to become a portfolio filter, run:

```bash
caos --experts kronos evaluate-expert BTCUSDT --expert kronos --horizon 6
```

The current qualification gate requires:

- at least 5 walk-forward windows;
- directional accuracy >= 55%;
- MAE no worse than the naive last-price forecast;
- no large systematic bias.

A failed expert remains available for research but should not affect portfolio selection.

## Ensemble policy

Kronos and Chronos-2 can be compared in an ensemble. The default research weights are 60/40 in favor of the finance-specific Kronos model. The `agreement_score` is only a dispersion heuristic and **must not be interpreted as probability of profit**.

## NEWS feeds

NEWS only reads RSS/Atom URLs configured by the human operator:

```bash
CAOS_NEWS_FEEDS="https://example.com/feed.xml,https://another.example/rss" \
caos --experts finbert --provider ollama --model qwen3:8b goal "analise as notícias configuradas"
```

The LLM cannot turn NEWS into an arbitrary URL-fetching tool.

## VRAM strategy

All three specialists are deliberately small compared with the main orchestrator. They should be loaded lazily and, when necessary, sequentially rather than keeping every model resident on the GPU. This preserves VRAM for the local orchestrator.

## What C.A.O.S deliberately did not select

Large "trading LLM" fine-tunes were not chosen as the execution brain. Natural-language fluency about markets is not a substitute for validated forecasting skill, realistic cost modelling, deterministic risk controls, or out-of-sample testing.
