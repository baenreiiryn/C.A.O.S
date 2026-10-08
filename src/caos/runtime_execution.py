from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .compliance import ComplianceEngine
from .domain import Mode
from .execution_fabric import ExecutionPlan
from .execution_reliability import DurableExecutionJournal
from .testnet import (
    BinanceSpotClient,
    ManualProductionExecutor,
    execution_plan_to_binance_order,
)


class RuntimeExecutionError(RuntimeError):
    pass


class RuntimeExecutionService:
    """Runtime-only execution mode and external broker proposal router.

    PAPER is autonomous. Spot TESTNET may auto-submit after the human selects
    TESTNET mode. Production creates durable proposals and requires one exact
    human confirmation per order. The selected mode is intentionally not
    persisted and therefore always resets to PAPER on process restart.
    """

    MODES = ("paper", "testnet", "real-manual")
    PROPOSAL_KEY = "runtime_execution_proposals_v1"

    def __init__(self, company, config: dict, vault):
        self.company = company
        self.config = config
        self.vault = vault
        self.mode = "paper"
        self.compliance = ComplianceEngine()

    def _profiles(self) -> list[dict]:
        return [
            dict(row)
            for row in self.config.get("broker_profiles", [])
            if isinstance(row, dict)
        ]

    def _active_profile(self) -> dict:
        profile_id = self.config.get("active_broker_profile")
        if not profile_id:
            raise RuntimeExecutionError(
                "active_broker_profile_required"
            )
        for row in self._profiles():
            if str(row.get("id")) == str(profile_id):
                return row
        raise RuntimeExecutionError(
            "active_broker_profile_not_found"
        )

    def _credential(self, profile_id: str, field: str) -> str:
        value = self.vault.get(
            f"broker:{profile_id}:{field}"
        )
        if not value:
            raise RuntimeExecutionError(
                "broker_credentials_required"
            )
        return str(value)

    def _client(
        self,
        *,
        environment: str,
        manual_production: bool = False,
    ) -> BinanceSpotClient:
        profile = self._active_profile()
        profile_id = str(profile["id"])
        if str(profile.get("provider")) != "binance":
            raise RuntimeExecutionError(
                "active_broker_must_be_binance"
            )
        if str(profile.get("environment")) != environment:
            raise RuntimeExecutionError(
                "active_broker_environment_mismatch"
            )
        return BinanceSpotClient(
            self._credential(profile_id, "api_key"),
            self._credential(profile_id, "api_secret"),
            environment=environment,
            allow_manual_production_orders=manual_production,
        )

    def _journal(
        self,
        environment: str,
    ) -> DurableExecutionJournal:
        if self.company.store is None:
            raise RuntimeExecutionError(
                "persistent_store_required"
            )
        return DurableExecutionJournal(
            self.company.store,
            venue="binance",
            environment=environment,
        )

    def _proposal_map(self) -> dict[str, dict]:
        if self.company.store is None:
            return {}
        raw = self.company.store.get_json(
            self.PROPOSAL_KEY,
            {},
        )
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def _save_proposals(
        self,
        proposals: dict[str, dict],
    ) -> None:
        if self.company.store is not None:
            self.company.store.set_json(
                self.PROPOSAL_KEY,
                proposals,
            )

    @staticmethod
    def _plan_from_dict(row: dict) -> ExecutionPlan:
        fields = {
            key: row[key]
            for key in (
                "symbol",
                "strategy_id",
                "decision_id",
                "action",
                "side",
                "current_notional",
                "desired_target_notional",
                "effective_target_notional",
                "order_notional",
                "reference_price",
                "risk_reducing",
                "allow_new_risk",
                "plan_id",
            )
        }
        return ExecutionPlan(**fields)

    def _outstanding_for_trader(
        self,
        trader_id: str,
    ) -> dict | None:
        for intent_id, meta in self._proposal_map().items():
            if str(meta.get("trader_id")) != str(trader_id):
                continue
            if meta.get("mirrored"):
                continue
            environment = str(meta.get("environment", ""))
            try:
                row = self._journal(environment).get(intent_id)
            except Exception:
                continue
            if row["status"] in {
                "prepared",
                "submitting",
                "acknowledged",
                "uncertain",
            }:
                return {
                    "intent": row,
                    "meta": meta,
                }
        return None

    def has_outstanding(self, trader_id: str) -> bool:
        return self._outstanding_for_trader(trader_id) is not None

    def _all_positions_flat(self) -> bool:
        return all(
            self.company.paper.positions_flat(trader_id)
            for trader_id in self.company.paper.accounts
        )

    def status(self) -> dict:
        profile = None
        try:
            profile = self._active_profile()
        except Exception:
            pass
        pending = self.list_proposals(
            statuses=(
                "prepared",
                "submitting",
                "acknowledged",
                "uncertain",
            )
        )
        return {
            "mode": self.mode,
            "available_modes": list(self.MODES),
            "runtime_only": True,
            "resets_to_paper_on_restart": True,
            "active_broker_profile": (
                dict(profile) if profile else None
            ),
            "pending_confirmations": sum(
                row["status"] == "prepared"
                and row["environment"] == "production-manual"
                for row in pending
            ),
            "unresolved": len(pending),
        }

    def set_mode(
        self,
        mode: str,
        *,
        confirmation: str = "",
    ) -> dict:
        mode = str(mode).strip().lower()
        if mode not in self.MODES:
            raise RuntimeExecutionError(
                "unsupported_execution_mode"
            )
        if self.company.operational_state() != "stopped":
            raise RuntimeExecutionError(
                "execution_mode_change_requires_stopped_company"
            )
        if not self._all_positions_flat():
            raise RuntimeExecutionError(
                "execution_mode_change_requires_flat_positions"
            )
        if any(
            self.company.paper.has_pending_order(trader_id)
            for trader_id in self.company.paper.accounts
        ):
            raise RuntimeExecutionError(
                "execution_mode_change_requires_no_pending_paper_orders"
            )

        if mode == "testnet":
            self._client(environment="spot-testnet")
            self.compliance.human_arm_testnet(
                confirmation="ARM TESTNET"
            )
        elif mode == "real-manual":
            if confirmation != "ENABLE REAL":
                raise RuntimeExecutionError(
                    "explicit_real_mode_confirmation_required"
                )
            self._client(
                environment="production-manual",
                manual_production=False,
            )
            self.compliance.human_disarm_live()
        else:
            self.compliance.human_disarm_testnet()
            self.compliance.human_disarm_live()

        self.mode = mode
        if self.company.store is not None:
            self.company.store.event(
                "runtime_execution_mode_changed",
                {
                    "mode": mode,
                    "runtime_only": True,
                },
            )
        return self.status()

    def _prepare(
        self,
        trader_id: str,
        preview: dict,
        *,
        environment: str,
        source: str,
    ) -> dict:
        plan = self._plan_from_dict(preview["plan"])
        payload = execution_plan_to_binance_order(
            plan,
            order_type="MARKET",
        )
        intent = self._journal(environment).prepare(
            plan,
            payload,
        )
        proposals = self._proposal_map()
        proposals[intent["intent_id"]] = {
            "intent_id": intent["intent_id"],
            "trader_id": trader_id,
            "environment": environment,
            "source": source,
            "mode": self.mode,
            "plan": preview["plan"],
            "decision": preview.get("decision"),
            "target": preview.get("target"),
            "as_of": preview.get("as_of"),
            "mirrored": False,
        }
        self._save_proposals(proposals)
        return {
            "intent": intent,
            "meta": proposals[intent["intent_id"]],
        }

    def cycle_trader(
        self,
        trader_id: str,
        *,
        allow_new_risk: bool = True,
    ):
        from .company.paper import TraderPaperCycle

        if self.mode == "paper":
            return self.company.paper.cycle_trader(
                trader_id,
                allow_new_risk=allow_new_risk,
            )

        outstanding = self._outstanding_for_trader(
            trader_id
        )
        if outstanding is not None:
            return TraderPaperCycle(
                trader_id,
                (
                    "awaiting_human_confirmation"
                    if (
                        outstanding["intent"]["status"]
                        == "prepared"
                        and self.mode == "real-manual"
                    )
                    else "awaiting_broker_reconciliation"
                ),
                None,
                None,
                self.company.paper.marked_equity(trader_id),
                self.company.paper.realized_equity(trader_id),
                plan=outstanding["meta"].get("plan"),
            )

        preview = self.company.paper.preview_external_plan(
            trader_id,
            allow_new_risk=allow_new_risk,
        )
        plan = self._plan_from_dict(preview["plan"])
        if not plan.executable:
            return TraderPaperCycle(
                trader_id,
                "no_state_change",
                preview.get("signal"),
                None,
                preview["equity"],
                preview["realized_equity"],
                preview.get("decision"),
                preview.get("target"),
                preview.get("plan"),
            )

        if self.mode == "real-manual":
            prepared = self._prepare(
                trader_id,
                preview,
                environment="production-manual",
                source="agent_proposal",
            )
            return TraderPaperCycle(
                trader_id,
                "awaiting_human_confirmation",
                preview.get("signal"),
                None,
                preview["equity"],
                preview["realized_equity"],
                preview.get("decision"),
                preview.get("target"),
                {
                    **preview["plan"],
                    "intent_id": prepared[
                        "intent"
                    ]["intent_id"],
                },
            )

        prepared = self._prepare(
            trader_id,
            preview,
            environment="spot-testnet",
            source="agent_testnet",
        )
        submitted = self._submit_testnet(
            prepared["intent"]["intent_id"]
        )
        self._mirror_if_filled(
            prepared["intent"]["intent_id"],
            submitted,
        )
        return TraderPaperCycle(
            trader_id,
            "testnet_submitted",
            preview.get("signal"),
            None,
            self.company.paper.marked_equity(trader_id),
            self.company.paper.realized_equity(trader_id),
            preview.get("decision"),
            preview.get("target"),
            {
                **preview["plan"],
                "intent_id": prepared[
                    "intent"
                ]["intent_id"],
            },
        )

    def _submit_testnet(
        self,
        intent_id: str,
    ) -> dict:
        self.compliance.allow_mode(Mode.TESTNET)
        journal = self._journal("spot-testnet")
        claimed = journal.claim_for_submit(intent_id)
        client = self._client(
            environment="spot-testnet",
        )
        payload = dict(claimed["payload"])
        payload["new_order_resp_type"] = "FULL"
        try:
            ack = client.place_order(**payload)
        except Exception as exc:
            journal.mark_uncertain(
                intent_id,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        return journal.mark_acknowledged(
            intent_id,
            broker_order_id=ack.order_id,
            broker_order_link_id=ack.order_link_id,
            raw=ack.raw,
        )

    @staticmethod
    def _fill_from_broker_row(
        row: dict,
    ) -> tuple[float, float] | None:
        raw = row.get("reconciliation_payload") or {}
        if str(raw.get("status", "")).upper() != "FILLED":
            return None
        try:
            qty = Decimal(
                str(raw.get("executedQty", "0"))
            )
            quote = Decimal(
                str(
                    raw.get(
                        "cummulativeQuoteQty",
                        "0",
                    )
                )
            )
        except InvalidOperation:
            return None
        if qty <= 0:
            return None
        price = (
            quote / qty
            if quote > 0
            else Decimal(
                str(raw.get("price", "0"))
            )
        )
        if price <= 0:
            return None
        return float(price), float(qty)

    def _mirror_if_filled(
        self,
        intent_id: str,
        row: dict,
    ) -> bool:
        proposals = self._proposal_map()
        meta = proposals.get(intent_id)
        if not meta or meta.get("mirrored"):
            return bool(meta and meta.get("mirrored"))
        fill = self._fill_from_broker_row(row)
        if fill is None:
            return False
        price, quantity = fill
        self.company.paper.apply_external_fill(
            str(meta["trader_id"]),
            plan=dict(meta["plan"]),
            price=price,
            quantity=quantity,
            ts=int(meta.get("as_of") or 0),
        )
        meta["mirrored"] = True
        meta["fill_price"] = price
        meta["fill_quantity"] = quantity
        proposals[intent_id] = meta
        self._save_proposals(proposals)
        self.company.checkpoint()
        return True

    def confirm_real(
        self,
        intent_id: str,
        *,
        confirmation: str,
    ) -> dict:
        if self.mode != "real-manual":
            raise RuntimeExecutionError(
                "real_mode_not_enabled"
            )
        meta = self._proposal_map().get(str(intent_id))
        if (
            not meta
            or meta.get("environment")
            != "production-manual"
        ):
            raise RuntimeExecutionError(
                "unknown_real_execution_proposal"
            )
        client = self._client(
            environment="production-manual",
            manual_production=True,
        )
        executor = ManualProductionExecutor(
            self.compliance,
            client,
            self._journal("production-manual"),
        )
        row = executor.submit_intent(
            str(intent_id),
            confirmation=confirmation,
        )
        self._mirror_if_filled(str(intent_id), row)
        return self.proposal(str(intent_id))

    def reject_real(
        self,
        intent_id: str,
    ) -> dict:
        meta = self._proposal_map().get(str(intent_id))
        if (
            not meta
            or meta.get("environment")
            != "production-manual"
        ):
            raise RuntimeExecutionError(
                "unknown_real_execution_proposal"
            )
        row = self._journal(
            "production-manual"
        ).reject_prepared(str(intent_id))
        return {
            **row,
            "meta": meta,
        }

    def proposal(self, intent_id: str) -> dict:
        meta = self._proposal_map().get(str(intent_id))
        if not meta:
            raise RuntimeExecutionError(
                "unknown_execution_proposal"
            )
        row = self._journal(
            str(meta["environment"])
        ).get(str(intent_id))
        return {
            **row,
            "meta": meta,
        }

    def list_proposals(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict]:
        rows: list[dict] = []
        for intent_id, meta in self._proposal_map().items():
            try:
                row = self._journal(
                    str(meta["environment"])
                ).get(intent_id)
            except Exception:
                continue
            if statuses and row["status"] not in statuses:
                continue
            rows.append(
                {
                    **row,
                    "meta": meta,
                }
            )
        rows.sort(
            key=lambda row: (
                str(row.get("created_at", "")),
                str(row.get("intent_id", "")),
            ),
            reverse=True,
        )
        return rows

    def cancel_new_risk_proposals(self) -> list[str]:
        rejected: list[str] = []
        for row in self.list_proposals(
            statuses=("prepared",)
        ):
            if (
                row["environment"] == "production-manual"
                and row["payload"].get("side") == "BUY"
            ):
                self._journal(
                    "production-manual"
                ).reject_prepared(
                    row["intent_id"],
                    reason="operations_stopped",
                )
                rejected.append(row["intent_id"])
        return rejected

    def emergency_stop(self) -> dict:
        if self.mode != "real-manual":
            return self.company.emergency_stop()

        rejected = self.cancel_new_risk_proposals()
        self.company.operations_paused = True
        self.company.risk.kill()

        close_proposals: list[str] = []
        for trader_id in list(self.company.paper.accounts):
            if self.company.paper.positions_flat(trader_id):
                continue
            outstanding = self._outstanding_for_trader(
                trader_id
            )
            if outstanding is not None:
                if (
                    outstanding["intent"]["status"]
                    == "prepared"
                    and outstanding["intent"][
                        "payload"
                    ].get("side") == "SELL"
                ):
                    close_proposals.append(
                        outstanding["intent"]["intent_id"]
                    )
                continue
            preview = self.company.paper.preview_external_plan(
                trader_id,
                allow_new_risk=False,
            )
            plan = self._plan_from_dict(preview["plan"])
            if plan.executable and plan.side == "sell":
                prepared = self._prepare(
                    trader_id,
                    preview,
                    environment="production-manual",
                    source="emergency_close",
                )
                close_proposals.append(
                    prepared["intent"]["intent_id"]
                )

        engine_result = None
        try:
            engine_result = self.company.engine.emergency_kill()
        except Exception as exc:
            engine_result = {
                "error": f"{type(exc).__name__}: {exc}",
            }
        self.company.checkpoint()
        return {
            "company_kill_switch": True,
            "operations_paused": True,
            "operational_state": "emergency_stopped",
            "rejected_entry_proposals": rejected,
            "manual_close_proposals": close_proposals,
            "requires_human_confirmation": bool(
                close_proposals
            ),
            "caos": engine_result,
        }
