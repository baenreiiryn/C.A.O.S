from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .supervisor import CompanyAudit


@dataclass(slots=True, frozen=True)
class ImprovementProposal:
    id: str
    kind: str
    target: str | None
    reason: str
    requires_human: bool
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "reason": self.reason,
            "requires_human": self.requires_human,
            "metadata": dict(self.metadata),
        }


class ImprovementManager:
    """Creates proposals only; it never bypasses Company policy/risk gates."""

    def propose(self, audit: CompanyAudit) -> list[ImprovementProposal]:
        proposals: list[ImprovementProposal] = []
        for alert in audit.alerts:
            kind = alert["kind"]
            if kind == "trader_stop_floor":
                proposals.append(
                    ImprovementProposal(
                        uuid4().hex,
                        "retire_trader",
                        alert.get("trader_id"),
                        "Trader breached Company stop floor.",
                        False,
                        dict(alert),
                    )
                )
            elif kind == "funded_trader_unassigned":
                proposals.append(
                    ImprovementProposal(
                        uuid4().hex,
                        "assign_market",
                        alert.get("trader_id"),
                        "Funded Trader is waiting for a valid opportunity.",
                        False,
                        dict(alert),
                    )
                )
            elif kind in {
                "direction_concentration",
                "strategy_family_concentration",
            }:
                proposals.append(
                    ImprovementProposal(
                        uuid4().hex,
                        "run_diversity_experiment",
                        None,
                        "Company portfolio concentration is elevated.",
                        False,
                        dict(alert),
                    )
                )
            elif kind in {"company_kill_switch", "caos_kill_switch"}:
                proposals.append(
                    ImprovementProposal(
                        uuid4().hex,
                        "investigate_emergency_state",
                        None,
                        "Emergency stop is active; reset must remain human-only.",
                        True,
                        dict(alert),
                    )
                )
        return proposals
