from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import uuid4


def _money(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))


@dataclass(slots=True, frozen=True)
class LedgerEntry:
    id: str
    kind: str
    amount: float
    from_account: str | None
    to_account: str | None
    trader_id: str | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class TreasuryError(RuntimeError):
    pass


class Treasury:
    """Company-owned capital ledger.

    Trader buckets are accounts controlled by the Company. They are not
    ownership branches and never settle through trader genealogy.
    """

    RESERVE = "TREASURY_RESERVE"

    def __init__(self, initial_capital: float):
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self._balances: dict[str, Decimal] = {self.RESERVE: Decimal("0")}
        self.entries: list[LedgerEntry] = []
        self._external_adjustment(
            kind="deposit",
            account=self.RESERVE,
            amount=_money(initial_capital),
            trader_id=None,
            note="initial_company_capital",
        )

    @staticmethod
    def trader_account(trader_id: str) -> str:
        if not trader_id:
            raise ValueError("trader_id required")
        return f"TRADER:{trader_id}"

    def _append(
        self,
        *,
        kind: str,
        amount: Decimal,
        from_account: str | None,
        to_account: str | None,
        trader_id: str | None,
        note: str,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            id=uuid4().hex,
            kind=kind,
            amount=float(amount),
            from_account=from_account,
            to_account=to_account,
            trader_id=trader_id,
            note=note,
        )
        self.entries.append(entry)
        return entry

    def _transfer(
        self,
        *,
        kind: str,
        source: str,
        target: str,
        amount: Decimal,
        trader_id: str | None = None,
        note: str = "",
    ) -> LedgerEntry:
        if amount <= 0:
            raise TreasuryError("amount_must_be_positive")
        source_balance = self._balances.get(source, Decimal("0"))
        if source_balance + Decimal("0.000000001") < amount:
            raise TreasuryError("insufficient_funds")
        self._balances[source] = source_balance - amount
        self._balances[target] = self._balances.get(target, Decimal("0")) + amount
        return self._append(
            kind=kind,
            amount=amount,
            from_account=source,
            to_account=target,
            trader_id=trader_id,
            note=note,
        )

    def _external_adjustment(
        self,
        *,
        kind: str,
        account: str,
        amount: Decimal,
        trader_id: str | None,
        note: str,
    ) -> LedgerEntry:
        if amount == 0:
            raise TreasuryError("amount_cannot_be_zero")
        current = self._balances.get(account, Decimal("0"))
        nxt = current + amount
        if nxt < Decimal("-0.000000001"):
            raise TreasuryError("account_cannot_go_negative")
        self._balances[account] = max(Decimal("0"), nxt)
        return self._append(
            kind=kind,
            amount=abs(amount),
            from_account=None if amount > 0 else account,
            to_account=account if amount > 0 else None,
            trader_id=trader_id,
            note=note,
        )

    @property
    def reserve(self) -> float:
        return float(self._balances.get(self.RESERVE, Decimal("0")))

    @property
    def company_equity(self) -> float:
        return float(sum(self._balances.values(), Decimal("0")))

    def balance(self, trader_id: str) -> float:
        return float(
            self._balances.get(self.trader_account(trader_id), Decimal("0"))
        )

    def allocate(
        self,
        trader_id: str,
        amount: float,
        *,
        note: str = "capital_allocation",
    ) -> LedgerEntry:
        return self._transfer(
            kind="allocation",
            source=self.RESERVE,
            target=self.trader_account(trader_id),
            amount=_money(amount),
            trader_id=trader_id,
            note=note,
        )

    def harvest(
        self,
        trader_id: str,
        amount: float,
        *,
        note: str = "capital_harvest",
    ) -> LedgerEntry:
        return self._transfer(
            kind="harvest",
            source=self.trader_account(trader_id),
            target=self.RESERVE,
            amount=_money(amount),
            trader_id=trader_id,
            note=note,
        )

    def harvest_all(
        self,
        trader_id: str,
        *,
        note: str = "trader_settlement",
    ) -> float:
        amount = self.balance(trader_id)
        if amount > 0:
            self.harvest(trader_id, amount, note=note)
        return amount

    def record_pnl(self, trader_id: str, pnl: float) -> LedgerEntry:
        if pnl == 0:
            raise TreasuryError("pnl_cannot_be_zero")
        return self._external_adjustment(
            kind="realized_pnl",
            account=self.trader_account(trader_id),
            amount=_money(pnl),
            trader_id=trader_id,
            note="realized_trade_result",
        )

    def record_fee(self, trader_id: str, fee: float) -> LedgerEntry:
        if fee <= 0:
            raise TreasuryError("fee_must_be_positive")
        return self._external_adjustment(
            kind="fee",
            account=self.trader_account(trader_id),
            amount=-_money(fee),
            trader_id=trader_id,
            note="broker_fee",
        )

    def reconcile_balance(
        self,
        trader_id: str,
        target_equity: float,
        *,
        note: str = "account_reconciliation",
    ) -> LedgerEntry | None:
        target = _money(target_equity)
        if target < 0:
            raise TreasuryError("target_equity_cannot_be_negative")
        account = self.trader_account(trader_id)
        current = self._balances.get(account, Decimal("0"))
        delta = target - current
        if abs(delta) <= Decimal("0.000000001"):
            return None
        return self._external_adjustment(
            kind="reconciliation",
            account=account,
            amount=delta,
            trader_id=trader_id,
            note=note,
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "Treasury":
        balances = {
            str(account): _money(value)
            for account, value in snapshot.get("balances", {}).items()
        }
        if cls.RESERVE not in balances:
            raise TreasuryError("treasury_reserve_missing")
        if any(value < 0 for value in balances.values()):
            raise TreasuryError("negative_balance_in_snapshot")
        obj = cls.__new__(cls)
        obj._balances = balances
        obj.entries = [
            LedgerEntry(**row)
            for row in snapshot.get("ledger", [])
        ]
        expected = _money(snapshot.get("company_equity", sum(balances.values())))
        actual = sum(balances.values(), Decimal("0"))
        if abs(expected - actual) > Decimal("0.000001"):
            raise TreasuryError("company_equity_snapshot_mismatch")
        return obj

    def snapshot(self) -> dict:
        return {
            "company_equity": self.company_equity,
            "reserve": self.reserve,
            "balances": {
                account: float(balance)
                for account, balance in sorted(self._balances.items())
            },
            "ledger": [entry.to_dict() for entry in self.entries],
        }
