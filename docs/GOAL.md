# Goal: "fazer igual, mas não copiar"

## Definition of done for v0.1

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
- Automated unit and end-to-end smoke tests pass on Python 3.11.
- GitHub Actions runs the same tests on push and pull request.

## Explicitly not claimed in v0.1

Production live trading, exchange credential storage, complete strategy parity with any commercial product, and profitability are not part of the v0.1 acceptance criteria.
