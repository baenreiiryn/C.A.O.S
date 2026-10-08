# Goal V2 — specialists + robust autonomous paper desk

## Goal

Extend the clean-room C.A.O.S implementation toward the observable capabilities of a professional autonomous quantitative desk while preserving the rule: **same useful idea, original implementation**.

Add open Hugging Face finance/time-series specialists only where they can demonstrate measurable value.

## Acceptance criteria

The Goal is complete when all of the following exist and the full CI suite is green:

- local general-purpose LLM remains the orchestrator;
- optional finance specialists are isolated behind adapters and lazy loading;
- Kronos-small is supported as a finance-specific OHLCV forecast expert;
- Chronos-2 is supported as an independent time-series baseline;
- ModernFinBERT is supported for NEWS sentiment only;
- forecast experts have a walk-forward qualification gate versus a naive baseline;
- specialist forecasts are evidence and cannot submit orders;
- LLM cannot place raw paper, testnet, or live orders;
- QUANT mines at least trend, mean-reversion, breakout and momentum families;
- portfolio construction rejects excessive strategy correlation;
- Binance Spot public order-book depth is used to estimate realistic execution cost;
- paper accounting tracks quantity, fees and realized P&L correctly;
- kill-switch can force risk-reducing exits while preventing new exposure;
- deterministic paper limit and stop primitives exist;
- runtime state can checkpoint and recover from SQLite;
- paper daemon isolates per-symbol data failures instead of trading stale data;
- SUPERVISOR compares expected backtest behavior with realized paper behavior;
- NEWS consumes only human-configured RSS/Atom feeds;
- Binance Spot TESTNET client is hard-locked to `testnet.binance.vision`;
- TESTNET requires a separate explicit human gate and is never exposed as an LLM tool;
- production LIVE remains human-gated and is intentionally not implemented by this milestone;
- all automated tests and CLI smoke tests pass in GitHub Actions.

## Model promotion policy

A specialist is **integrated** when its adapter and evaluation path are implemented. It becomes **trusted evidence** only after it passes the walk-forward qualification gate on the intended market/timeframe. It becomes a **portfolio filter** only after repeated out-of-sample and paper validation. These states must not be conflated.

## Non-goals

- claiming profitability;
- treating model confidence as probability of profit;
- allowing an LLM or news sentiment model to bypass RISK/COMPLIANCE;
- copying proprietary AlgoMaker engine code;
- enabling production-money execution before separate long-duration validation.


## Status: COMPLETE

Goal V2 is complete as of C.A.O.S v0.5.0.

Acceptance evidence at closure:

- package installs successfully on Python 3.11 in GitHub Actions;
- the complete unit/integration suite passes;
- CLI smoke test passes;
- the specialist-model layer is optional and lazy;
- TESTNET is human-gated and hard-locked away from production;
- production LIVE remains intentionally out of scope until a separate validation goal authorizes it.

Important: completion means the **software architecture and validation machinery** are implemented and tested. It does not mean Kronos, Chronos-2 or any strategy has proven profitability. Each specialist must still pass its market/timeframe-specific walk-forward qualification on the operator's real historical dataset before promotion.
