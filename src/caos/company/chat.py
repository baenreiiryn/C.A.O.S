from __future__ import annotations

import json
import threading
from collections import deque


class CompanyChatError(RuntimeError):
    pass


class CompanyChatService:
    """Read-only natural-language assistant for the Trade Company UI."""

    def __init__(
        self,
        caos,
        company,
        *,
        execution_service=None,
        max_messages: int = 12,
    ):
        self.caos = caos
        self.company = company
        self.execution_service = execution_service
        self.history = deque(maxlen=max(4, int(max_messages)))
        self._lock = threading.RLock()

    def _context(self) -> dict:
        status = self.company.status()
        traders = []
        for trader_id, row in (
            status.get("traders", {})
            .get("traders", {})
            .items()
        ):
            traders.append(
                {
                    "id": trader_id,
                    "status": row.get("status"),
                    "market": row.get("market"),
                    "direction": row.get("direction"),
                    "strategy_id": row.get("strategy_id"),
                    "mode": row.get("mode"),
                    "max_trade_exposure_pct": row.get(
                        "max_trade_exposure_pct"
                    ),
                    "trade_exposure_pct": row.get(
                        "trade_exposure_pct"
                    ),
                    "timeframe": (
                        row.get("metadata", {})
                        .get("timeframe")
                    ),
                    "selection_mode": (
                        row.get("metadata", {})
                        .get("selection_mode")
                    ),
                }
            )
        execution = (
            self.execution_service.status()
            if self.execution_service is not None
            else {"mode": "paper"}
        )
        return {
            "operational_state": status.get(
                "operational_state"
            ),
            "execution_mode": execution.get("mode"),
            "policy": {
                key: status.get("policy", {}).get(key)
                for key in (
                    "trader_initial_bucket",
                    "trader_stop_floor",
                    "default_trader_max_exposure_pct",
                    "company_max_drawdown_pct",
                    "operational_trader_cap",
                )
            },
            "company": {
                "equity": status.get(
                    "marked_company_equity"
                ),
                "treasury_reserve": status.get(
                    "treasury", {}
                ).get("reserve"),
                "gross_exposure": status.get(
                    "exposure", {}
                ).get("gross_notional"),
                "drawdown_pct": status.get(
                    "risk", {}
                ).get("drawdown_pct"),
                "kill_switch": status.get(
                    "risk", {}
                ).get("kill_switch"),
            },
            "traders": traders,
            "assignments": status.get("assignments", {}),
            "audit": status.get("audit", {}),
            "news_contexts": status.get(
                "news_intelligence", {}
            ).get("contexts", {}),
        }

    def messages(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self.history]

    def clear(self) -> dict:
        with self._lock:
            self.history.clear()
        return {"cleared": True}

    def ask(self, message: str) -> dict:
        message = str(message).strip()
        if not message:
            raise CompanyChatError("message_required")
        if len(message) > 8000:
            raise CompanyChatError("message_too_long")

        with self._lock:
            previous = list(self.history)[-8:]

        context = self._context()
        conversation = "\n".join(
            f"{row['role']}: {row['content']}"
            for row in previous
        )
        system = (
            "You are the read-only natural-language assistant inside "
            "C.A.O.S Trade Company. Answer in the user's language. "
            "Explain the current Company state, Traders, risk, market "
            "context, strategies and configuration clearly. You may "
            "suggest actions, but you cannot execute trades, change "
            "PAPER/TESTNET/REAL mode, confirm production orders, change "
            "credentials, or mutate Company state. Never claim an action "
            "was performed. Distinguish facts from suggestions."
        )
        user = (
            "CURRENT TRADE COMPANY SNAPSHOT:\n"
            + json.dumps(
                context,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\nRECENT CHAT:\n"
            + (conversation or "(none)")
            + "\n\nUSER:\n"
            + message
        )

        try:
            answer = str(
                self.caos.llm.complete(system, user)
            ).strip()
        except Exception as exc:
            raise CompanyChatError(
                f"llm_chat_failed:{type(exc).__name__}:{exc}"
            ) from exc
        if not answer:
            answer = "(The configured LLM returned an empty response.)"

        with self._lock:
            self.history.append(
                {"role": "user", "content": message}
            )
            self.history.append(
                {"role": "assistant", "content": answer}
            )
        return {
            "answer": answer,
            "history": self.messages(),
            "read_only": True,
        }
