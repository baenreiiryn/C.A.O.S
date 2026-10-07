# C.A.O.S

**Cognitive Autonomous Orchestration System** — a clean-room, local-first quantitative research and paper-trading platform whose orchestrator is a **local LLM**, not a hosted assistant.

The design goal is **"fazer igual, mas não copiar"**: reproduce useful observable architectural ideas (specialized desks, deterministic quantitative tools, hard risk/compliance gates, paper execution and expected-vs-real supervision) with original code and a different internal architecture.

> Current milestone: **v0.1 paper/research core**. Live exchange execution is intentionally not enabled yet.

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

## Safety boundaries in v0.1

- research and paper trading only;
- configurable position cap (20% default);
- drawdown guard;
- kill-switch;
- human-only live gate exists in the architecture but no production broker adapter is shipped;
- LLM tool list cannot arm live, set broker secrets, or reset a kill-switch.

## Project documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/GOAL.md`](docs/GOAL.md)

## License

MIT for the original C.A.O.S code in this repository.
