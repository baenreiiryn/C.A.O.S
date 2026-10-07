from __future__ import annotations

import argparse
import json
import math
import os
import random
import time

from .dashboard import serve
from .company.control import CompanyControlPort
from .company.dashboard import serve_company
from .company.domain import TraderMode
from .company.standalone import (
    CompanyStandaloneError,
    build_daemon,
    build_policy,
    build_standalone_company,
    initialize_company,
    load_runtime_config,
    load_saved_policy,
    parse_scan_targets,
    require_initialized,
    save_runtime_config,
    targets_from_runtime_config,
)
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
from .testnet import BybitTestnetClient, HumanTestnetExecutor


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
    tnet = sub.add_parser("testnet-order")
    tnet.add_argument("--confirm", required=True)
    tnet.add_argument("--category", choices=["linear", "inverse", "spot"], default="linear")
    tnet.add_argument("symbol")
    tnet.add_argument("side", choices=["Buy", "Sell"])
    tnet.add_argument("order_type", choices=["Market", "Limit"])
    tnet.add_argument("qty")
    tnet.add_argument("--price")
    tnet.add_argument("--reduce-only", action="store_true")
    tnet.add_argument("--trigger-price")
    tnet.add_argument("--trigger-direction", type=int, choices=[1, 2])
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

    company = sub.add_parser(
        "company",
        help="Run the standalone Trade Company cell",
    )
    company_sub = company.add_subparsers(
        dest="company_cmd",
        required=True,
    )

    cinit = company_sub.add_parser("init")
    cinit.add_argument("--company-capital", type=float, default=10.0)
    cinit.add_argument("--trader-bucket", type=float, default=10.0)
    cinit.add_argument("--stop-floor", type=float, default=3.0)
    cinit.add_argument(
        "--default-max-exposure",
        type=float,
        default=20.0,
    )
    cinit.add_argument(
        "--operational-cap",
        type=int,
        default=6,
    )
    cinit.add_argument(
        "--company-max-dd",
        type=float,
        default=30.0,
    )
    cinit.add_argument(
        "--trader-max-exposure",
        type=float,
        default=None,
    )
    cinit.add_argument(
        "--requested-exposure",
        type=float,
        default=None,
    )
    cinit.add_argument(
        "--mode",
        choices=["production", "training"],
        default="production",
    )
    cinit.add_argument(
        "--targets",
        default="BTCUSDT:long:momentum",
        help=(
            "Comma-separated SYMBOL[:direction[:strategy+strategy]] entries"
        ),
    )
    cinit.add_argument("--interval", default="60")
    cinit.add_argument("--candle-limit", type=int, default=500)
    cinit.add_argument(
        "--opportunity-ttl-ms",
        type=int,
        default=3_600_000,
    )
    cinit.add_argument("--every", type=float, default=60.0)

    company_sub.add_parser("status")
    company_sub.add_parser("traders")
    company_sub.add_parser("treasury")
    company_sub.add_parser("opportunities")
    company_sub.add_parser("audit")

    def add_runtime_overrides(sp):
        sp.add_argument("--targets", default=None)
        sp.add_argument("--interval", default=None)
        sp.add_argument("--candle-limit", type=int, default=None)
        sp.add_argument(
            "--opportunity-ttl-ms",
            type=int,
            default=None,
        )

    conce = company_sub.add_parser("once")
    add_runtime_overrides(conce)

    crun = company_sub.add_parser("run")
    add_runtime_overrides(crun)
    crun.add_argument("--every", type=float, default=None)

    cdash = company_sub.add_parser("dashboard")
    cdash.add_argument("--port", type=int, default=5191)
    cdash.add_argument("--no-browser", action="store_true")

    climit = company_sub.add_parser("set-limit")
    climit.add_argument("limit", type=int)

    cexp = company_sub.add_parser("set-exposure")
    cexp.add_argument("trader_id")
    cexp.add_argument("--max", dest="max_exposure", type=float, required=True)
    cexp.add_argument("--size", dest="requested_exposure", type=float)

    cpause = company_sub.add_parser("pause")
    cpause.add_argument("trader_id")
    cresume = company_sub.add_parser("resume")
    cresume.add_argument("trader_id")
    company_sub.add_parser("emergency-stop")

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
    elif args.cmd == "testnet-order":
        api_key = os.getenv("BYBIT_TESTNET_API_KEY", "")
        api_secret = os.getenv("BYBIT_TESTNET_API_SECRET", "")
        c.compliance.human_arm_testnet(
            confirmation=args.confirm
        )
        executor = HumanTestnetExecutor(
            c.compliance,
            BybitTestnetClient(
                api_key=api_key,
                api_secret=api_secret,
            ),
        )
        ack = executor.place_order(
            category=args.category,
            symbol=args.symbol,
            side=args.side,
            order_type=args.order_type,
            qty=args.qty,
            price=args.price,
            reduce_only=args.reduce_only,
            trigger_price=args.trigger_price,
            trigger_direction=args.trigger_direction,
        )
        print(
            json.dumps(
                {
                    "order_id": ack.order_id,
                    "order_link_id": ack.order_link_id,
                    "environment": "BYBIT_TESTNET_ONLY",
                },
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
