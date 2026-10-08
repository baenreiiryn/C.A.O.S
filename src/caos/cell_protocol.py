from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


CELL_PROTOCOL_VERSION = "company-cell/v1"


class CellProtocolError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class CellManifest:
    cell_id: str
    cell_type: str
    name: str
    protocol_version: str = CELL_PROTOCOL_VERSION
    autonomy: str = "autonomous"
    capabilities: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    ui: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cell_id.strip():
            raise ValueError("cell_id_required")
        if not self.cell_type.strip():
            raise ValueError("cell_type_required")
        if not self.name.strip():
            raise ValueError("cell_name_required")
        if self.protocol_version != CELL_PROTOCOL_VERSION:
            raise ValueError("unsupported_cell_protocol_version")

    def to_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "cell_type": self.cell_type,
            "name": self.name,
            "protocol_version": self.protocol_version,
            "autonomy": self.autonomy,
            "capabilities": list(self.capabilities),
            "commands": list(self.commands),
            "ui": dict(self.ui),
        }


@runtime_checkable
class CompanyCell(Protocol):
    """Stable generic contract consumed by future supervisors.

    Domain-specific internals remain behind the cell adapter.
    """

    def get_manifest(self) -> dict: ...
    def get_status(self) -> dict: ...
    def get_health(self) -> dict: ...
    def get_metrics(self) -> dict: ...
    def get_alerts(self) -> list[dict]: ...
    def get_recent_events(self, limit: int = 30) -> list[dict]: ...
    def get_report(self) -> dict: ...
    def execute_command(
        self,
        name: str,
        args: dict | None = None,
    ) -> dict: ...
