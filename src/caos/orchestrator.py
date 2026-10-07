from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .broker import PaperBroker
from .compliance import ComplianceEngine
from .domain import Mandate, MarketBar, OrderRequest
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
    }

    def __init__(self, llm: LocalLLM, market_client: BybitPublicClient | None = None):
        self.llm = llm
        self.market_client = market_client or BybitPublicClient()
        self.mandate: Mandate | None = None
        self.risk: RiskEngine | None = None
        self.compliance = ComplianceEngine()
        self.paper: PaperBroker | None = None
        self.market_data: dict[str, list[MarketBar]] = {}
        self.approved: dict[str, list[dict]] = {}
        self.candidate_bank: dict[str, list] = {}
        self.portfolio = []
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
            "status",
            "Return current desk, risk and paper-account status.",
            self.status,
        )
        self._register(
            "market_regime",
            "Classify trend/range and recent volatility for a loaded symbol.",
            self.tool_market_regime,
        )
        self._register(
            "mine",
            "Mine and robustly validate strategies for a loaded symbol.",
            self.tool_mine,
        )
        self._register(
            "paper_order",
            "Submit a paper-only order after risk checks.",
            self.tool_paper_order,
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

    def tool_market_regime(self, symbol: str) -> dict:
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        return market_regime(bars)

    def tool_mine(
        self,
        symbol: str,
        cost_bps: float = 8.0,
    ) -> dict:
        self._require_mandate()
        bars = self.market_data.get(symbol.upper())
        if not bars:
            raise OrchestrationError("market_data_required")
        assert self.mandate is not None
        results = mine_strategies(
            bars,
            self.mandate,
            float(cost_bps),
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
            "strategies": payload[:10],
        }

    def tool_build_portfolio(
        self,
        max_entries: int = 6,
        one_per_symbol: bool = True,
    ) -> dict:
        self._require_mandate()
        self.portfolio = build_portfolio(
            self.candidate_bank,
            max_entries=int(max_entries),
            one_per_symbol=bool(one_per_symbol),
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
            "paper": (
                self.paper.snapshot()
                if self.paper
                else None
            ),
            "orchestrator": "local_llm",
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
            "request broker secrets, or reset a kill switch. "
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
