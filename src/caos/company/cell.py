from __future__ import annotations

from typing import Any

from ..cell_protocol import (
    CELL_PROTOCOL_VERSION,
    CellManifest,
    CellProtocolError,
)
from .control import CompanyControlPort


class TradeCompanyCell:
    """Generic Company Cell adapter for the standalone Trade Company."""

    SAFE_COMMANDS = (
        "pause",
        "resume",
        "emergency_stop",
    )

    def __init__(
        self,
        control: CompanyControlPort,
        *,
        cell_id: str = "trade-company",
        name: str = "Trade Company",
    ):
        self.control = control
        self.manifest = CellManifest(
            cell_id=cell_id,
            cell_type="trading",
            name=name,
            protocol_version=CELL_PROTOCOL_VERSION,
            autonomy="autonomous",
            capabilities=(
                "status",
                "health",
                "metrics",
                "alerts",
                "events",
                "report",
                "themed_ui",
                "domain.trade.summary",
            ),
            commands=self.SAFE_COMMANDS,
            ui={
                "kind": "themed_city",
                "path": "/",
                "label": "Arcane Trading City",
            },
        )

    def get_manifest(self) -> dict:
        return self.manifest.to_dict()

    def _company_status(self) -> dict:
        return self.control.get_company_status()

    @staticmethod
    def _health_state(status: dict) -> str:
        risk = status.get("risk", {})
        caos = status.get("caos", {})
        audit = status.get("audit", {})
        if risk.get("kill_switch") or caos.get("kill_switch"):
            return "emergency"
        if audit.get("status") == "critical":
            return "critical"
        if audit.get("alerts"):
            return "attention"
        return "healthy"

    @staticmethod
    def _operational_state(status: dict) -> str:
        if status.get("risk", {}).get("kill_switch"):
            return "emergency_stopped"
        if status.get("operations_paused"):
            return "paused"
        return "running"

    def get_status(self) -> dict:
        status = self._company_status()
        return {
            "protocol_version": CELL_PROTOCOL_VERSION,
            "cell_id": self.manifest.cell_id,
            "cell_type": self.manifest.cell_type,
            "name": self.manifest.name,
            "operational_state": self._operational_state(status),
            "health": self._health_state(status),
            "autonomy": self.manifest.autonomy,
            "summary": {
                "marked_company_equity": status.get(
                    "marked_company_equity",
                    0.0,
                ),
                "treasury_reserve": status.get(
                    "treasury",
                    {},
                ).get("reserve", 0.0),
                "trader_slots": status.get(
                    "traders",
                    {},
                ).get("slot_count", 0),
                "effective_trader_limit": status.get(
                    "effective_trader_limit",
                    0,
                ),
                "alerts": len(
                    status.get("audit", {}).get("alerts", [])
                ),
            },
        }

    def get_health(self) -> dict:
        status = self._company_status()
        audit = status.get("audit", {})
        mismatches = status.get("reconciliation_mismatches", [])
        state = self._health_state(status)
        checks = {
            "company_supervisor": audit.get("status", "unknown"),
            "company_kill_switch": bool(
                status.get("risk", {}).get("kill_switch")
            ),
            "caos_kill_switch": bool(
                status.get("caos", {}).get("kill_switch")
            ),
            "reconciliation": (
                "mismatch" if mismatches else "ok"
            ),
            "operations_paused": bool(
                status.get("operations_paused")
            ),
        }
        return {
            "cell_id": self.manifest.cell_id,
            "state": state,
            "checks": checks,
        }

    def get_metrics(self) -> dict:
        status = self._company_status()
        exposure = status.get("exposure", {})
        risk = status.get("risk", {})
        traders = status.get("traders", {})
        opportunities = status.get("opportunities", {})
        return {
            "cell_id": self.manifest.cell_id,
            "metrics": {
                "company_equity": status.get(
                    "marked_company_equity",
                    0.0,
                ),
                "treasury_reserve": status.get(
                    "treasury",
                    {},
                ).get("reserve", 0.0),
                "trader_slots": traders.get("slot_count", 0),
                "effective_trader_limit": status.get(
                    "effective_trader_limit",
                    0,
                ),
                "gross_exposure": exposure.get(
                    "gross_notional",
                    0.0,
                ),
                "company_drawdown_pct": risk.get(
                    "drawdown_pct",
                    0.0,
                ),
                "opportunities": len(opportunities),
                "alerts": len(
                    status.get("audit", {}).get("alerts", [])
                ),
            },
        }

    def get_alerts(self) -> list[dict]:
        alerts = self._company_status().get(
            "audit",
            {},
        ).get("alerts", [])
        normalized = []
        for index, alert in enumerate(alerts):
            row = dict(alert)
            row.setdefault("severity", "attention")
            row["cell_id"] = self.manifest.cell_id
            row["alert_index"] = index
            normalized.append(row)
        return normalized

    def get_recent_events(self, limit: int = 30) -> list[dict]:
        return [
            {
                "cell_id": self.manifest.cell_id,
                "id": event.get("id"),
                "kind": event.get("kind"),
                "created_at": event.get("created_at"),
                "payload": event.get("payload"),
            }
            for event in self.control.get_recent_events(limit)
        ]

    def get_report(self) -> dict:
        status = self.get_status()
        health = self.get_health()
        metrics = self.get_metrics()["metrics"]
        alerts = self.get_alerts()
        highlights = [
            (
                f"Company equity {metrics['company_equity']:.4f}; "
                f"Treasury reserve {metrics['treasury_reserve']:.4f}."
            ),
            (
                f"Trader capacity {metrics['trader_slots']}/"
                f"{metrics['effective_trader_limit']}."
            ),
            (
                f"Gross exposure {metrics['gross_exposure']:.4f}; "
                f"drawdown {metrics['company_drawdown_pct']:.2f}%."
            ),
        ]
        return {
            "cell_id": self.manifest.cell_id,
            "cell_type": self.manifest.cell_type,
            "name": self.manifest.name,
            "operational_state": status["operational_state"],
            "health": health["state"],
            "headline": (
                f"{self.manifest.name}: "
                f"{health['state']} / "
                f"{status['operational_state']}"
            ),
            "highlights": highlights,
            "alert_count": len(alerts),
            "alerts": alerts[:5],
            "metrics": metrics,
            "ui": dict(self.manifest.ui),
        }

    def execute_command(
        self,
        name: str,
        args: dict | None = None,
    ) -> dict:
        del args
        if name not in self.SAFE_COMMANDS:
            raise CellProtocolError("unsupported_cell_command")
        if name == "pause":
            result = self.control.pause_operations()
        elif name == "resume":
            result = self.control.resume_operations()
        else:
            result = self.control.emergency_stop()
        return {
            "cell_id": self.manifest.cell_id,
            "command": name,
            "result": result,
        }
