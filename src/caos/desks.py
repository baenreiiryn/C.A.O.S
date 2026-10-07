from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .llm import LocalLLM


@dataclass(slots=True, frozen=True)
class DeskSpec:
    name: str
    mission: str
    allowed_tools: tuple[str, ...]


DESKS: dict[str, DeskSpec] = {
    "quant": DeskSpec(
        "QUANT",
        "Research strategies, interpret backtests and robustness, and recommend quantitative experiments.",
        (
            "fetch_market",
            "market_regime",
            "forecast",
            "forecast_ensemble",
            "evaluate_forecast_expert",
            "mine",
            "build_portfolio",
            "status",
        ),
    ),
    "macro": DeskSpec(
        "MACRO",
        "Interpret market regime and cross-market context. Never execute orders.",
        ("fetch_market", "market_regime", "status"),
    ),
    "news": DeskSpec(
        "NEWS",
        "Interpret user-supplied headlines or external context. Never execute orders or alter safety state.",
        ("news_sentiment", "status"),
    ),
    "risk": DeskSpec(
        "RISK",
        "Audit exposure and safety. Prefer reducing risk; emergency stop is allowed.",
        ("status", "kill"),
    ),
    "compliance": DeskSpec(
        "COMPLIANCE",
        "Audit policy boundaries. Never arm live trading, handle broker secrets, or reset a kill switch.",
        ("status", "kill"),
    ),
    "supervisor": DeskSpec(
        "SUPERVISOR",
        "Watch the whole system for divergence, stale data and unsafe state; recommend corrective actions.",
        (
            "status",
            "market_regime",
            "forecast_ensemble",
            "evaluate_forecast_expert",
            "kill",
        ),
    ),
}


class DeskCouncil:
    """Logical multi-agent layer multiplexed over one local LLM."""

    def __init__(self, llm: LocalLLM):
        self.llm = llm

    def consult(
        self,
        desk: str,
        context: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        key = desk.lower()
        if key not in DESKS:
            raise ValueError(f"unknown desk: {desk}")
        spec = DESKS[key]
        system = (
            f"You are the {spec.name} desk in C.A.O.S. Mission: {spec.mission} "
            f"Allowed tools for recommendations: {list(spec.allowed_tools)}. "
            "Return JSON only with keys assessment, risks, recommendations, suggested_tool. "
            "suggested_tool must be null or one of the allowed tools."
        )
        user = json.dumps(
            {"question": question, "context": context},
            ensure_ascii=False,
        )
        raw = self.llm.complete(system, user)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("desk returned invalid JSON") from exc
        suggested = result.get("suggested_tool")
        if (
            suggested is not None
            and suggested not in spec.allowed_tools
        ):
            raise ValueError("desk suggested forbidden tool")
        result["desk"] = spec.name
        return result
