from __future__ import annotations

import argparse
import json
import math
import os
import random

from .dashboard import serve
from .domain import Mandate, MarketBar
from .llm import (
    OllamaClient,
    OpenAICompatClient,
    StaticLLM,
)
from .orchestrator import CAOS


def synthetic_bars(
    n: int = 500,
    seed: int = 11,
) -> list[MarketBar]:
    rng = random.Random(seed)
    p = 100.0
    bars: list[MarketBar] = []
    for i in range(n):
        drift = 0.12 * math.sin(i / 25.0) + 0.035
        shock = rng.gauss(0.0, 0.65)
        nxt = max(
            1.0,
            p * (1.0 + (drift + shock) / 100.0),
        )
        high = max(p, nxt) * 1.002
        low = min(p, nxt) * 0.998
        bars.append(
            MarketBar(
                i,
                p,
                high,
                low,
                nxt,
                1000 + rng.random() * 100,
            )
        )
        p = nxt
    return bars


def build_caos(args) -> CAOS:
    if args.provider == "ollama":
        llm = OllamaClient(
            args.model,
            args.base_url
            or "http://127.0.0.1:11434",
        )
    elif args.provider == "openai-compatible":
        llm = OpenAICompatClient(
            args.model,
            args.base_url
            or "http://127.0.0.1:1234/v1",
            os.getenv("CAOS_API_KEY", "local"),
        )
    else:
        llm = StaticLLM(
            '{"tool":"status","args":{}}'
        )
    c = CAOS(llm)
    c.set_mandate(
        Mandate(
            args.capital,
            args.max_dd,
            "consistency",
            6,
            args.max_position,
        )
    )
    c.load_bars("DEMOUSDT", synthetic_bars())
    return c


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="caos",
        description=(
            "C.A.O.S local-LLM quantitative lab"
        ),
    )
    p.add_argument(
        "--provider",
        choices=[
            "ollama",
            "openai-compatible",
            "static",
        ],
        default=os.getenv(
            "CAOS_PROVIDER",
            "ollama",
        ),
    )
    p.add_argument(
        "--model",
        default=os.getenv(
            "CAOS_MODEL",
            "qwen3:8b",
        ),
    )
    p.add_argument(
        "--base-url",
        default=os.getenv("CAOS_BASE_URL"),
    )
    p.add_argument(
        "--capital",
        type=float,
        default=1000.0,
    )
    p.add_argument(
        "--max-dd",
        type=float,
        default=15.0,
    )
    p.add_argument(
        "--max-position",
        type=float,
        default=20.0,
    )
    sub = p.add_subparsers(
        dest="cmd",
        required=True,
    )
    sub.add_parser("status")
    sub.add_parser("demo")
    chat = sub.add_parser("chat")
    chat.add_argument("message", nargs="+")
    dash = sub.add_parser("dashboard")
    dash.add_argument(
        "--port",
        type=int,
        default=5190,
    )
    dash.add_argument(
        "--no-browser",
        action="store_true",
    )
    return p


def main() -> None:
    args = parser().parse_args()
    c = build_caos(args)
    if args.cmd == "status":
        print(
            json.dumps(
                c.status(),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "demo":
        print(
            json.dumps(
                c.tool_mine("DEMOUSDT"),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "chat":
        print(
            json.dumps(
                c.handle(" ".join(args.message)),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "dashboard":
        server = serve(
            c,
            port=args.port,
            open_browser=not args.no_browser,
        )
        print(
            f"C.A.O.S dashboard: "
            f"http://127.0.0.1:{args.port}"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
