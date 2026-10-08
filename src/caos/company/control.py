from __future__ import annotations

from .company import TradeCompany


class CompanyControlPort:
    """Safe external control surface for CLI/UI and a future Drizzt adapter.

    This interface deliberately contains no direct broker or credential access.
    """

    def __init__(self, company: TradeCompany):
        self.company = company

    def get_company_status(self) -> dict:
        return self.company.status()

    def get_treasury(self) -> dict:
        return self.company.treasury.snapshot()

    def list_traders(self) -> list[dict]:
        return [
            trader.to_dict()
            for trader in self.company.registry.traders.values()
        ]

    def list_opportunities(self) -> list[dict]:
        return [
            opportunity.to_dict()
            for opportunity in self.company.opportunities.opportunities.values()
        ]

    def list_experiments(self) -> list[dict]:
        return [
            experiment.to_dict()
            for experiment in self.company.training.experiments.values()
        ]

    def get_execution_plans(self) -> dict:
        return {
            "version": self.company.status()[
                "execution_fabric"
            ]["version"],
            "last_plans": dict(
                self.company.paper.last_plans
            ),
        }

    def get_recent_events(self, limit: int = 30) -> list[dict]:
        if self.company.store is None:
            return []
        return self.company.store.recent_events(
            max(1, min(int(limit), 100))
        )

    def pause_operations(self) -> dict:
        return self.company.pause_operations()

    def resume_operations(self) -> dict:
        return self.company.resume_operations()

    def pause_trader(self, trader_id: str) -> dict:
        return self.company.pause_trader(trader_id)

    def resume_trader(self, trader_id: str) -> dict:
        return self.company.resume_trader(trader_id)

    def set_effective_trader_limit(self, limit: int) -> dict:
        return {
            "effective_trader_limit": self.company.set_effective_trader_limit(limit)
        }

    def set_operational_trader_limit(self, limit: int) -> dict:
        return self.set_effective_trader_limit(limit)

    def configure_trader_exposure(
        self,
        trader_id: str,
        *,
        max_trade_exposure_pct: float,
        trade_exposure_pct: float | None = None,
    ) -> dict:
        return self.company.configure_trader_exposure(
            trader_id,
            max_trade_exposure_pct=max_trade_exposure_pct,
            trade_exposure_pct=trade_exposure_pct,
        )

    def request_improvement(self) -> list[dict]:
        return self.company.improvement_proposals()

    def emergency_stop(self) -> dict:
        return self.company.emergency_stop()
