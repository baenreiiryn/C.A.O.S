from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .broker import PaperBroker
from .compliance import ComplianceEngine
from .domain import Mandate, MarketBar, OrderRequest
from .experts.ensemble import ExpertEnsemble
from .experts.evaluation import walk_forward_evaluate
from .execution import estimate_execution_cost
from .llm import LocalLLM
from .marketdata import BybitPublicClient
from .portfolio import build_portfolio
from .quant import market_regime, mine_strategies
from .risk import RiskEngine
from .runner import PaperRunner


class OrchestrationError(RuntimeError):
    pass


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]


class CAOS:
    """Local-LLM orchestrator with a deterministic tool boundary."""

    FORBIDDEN_FOR_LLM = {
        "human_arm_live",
        "set_broker_credentials",
        "reset_kill_switch",
        "paper_order",
    }

    def __init__(
        self,
        llm: LocalLLM,
        market_client: BybitPublicClient | None = None,
        forecast_experts: dict[str, Any] | None = None,
        sentiment_expert: Any | None = None,
    ):
        self.llm = llm
        self.market_client = market_client or BybitPublicClient()
        self.forecast_experts = forecast_experts or {}
        self.sentiment_expert = sentiment_expert
        self.expert_ensemble = ExpertEnsemble()
        self.mandate: Mandate | None = None
        self.risk: RiskEngine | None = None
        self.compliance = ComplianceEngine()
        self.paper: PaperBroker | None = None
        self.market_data: dict[str, list[MarketBar]] = {}
        self.approved: dict[str, list[dict]] = {}
        self.candidate_bank: dict[str, list] = {}
        self.portfolio = []
        self.execution_costs: dict[str, float] = {}
        self.tools: dict[str, Tool] = {}
        self._register_tools()

    def _register(
        self,
        name: str,
        description: str,
        fn: Callable[..., Any],
    ) -> None:
        self.tools[name] = Tool(name, description, fn)

    def _register_tools(self) -> None:
        self._register(
            "fetch_market",
            "Download public Bybit candles for a symbol; no API key is used.",
            self.tool_fetch_market,
        )
        self._register(
            "status",
            "Return current desk, risk, expert and paper-account status.",
            self.status,
        )
        self._register(
            "market_regime",
            "Classify trend/range and recent volatility for a loaded symbol.",
            self.tool_market_regime,
        )
        self._register(
            "estimate_cost",
            "Measure spread and depth-based execution cost from the public Bybit orderbook.",
            self.tool_estimate_cost,
        )
        self._register(
            "forecast",
            "Run one configured local forecast expert. The result is evidence, never an order.",
            self.tool_forecast,
        )
        self._register(
            "forecast_ensemble",
            "Compare configured forecast experts and optionally financial-news sentiment.",
            self.tool_forecast_ensemble,
        )
        self._register(
            "evaluate_forecast_expert",
            "Walk-forward evaluate one configured forecast expert against a naive price baseline.",
            self.tool_evaluate_forecast_expert,
        )
        self._register(
            "news_sentiment",
            "Classify financial text with the configured local sentiment specialist.",
            self.tool_news_sentiment,
        )
        self._register(
            "mine",
            "Mine and robustly validate deterministic strategies for a loaded symbol.",
            self.tool_mine,
        )
        self._register(
            "build_portfolio",
            "Build a paper portfolio only from strategies that passed robustness gates.",
            self.tool_build_portfolio,
        )
        self._register(
            "paper_cycle",
            "Run one deterministic paper cycle for the validated portfolio; the LLM does not place raw orders.",
            self.tool_paper_cycle,
        )
        self._register(
            "kill",
            "Emergency stop. LLM is allowed to make the system safer.",
            self.tool_kill,
        )

    def set_mandate(self, mandate: Mandate) -> None:
        self.mandate = mandate
        self.risk = RiskEngine(mandate)
        self.paper = PaperBroker(self.risk)

    def load_bars(
        self,
        symbol: str,
        bars: list[MarketBar],
    ) -> None:
        if not symbol:
            raise ValueError("symbol required")
        self.market_data[symbol.upper()] = list(bars)

    def _require_mandate(self) -> None:
        if (
            self.mandate is None
            or self.risk is None
            or self.paper is None
        ):
            raise OrchestrationError("mandate_required")

    def tool_fetch_market(
        self,
        symbol: str,
        interval: str = "60",
        limit: int = 500,
        category: str = "linear",
    ) -> dict:
        bars = self.market_client.klines(symbol, interval, int(limit), category)
        self.load_bars(symbol, bars)
        return {
            "symbol": symbol.upper(),
            "bars": len(bars),
            "first_ts": bars[0].ts if bars else None,
            "last_ts": bars[-1].ts if bars else None,
        }

    def tool_estimate_cost(
        self,
        symbol: str,
        side: str = "buy",
        notional: float = 100.0,
        fee_bps: float = 5.0,
        depth: int = 50,
        category: str = "linear",
    ) -> dict:
        book = self.market_client.orderbook(
            symbol,
            limit=int(depth),
            category=category,
        )
        cost = estimate_execution_cost(
            book["bids"],
            book["asks"],
            side=side,
            notional=float(notional),
            fee_bps=float(fee_bps),
        )
        if cost.liquidity_sufficient:
            self.execution_costs[symbol.upper()] = cost.roundtrip_cost_bps
        payload = cost.to_dict()
        payload["symbol"] = symbol.upper()
        payload["book_ts"] = book.get("ts")
        return payload

    def tool_market_regime(self, symbol: str) -> dict:
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        return market_regime(bars)

    def tool_forecast(
        self,
        symbol: str,
        expert: str = "kronos",
        horizon: int = 12,
    ) -> dict:
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        predictor = self.forecast_experts.get(expert.lower())
        if predictor is None:
            raise OrchestrationError("forecast_expert_not_configured")
        result = predictor.forecast(symbol.upper(), bars, int(horizon))
        return result.to_dict()

    def tool_evaluate_forecast_expert(
        self,
        symbol: str,
        expert: str = "kronos",
        horizon: int = 6,
        min_context: int = 100,
        max_windows: int = 12,
    ) -> dict:
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        predictor = self.forecast_experts.get(expert.lower())
        if predictor is None:
            raise OrchestrationError("forecast_expert_not_configured")
        return walk_forward_evaluate(
            predictor,
            symbol.upper(),
            bars,
            horizon=int(horizon),
            min_context=int(min_context),
            max_windows=int(max_windows),
        ).to_dict()

    def tool_news_sentiment(self, text: str) -> dict:
        if self.sentiment_expert is None:
            raise OrchestrationError("sentiment_expert_not_configured")
        return self.sentiment_expert.classify(text).to_dict()

    def tool_forecast_ensemble(
        self,
        symbol: str,
        horizon: int = 12,
        experts: list[str] | None = None,
        news_text: str | None = None,
    ) -> dict:
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        selected = experts or sorted(self.forecast_experts)
        forecasts = []
        errors: dict[str, str] = {}
        for name in selected:
            predictor = self.forecast_experts.get(name.lower())
            if predictor is None:
                errors[name] = "not_configured"
                continue
            try:
                forecasts.append(
                    predictor.forecast(symbol.upper(), bars, int(horizon))
                )
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"

        sentiment = None
        if news_text and self.sentiment_expert is not None:
            try:
                sentiment = self.sentiment_expert.classify(news_text)
            except Exception as exc:
                errors["sentiment"] = f"{type(exc).__name__}: {exc}"

        outlook = self.expert_ensemble.combine(forecasts, sentiment)
        payload = outlook.to_dict()
        payload["symbol"] = symbol.upper()
        payload["horizon"] = int(horizon)
        payload["errors"] = errors
        return payload

    def tool_mine(
        self,
        symbol: str,
        cost_bps: float | None = None,
    ) -> dict:
        self._require_mandate()
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        assert self.mandate is not None
        effective_cost_bps = (
            float(cost_bps)
            if cost_bps is not None
            else float(self.execution_costs.get(symbol.upper(), 8.0))
        )
        results = mine_strategies(
            bars,
            self.mandate,
            effective_cost_bps,
        )
        self.candidate_bank[symbol.upper()] = results
        payload = []
        for spec, bt, rb in results:
            payload.append(
                {
                    "strategy": asdict(spec),
                    "backtest": bt.to_dict(),
                    "robustness": asdict(rb),
                }
            )
        self.approved[symbol.upper()] = payload
        return {
            "symbol": symbol.upper(),
            "approved": len(payload),
            "cost_bps": effective_cost_bps,
            "strategies": payload[:10],
        }

    def tool_build_portfolio(
        self,
        max_entries: int = 6,
        one_per_symbol: bool = True,
        max_correlation: float = 0.85,
    ) -> dict:
        self._require_mandate()
        self.portfolio = build_portfolio(
            self.candidate_bank,
            max_entries=int(max_entries),
            one_per_symbol=bool(one_per_symbol),
            market_data=self.market_data,
            max_correlation=float(max_correlation),
        )
        return {
            "entries": len(self.portfolio),
            "portfolio": [entry.to_dict() for entry in self.portfolio],
        }

    def tool_paper_cycle(self) -> dict:
        self._require_mandate()
        result = PaperRunner(self).cycle(self.portfolio)
        return {"actions": result.actions, "skipped": result.skipped}

    def tool_paper_order(
        self,
        symbol: str,
        side: str,
        notional: float,
        price: float,
        strategy: str = "manual",
    ) -> dict:
        self._require_mandate()
        if side not in {"buy", "sell"}:
            raise OrchestrationError("side_must_be_buy_or_sell")
        assert self.paper is not None
        fill = self.paper.execute(
            OrderRequest(
                symbol.upper(),
                side,
                float(notional),
                float(price),
                strategy,
            )
        )
        return asdict(fill)

    def tool_kill(self) -> dict:
        self._require_mandate()
        assert self.risk is not None
        self.risk.kill()
        return {"kill_switch": True}

    def status(self) -> dict:
        return {
            "mandate": (
                self.mandate.to_dict()
                if self.mandate
                else None
            ),
            "kill_switch": (
                self.risk.state.kill_switch
                if self.risk
                else False
            ),
            "live_armed": self.compliance.state.live_armed,
            "symbols_loaded": sorted(self.market_data),
            "approved_by_symbol": {
                k: len(v)
                for k, v in self.approved.items()
            },
            "portfolio": [
                {
                    "symbol": e.symbol,
                    "strategy": e.strategy.name,
                    "weight": e.weight,
                }
                for e in self.portfolio
            ],
            "execution_cost_bps": dict(self.execution_costs),
            "paper": (
                self.paper.snapshot()
                if self.paper
                else None
            ),
            "orchestrator": "local_llm",
            "experts": {
                "forecast": sorted(self.forecast_experts),
                "sentiment": (
                    getattr(self.sentiment_expert, "name", None)
                    if self.sentiment_expert is not None
                    else None
                ),
            },
        }

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise OrchestrationError(
                    "llm_did_not_return_json"
                )
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise OrchestrationError(
                    "invalid_llm_json"
                ) from exc

    def run_goal(self, goal: str, max_steps: int = 8) -> dict:
        if not 1 <= max_steps <= 32:
            raise ValueError("max_steps must be between 1 and 32")
        trace: list[dict] = []
        for step in range(1, max_steps + 1):
            exposed = [
                {"name": t.name, "description": t.description}
                for t in self.tools.values()
                if t.name not in self.FORBIDDEN_FOR_LLM
            ]
            system = (
                "You are the C.A.O.S goal orchestrator. Work toward the goal one safe step at a time. "
                'Return JSON only. To execute a step return {"tool":"name","args":{...}}. '
                'When the goal is actually satisfied return {"finish":{"summary":"..."}}. '
                "Never arm live trading, request broker secrets, reset a kill switch, or place raw orders. "
                "Forecasts and sentiment are evidence only; paper execution must use validated portfolio tools. Tools: "
                + json.dumps(exposed, ensure_ascii=False)
            )
            user = json.dumps(
                {
                    "goal": goal,
                    "state": self.status(),
                    "trace": trace[-6:],
                    "step": step,
                },
                ensure_ascii=False,
            )
            plan = self._extract_json(self.llm.complete(system, user))
            if "finish" in plan:
                finish = plan["finish"]
                if not isinstance(finish, dict):
                    raise OrchestrationError("finish_must_be_object")
                return {
                    "status": "completed",
                    "steps": step - 1,
                    "summary": finish.get("summary", ""),
                    "trace": trace,
                }
            name = plan.get("tool")
            args = plan.get("args", {})
            if name in self.FORBIDDEN_FOR_LLM:
                raise OrchestrationError("forbidden_tool")
            tool = self.tools.get(name)
            if tool is None:
                raise OrchestrationError("unknown_tool")
            if not isinstance(args, dict):
                raise OrchestrationError("tool_args_must_be_object")
            result = tool.fn(**args)
            trace.append(
                {
                    "step": step,
                    "tool": name,
                    "args": args,
                    "result": result,
                }
            )
        return {
            "status": "max_steps",
            "steps": max_steps,
            "summary": "Goal was not declared complete within the safe step budget.",
            "trace": trace,
        }

    def handle(self, message: str) -> dict:
        exposed = [
            {
                "name": t.name,
                "description": t.description,
            }
            for t in self.tools.values()
            if t.name not in self.FORBIDDEN_FOR_LLM
        ]
        system = (
            "You are the C.A.O.S local orchestrator. "
            "Pick exactly one deterministic tool. "
            "Never invent tools. Never arm live trading, "
            "request broker secrets, reset a kill switch, or place raw orders. "
            "Forecasts and sentiment are evidence only; execution must flow through validated portfolio tools. "
            'Return JSON only as {"tool":"name","args":{...}}. '
            "Available tools: "
            + json.dumps(exposed, ensure_ascii=False)
        )
        raw = self.llm.complete(system, message)
        plan = self._extract_json(raw)
        name = plan.get("tool")
        args = plan.get("args", {})
        if name in self.FORBIDDEN_FOR_LLM:
            raise OrchestrationError("forbidden_tool")
        tool = self.tools.get(name)
        if tool is None:
            raise OrchestrationError("unknown_tool")
        if not isinstance(args, dict):
            raise OrchestrationError(
                "tool_args_must_be_object"
            )
        result = tool.fn(**args)
        return {"tool": name, "result": result}
