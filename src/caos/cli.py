from __future__ import annotations

import argparse
import json
import math
import os
import random
import time

from .dashboard import serve
from .company.cell import TradeCompanyCell
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
    company_sub.add_parser("execution-plans")
    company_sub.add_parser("research")

    rh = company_sub.add_parser("research-hypothesis")
    rh.add_argument("--symbol", required=True)
    rh.add_argument(
        "--family",
        required=True,
        choices=[
            "trend",
            "mean_reversion",
            "breakout",
            "momentum",
        ],
    )
    rh.add_argument("--thesis", required=True)
    rh.add_argument("--source", default="manual")
    rh.add_argument("--parent-strategy", default=None)

    rfi = company_sub.add_parser("research-from-improvements")
    rfi.add_argument("--symbol", required=True)
    rfi.add_argument(
        "--family",
        required=True,
        choices=[
            "trend",
            "mean_reversion",
            "breakout",
            "momentum",
        ],
    )

    rr = company_sub.add_parser("research-run")
    rr.add_argument("hypothesis_id")
    rr.add_argument("--generator", default="builtin_grid")
    rr.add_argument("--candidate-limit", type=int, default=12)
    rr.add_argument("--starting-capital", type=float, default=10.0)
    rr.add_argument("--cost-bps", type=float, default=8.0)

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
    cexp.add_argument(
        "--max-exposure",
        dest="max_exposure",
        type=float,
        required=True,
    )
    cexp.add_argument("--size", dest="requested_exposure", type=float)

    cpause = company_sub.add_parser("pause")
    cpause.add_argument("trader_id")
    cresume = company_sub.add_parser("resume")
    cresume.add_argument("trader_id")
    company_sub.add_parser("emergency-stop")
    company_sub.add_parser("cell-manifest")
    company_sub.add_parser("cell-status")
    company_sub.add_parser("cell-health")
    company_sub.add_parser("cell-metrics")
    company_sub.add_parser("cell-alerts")
    company_sub.add_parser("cell-report")
    company_sub.add_parser("cell-pause")
    company_sub.add_parser("cell-resume")

    return p


def _company_runtime_settings(args, store):
    saved = load_runtime_config(store)
    if saved is None:
        raise CompanyStandaloneError(
            "company_runtime_config_missing_run_company_init_first"
        )

    targets = (
        parse_scan_targets(args.targets)
        if getattr(args, "targets", None)
        else targets_from_runtime_config(saved)
    )
    interval = (
        args.interval
        if getattr(args, "interval", None) is not None
        else saved.get("interval", "60")
    )
    candle_limit = (
        args.candle_limit
        if getattr(args, "candle_limit", None) is not None
        else int(saved.get("candle_limit", 500))
    )
    ttl = (
        args.opportunity_ttl_ms
        if getattr(args, "opportunity_ttl_ms", None) is not None
        else int(saved.get("opportunity_ttl_ms", 3_600_000))
    )
    every = (
        args.every
        if getattr(args, "every", None) is not None
        else float(saved.get("every_seconds", 60.0))
    )
    return targets, interval, candle_limit, ttl, every


def _load_company_for_command(c):
    policy = load_saved_policy(c.store)
    if policy is None:
        raise CompanyStandaloneError(
            "company_not_initialized_run_company_init_first"
        )
    company, restored = build_standalone_company(
        c,
        policy,
        restore=True,
    )
    if not restored:
        raise CompanyStandaloneError(
            "company_checkpoint_missing"
        )
    require_initialized(company)
    return company


def _print_json(payload) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> None:
    args = parser().parse_args()
    c = build_caos(args)

    if args.cmd == "company":
        if args.company_cmd == "init":
            if load_saved_policy(c.store) is not None:
                raise CompanyStandaloneError(
                    "company_already_initialized"
                )
            policy = build_policy(
                initial_company_capital=args.company_capital,
                trader_initial_bucket=args.trader_bucket,
                trader_stop_floor=args.stop_floor,
                default_trader_max_exposure_pct=(
                    args.default_max_exposure
                ),
                operational_trader_cap=args.operational_cap,
                company_max_drawdown_pct=args.company_max_dd,
            )
            company, _ = build_standalone_company(
                c,
                policy,
                restore=False,
            )
            targets = parse_scan_targets(args.targets)
            initialized = initialize_company(
                company,
                targets,
                mode=TraderMode(args.mode),
                max_trade_exposure_pct=args.trader_max_exposure,
                trade_exposure_pct=args.requested_exposure,
            )
            runtime = save_runtime_config(
                c.store,
                targets,
                interval=args.interval,
                candle_limit=args.candle_limit,
                opportunity_ttl_ms=args.opportunity_ttl_ms,
                every_seconds=args.every,
            )
            _print_json(
                {
                    **initialized,
                    "runtime": runtime,
                    "status": company.status(),
                }
            )
            return

        company = _load_company_for_command(c)
        control = CompanyControlPort(company)
        cell = TradeCompanyCell(control)

        if args.company_cmd == "cell-manifest":
            _print_json(cell.get_manifest())
            return
        if args.company_cmd == "cell-status":
            _print_json(cell.get_status())
            return
        if args.company_cmd == "cell-health":
            _print_json(cell.get_health())
            return
        if args.company_cmd == "cell-metrics":
            _print_json(cell.get_metrics())
            return
        if args.company_cmd == "cell-alerts":
            _print_json(cell.get_alerts())
            return
        if args.company_cmd == "cell-report":
            _print_json(cell.get_report())
            return
        if args.company_cmd == "cell-pause":
            _print_json(cell.execute_command("pause"))
            return
        if args.company_cmd == "cell-resume":
            _print_json(cell.execute_command("resume"))
            return

        if args.company_cmd == "status":
            _print_json(control.get_company_status())
            return
        if args.company_cmd == "traders":
            _print_json(control.list_traders())
            return
        if args.company_cmd == "treasury":
            _print_json(control.get_treasury())
            return
        if args.company_cmd == "opportunities":
            _print_json(control.list_opportunities())
            return
        if args.company_cmd == "audit":
            _print_json(company.audit())
            return
        if args.company_cmd == "execution-plans":
            _print_json(control.get_execution_plans())
            return
        if args.company_cmd == "research":
            _print_json(control.get_research())
            return
        if args.company_cmd == "research-hypothesis":
            _print_json(
                control.submit_research_hypothesis(
                    symbol=args.symbol,
                    family=args.family,
                    thesis=args.thesis,
                    source=args.source,
                    parent_strategy_id=args.parent_strategy,
                )
            )
            return
        if args.company_cmd == "research-from-improvements":
            _print_json(
                control.seed_research_from_improvements(
                    symbol=args.symbol,
                    family=args.family,
                )
            )
            return
        if args.company_cmd == "research-run":
            _print_json(
                control.run_research_cycle(
                    args.hypothesis_id,
                    generator_id=args.generator,
                    candidate_limit=args.candidate_limit,
                    starting_capital=args.starting_capital,
                    cost_bps=args.cost_bps,
                )
            )
            return
        if args.company_cmd in {"once", "run"}:
            (
                targets,
                interval,
                candle_limit,
                ttl,
                every,
            ) = _company_runtime_settings(args, c.store)
            daemon = build_daemon(
                company,
                targets,
                interval=interval,
                candle_limit=candle_limit,
                opportunity_ttl_ms=ttl,
            )
            if args.company_cmd == "once":
                _print_json(
                    daemon.run_once(
                        now=int(time.time() * 1000)
                    ).to_dict()
                )
                return
            print(
                "Trade Company daemon: "
                f"{len(targets)} target(s), "
                f"every {every:g}s"
            )
            try:
                daemon.serve(every_seconds=every)
            except KeyboardInterrupt:
                pass
            return
        if args.company_cmd == "dashboard":
            server = serve_company(
                control,
                port=args.port,
                open_browser=not args.no_browser,
            )
            print(
                "Trade Company dashboard: "
                f"http://127.0.0.1:{args.port}"
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        if args.company_cmd == "set-limit":
            _print_json(
                control.set_operational_trader_limit(
                    args.limit
                )
            )
            return
        if args.company_cmd == "set-exposure":
            _print_json(
                control.configure_trader_exposure(
                    args.trader_id,
                    max_trade_exposure_pct=args.max_exposure,
                    trade_exposure_pct=args.requested_exposure,
                )
            )
            return
        if args.company_cmd == "pause":
            _print_json(control.pause_trader(args.trader_id))
            return
        if args.company_cmd == "resume":
            _print_json(control.resume_trader(args.trader_id))
            return
        if args.company_cmd == "emergency-stop":
            _print_json(control.emergency_stop())
            return
        raise CompanyStandaloneError("unknown_company_command")

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
