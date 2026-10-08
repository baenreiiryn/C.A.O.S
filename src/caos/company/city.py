from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CityLocation:
    id: str
    title: str
    technical_name: str
    character: str
    state: str
    summary: str
    attention: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "technical_name": self.technical_name,
            "character": self.character,
            "state": self.state,
            "summary": self.summary,
            "attention": self.attention,
        }


class CityPresentationMapper:
    """Presentation-only mapper from Company state to fantasy city state."""

    ALERT_LOCATION = {
        "operational_trader_cap_violated": "citadel",
        "trader_stop_floor": "risk",
        "funded_trader_unassigned": "guild",
        "direction_concentration": "risk",
        "strategy_family_concentration": "risk",
        "paper_treasury_reconciliation_mismatch": "treasury",
        "company_kill_switch": "risk",
        "caos_kill_switch": "nexus",
    }

    def build(
        self,
        status: dict,
        *,
        improvements: list[dict] | None = None,
        recent_events: list[dict] | None = None,
    ) -> dict:
        audit = status.get("audit", {})
        alerts = list(audit.get("alerts", []))
        improvements = list(improvements or [])
        events = list(recent_events or [])
        severity = {
            str(alert.get("severity", "attention")).lower()
            for alert in alerts
        }
        if status.get("risk", {}).get("kill_switch"):
            mood = "emergency"
        elif status.get("operations_paused"):
            mood = "paused"
        elif "critical" in severity or audit.get("status") == "critical":
            mood = "critical"
        elif alerts:
            mood = "attention"
        else:
            mood = "healthy"

        alert_locations = {
            self.ALERT_LOCATION.get(str(alert.get("kind")), "citadel")
            for alert in alerts
        }
        traders = status.get("traders", {}).get("traders", {})
        active = sum(
            row.get("status") == "active"
            for row in traders.values()
        )
        waiting = sum(
            row.get("status") == "waiting_assignment"
            for row in traders.values()
        )
        paused = sum(
            row.get("status") == "paused"
            for row in traders.values()
        )
        experiments = status.get("training", {})
        opportunities = status.get("opportunities", {})
        available = sum(
            row.get("status") == "available"
            for row in opportunities.values()
        )
        news = status.get("caos", {}).get("news", {})
        experts = status.get("caos", {}).get("experts", {})
        reserve = float(status.get("treasury", {}).get("reserve", 0.0))
        spawn_capacity = int(status.get("treasury_spawn_capacity", 0))
        drawdown = float(status.get("risk", {}).get("drawdown_pct", 0.0))
        reconciliation = status.get("reconciliation_mismatches", [])
        symbols = status.get("caos", {}).get("symbols_loaded", [])

        def loc(
            id: str,
            title: str,
            technical: str,
            character: str,
            state: str,
            summary: str,
        ) -> CityLocation:
            return CityLocation(
                id=id,
                title=title,
                technical_name=technical,
                character=character,
                state=state,
                summary=summary,
                attention=id in alert_locations,
            )

        locations = [
            loc(
                "citadel",
                "Citadel of Oversight",
                "CompanySupervisor",
                "Royal Steward",
                audit.get("status", "unknown"),
                f"{len(alerts)} alert(s) across the city.",
            ),
            loc(
                "treasury",
                "Grand Vault",
                "Treasury + CapitalAllocator",
                "Royal Treasurer",
                "critical" if reconciliation else "healthy",
                (
                    f"Reserve ${reserve:.2f}; "
                    f"funding capacity {spawn_capacity} Trader(s)."
                ),
            ),
            loc(
                "risk",
                "Tower of Wards",
                "CompanyRiskGovernor + StrategyDiversity",
                "Archmage of Wards",
                "emergency"
                if status.get("risk", {}).get("kill_switch")
                else ("attention" if "risk" in alert_locations else "healthy"),
                f"Company drawdown {drawdown:.2f}%.",
            ),
            loc(
                "guild",
                "Grand Trading Guild",
                "TraderRegistry + MarketAllocator + StrategyRegistry",
                "Guild Questmaster",
                "attention" if waiting else "active",
                (
                    f"{active} active, {waiting} waiting, "
                    f"{paused} paused Trader(s)."
                ),
            ),
            loc(
                "quests",
                "Quest Board",
                "OpportunityRegistry",
                "Guild Scribe",
                "active" if opportunities else "quiet",
                (
                    f"{len(opportunities)} opportunity scroll(s), "
                    f"{available} available."
                ),
            ),
            loc(
                "scout",
                "Scout Lodge",
                "MarketScout",
                "Royal Pathfinder",
                "active" if symbols else "quiet",
                f"{len(symbols)} market symbol(s) loaded.",
            ),
            loc(
                "observatory",
                "Arcane Observatory",
                "C.A.O.S Quant / Market Regime",
                "Market Seer",
                "active" if symbols else "quiet",
                (
                    f"Watching {len(symbols)} symbol(s) through "
                    "deterministic market analysis."
                ),
            ),
            loc(
                "tavern",
                "The Whispering Tankard",
                "News / Sentiment",
                "Bard of Rumors",
                "active" if news.get("configured") else "quiet",
                (
                    f"{news.get('feeds', 0)} news feed(s) configured."
                    if news.get("configured")
                    else "No news messengers configured."
                ),
            ),
            loc(
                "arena",
                "Grand Tournament Arena",
                "TrainingArena",
                "Arena Master",
                "active" if experiments else "quiet",
                f"{len(experiments)} experiment(s) recorded.",
            ),
            loc(
                "workshop",
                "Arcane Workshop",
                "ImprovementManager",
                "Royal Arcanist",
                "attention" if improvements else "quiet",
                f"{len(improvements)} improvement proposal(s).",
            ),
            loc(
                "nexus",
                "Arcane Nexus",
                "C.A.O.S",
                "Arcane Engine",
                "critical"
                if status.get("caos", {}).get("kill_switch")
                else "healthy",
                (
                    f"{len(experts.get('forecast', []))} forecast oracle(s); "
                    f"sentiment oracle: {experts.get('sentiment') or 'none'}."
                ),
            ),
            loc(
                "chronicle",
                "Chronicle Vault",
                "CompanyCheckpoint + Store",
                "Keeper of Chronicles",
                "active" if events else "quiet",
                f"{len(events)} recent persisted event(s) available.",
            ),
        ]

        return {
            "city": {
                "name": "Trade Company",
                "subtitle": "Arcane Trading City",
                "mode": "standalone",
                "mood": mood,
                "health": audit.get("status", "unknown"),
                "emergency": bool(
                    status.get("risk", {}).get("kill_switch")
                ),
                "operations_paused": bool(
                    status.get("operations_paused")
                ),
                "company_equity": status.get(
                    "marked_company_equity",
                    0.0,
                ),
                "treasury_reserve": reserve,
                "active_traders": active,
                "trader_slots": status.get(
                    "traders",
                    {},
                ).get("slot_count", 0),
                "effective_trader_limit": status.get(
                    "effective_trader_limit",
                    0,
                ),
                "alerts": len(alerts),
            },
            "locations": {
                location.id: location.to_dict()
                for location in locations
            },
            "traders": list(traders.values()),
            "alerts": alerts,
            "improvements": improvements,
            "recent_events": events,
        }
