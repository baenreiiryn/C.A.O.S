# Goal: "fazer igual, mas não copiar"

## Definition of done for the executable clean-room milestone

C.A.O.S reaches the first executable goal when all items below are true:

- Clean-room codebase: no proprietary AlgoMaker code or package dependency.
- Local LLM can orchestrate the system through Ollama or an OpenAI-compatible local endpoint.
- Numerical work is deterministic and outside the LLM.
- QUANT provides backtest, simple strategy mining, walk-forward, Monte Carlo and cost stress.
- MACRO provides a deterministic regime classification.
- RISK enforces a configurable per-position cap and kill-switch.
- COMPLIANCE blocks live mode until a human-only action explicitly arms it.
- Paper broker executes simulated orders after risk validation.
- Supervisor measures expected-vs-real divergence.
- Local dashboard exposes desk and safety state on `127.0.0.1`.
- Public Bybit candles can be ingested without credentials.
- Strategy candidates can be scored into a portfolio.
- A deterministic paper daemon can refresh data and execute approved strategy state changes.
- QUANT, MACRO, NEWS, RISK, COMPLIANCE and SUPERVISOR exist as logical agents with individual tool boundaries.
- A bounded multi-step Goal loop can pursue a natural-language objective with the local LLM.
- Automated unit and end-to-end smoke tests pass on Python 3.11.
- GitHub Actions runs the same tests on push and pull request.

## Explicitly not claimed

Production live trading, exchange credential storage, complete strategy parity with any commercial product, and profitability are not part of the v0.1 acceptance criteria.


## Current status

The clean-room **research + autonomous paper desk milestone is implemented**. Full commercial-product parity is not claimed: production exchange execution, encrypted credential management, richer strategy families, order-book cost modelling and long-duration fault-injection validation remain separate future milestones.
