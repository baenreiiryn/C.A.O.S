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

    def pause_trader(self, trader_id: str) -> dict:
        return self.company.pause_trader(trader_id)

    def resume_trader(self, trader_id: str) -> dict:
        return self.company.resume_trader(trader_id)

    def set_effective_trader_limit(self, limit: int) -> dict:
        return {
            "effective_trader_limit": self.company.set_effective_trader_limit(limit)
        }

    def request_improvement(self) -> list[dict]:
        return self.company.improvement_proposals()

    def emergency_stop(self) -> dict:
        return self.company.emergency_stop()
