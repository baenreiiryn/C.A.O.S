from __future__ import annotations

import argparse
import json
import math
import os
import random

from .dashboard import serve
from .desks import DeskCouncil
from .domain import Mandate, MarketBar
from .experts.registry import build_experts, recommended_stack
from .news import NewsAnalyzer, RSSNewsClient
from .llm import (
    OllamaClient,
    OpenAICompatClient,
    StaticLLM,
)
from .orchestrator import CAOS
from .store import Store


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
    expert_names = [
        x.strip()
        for x in getattr(args, "experts", "").split(",")
        if x.strip()
    ]
    forecast_experts, sentiment_expert = build_experts(expert_names)
    store = Store(args.state_db) if args.state_db else None
    feed_urls = [
        x.strip()
        for x in getattr(args, "news_feeds", "").split(",")
        if x.strip()
    ]
    news_analyzer = (
        NewsAnalyzer(
            RSSNewsClient(feed_urls),
            sentiment_expert=sentiment_expert,
        )
        if feed_urls
        else None
    )
    c = CAOS(
        llm,
        forecast_experts=forecast_experts,
        sentiment_expert=sentiment_expert,
        news_analyzer=news_analyzer,
        store=store,
    )
    restored = bool(args.restore and c.restore_checkpoint())
    if not restored:
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
        "--experts",
        default=os.getenv("CAOS_EXPERTS", ""),
        help="Comma-separated optional specialists: kronos,chronos2,finbert",
    )
    p.add_argument(
        "--news-feeds",
        default=os.getenv("CAOS_NEWS_FEEDS", ""),
        help="Comma-separated RSS/Atom feed URLs configured by the human operator",
    )
    p.add_argument(
        "--state-db",
        default=os.getenv("CAOS_STATE_DB", ".caos/caos.db"),
        help="SQLite runtime state path; pass an empty string to disable persistence",
    )
    p.add_argument(
        "--restore",
        action="store_true",
        help="Restore the latest runtime checkpoint before executing the command",
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
    sub.add_parser("models")
    forecast = sub.add_parser("forecast")
    forecast.add_argument("symbol")
    forecast.add_argument("--expert", default="kronos")
    forecast.add_argument("--horizon", type=int, default=12)
    ensemble = sub.add_parser("ensemble")
    ensemble.add_argument("symbol")
    ensemble.add_argument("--horizon", type=int, default=12)
    evaluate = sub.add_parser("evaluate-expert")
    evaluate.add_argument("symbol")
    evaluate.add_argument("--expert", default="kronos")
    evaluate.add_argument("--horizon", type=int, default=6)
    sentiment = sub.add_parser("sentiment")
    sentiment.add_argument("text", nargs="+")
    chat = sub.add_parser("chat")
    chat.add_argument("message", nargs="+")
    goal = sub.add_parser("goal")
    goal.add_argument("message", nargs="+")
    goal.add_argument("--max-steps", type=int, default=8)
    desk = sub.add_parser("desk")
    desk.add_argument(
        "name",
        choices=[
            "quant",
            "macro",
            "news",
            "risk",
            "compliance",
            "supervisor",
        ],
    )
    desk.add_argument("question", nargs="+")
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
    if args.cmd == "models":
        print(
            json.dumps(
                recommended_stack(),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "status":
        print(
            json.dumps(
                c.status(),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "forecast":
        print(
            json.dumps(
                c.tool_forecast(
                    args.symbol,
                    expert=args.expert,
                    horizon=args.horizon,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "ensemble":
        print(
            json.dumps(
                c.tool_forecast_ensemble(
                    args.symbol,
                    horizon=args.horizon,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "evaluate-expert":
        print(
            json.dumps(
                c.tool_evaluate_forecast_expert(
                    args.symbol,
                    expert=args.expert,
                    horizon=args.horizon,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "sentiment":
        print(
            json.dumps(
                c.tool_news_sentiment(" ".join(args.text)),
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
    elif args.cmd == "goal":
        print(
            json.dumps(
                c.run_goal(
                    " ".join(args.message),
                    max_steps=args.max_steps,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "desk":
        council = DeskCouncil(c.llm)
        print(
            json.dumps(
                council.consult(
                    args.name,
                    c.status(),
                    " ".join(args.question),
                ),
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
