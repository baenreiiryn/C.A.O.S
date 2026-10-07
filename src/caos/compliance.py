from __future__ import annotations

from dataclasses import dataclass

from .domain import Mode


class ComplianceViolation(RuntimeError):
    pass


@dataclass(slots=True)
class ComplianceState:
    live_armed: bool = False


class ComplianceEngine:
    """Hard boundary between the LLM and money-moving operations.

    The orchestrator can read this state and can activate emergency stop, but cannot arm live mode.
    A UI or direct human-only administrative surface must call `human_arm_live`.
    """

    def __init__(self) -> None:
        self.state = ComplianceState()

    def human_arm_live(self, *, confirmation: str) -> None:
        if confirmation != "ARM LIVE":
            raise ComplianceViolation("explicit_human_confirmation_required")
        self.state.live_armed = True

    def human_disarm_live(self) -> None:
        self.state.live_armed = False

    def allow_mode(self, mode: Mode) -> None:
        if mode is Mode.LIVE and not self.state.live_armed:
            raise ComplianceViolation("live_not_armed")
