from __future__ import annotations

from .domain import CompanyPolicy


class CompanyCheckpointError(RuntimeError):
    pass


class CompanyCheckpoint:
    KEY = "trade_company_checkpoint_v1"

    @classmethod
    def save(cls, company, store) -> dict:
        payload = {
            "version": 1,
            "policy": company.policy.to_dict(),
            "effective_trader_limit": company.effective_trader_limit,
            "operations_paused": company.operations_paused,
            "treasury": company.treasury.snapshot(),
            "traders": company.registry.snapshot(),
            "opportunities": company.opportunities.snapshot(),
            "assignments": company.market.snapshot(),
            "risk": company.risk.snapshot(),
            "strategies": company.strategies.snapshot(),
            "training": company.training.snapshot(),
            "research": company.research.snapshot(),
            "rollout": company.rollout.snapshot(),
            "paper": company.paper.snapshot(),
        }
        store.set_json(cls.KEY, payload)
        store.event(
            "trade_company_checkpoint",
            {
                "company_equity": company.treasury.company_equity,
                "trader_slots": company.registry.slot_count(),
                "assignments": len(company.market.assignments),
                "paper_accounts": len(company.paper.accounts),
            },
        )
        return payload

    @staticmethod
    def _validate_policy(company, payload: dict) -> None:
        saved = CompanyPolicy(**payload["policy"])
        if saved != company.policy:
            raise CompanyCheckpointError("company_policy_mismatch")

    @classmethod
    def restore(cls, company, store) -> bool:
        payload = store.get_json(cls.KEY)
        if not payload:
            return False
        if int(payload.get("version", 0)) != 1:
            raise CompanyCheckpointError("unsupported_company_checkpoint")
        cls._validate_policy(company, payload)

        company.treasury.restore(payload["treasury"])
        company.registry.restore(payload["traders"])
        company.opportunities.restore(payload.get("opportunities", {}))
        company.market.restore(payload.get("assignments", {}))
        company.strategies.restore(payload.get("strategies", {}))
        company.training.restore(payload.get("training", {}))
        company.research.restore(payload.get("research", {}))
        company.rollout.restore(payload.get("rollout", {}))
        company.paper.restore(payload.get("paper", {}))

        effective = int(
            payload.get(
                "effective_trader_limit",
                company.policy.operational_trader_cap,
            )
        )
        if not 1 <= effective <= company.policy.operational_trader_cap:
            raise CompanyCheckpointError("invalid_effective_trader_limit")
        if effective < company.registry.slot_count():
            raise CompanyCheckpointError(
                "effective_limit_below_restored_slots"
            )
        company.effective_trader_limit = effective
        company.operations_paused = bool(
            payload.get("operations_paused", False)
        )

        risk = payload.get("risk", {})
        company.risk.state.kill_switch = bool(
            risk.get("kill_switch", False)
        )
        company.risk.state.start_equity = float(
            risk.get(
                "start_equity",
                company.treasury.company_equity,
            )
        )

        cls._validate_integrity(company)
        store.event(
            "trade_company_restore",
            {
                "company_equity": company.treasury.company_equity,
                "trader_slots": company.registry.slot_count(),
                "assignments": len(company.market.assignments),
                "paper_accounts": len(company.paper.accounts),
            },
        )
        return True

    @staticmethod
    def _validate_integrity(company) -> None:
        if company.registry.slot_count() > company.policy.operational_trader_cap:
            raise CompanyCheckpointError("operational_trader_cap_exceeded")

        for trader_id, assignment in company.market.assignments.items():
            trader = company.registry.get(trader_id)
            if trader.market != assignment.symbol:
                raise CompanyCheckpointError(
                    "assignment_trader_market_mismatch"
                )
            opportunity = company.opportunities.get(
                assignment.opportunity_id
            )
            if (
                assignment.mode.value == "production"
                and opportunity.reserved_by != trader_id
            ):
                raise CompanyCheckpointError(
                    "production_reservation_mismatch"
                )

        for trader_id in company.paper.accounts:
            company.registry.get(trader_id)

        for symbol, strategy_id in company.research.champions.items():
            try:
                company.strategies.get(strategy_id)
            except Exception as exc:
                raise CompanyCheckpointError(
                    "research_champion_strategy_missing"
                ) from exc
            if not symbol:
                raise CompanyCheckpointError(
                    "research_champion_symbol_invalid"
                )

        for candidate in company.research.candidates.values():
            if candidate.hypothesis_id not in company.research.hypotheses:
                raise CompanyCheckpointError(
                    "research_candidate_hypothesis_missing"
                )
            if (
                candidate.evaluation_id is not None
                and candidate.evaluation_id
                not in company.research.evaluations
            ):
                raise CompanyCheckpointError(
                    "research_candidate_evaluation_missing"
                )

        for evaluation in company.research.evaluations.values():
            if evaluation.candidate_id not in company.research.candidates:
                raise CompanyCheckpointError(
                    "research_evaluation_candidate_missing"
                )

        mismatches = company.paper.audit_reconciliation()
        if mismatches:
            raise CompanyCheckpointError(
                "paper_treasury_reconciliation_mismatch"
            )
