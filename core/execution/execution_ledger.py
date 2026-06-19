# -*- coding: utf-8 -*-
"""ExecutionLedger — shadow-накопитель денежных потоков из WS (Ф3.3, DS).

Слушает LedgerEvent + FillEvent через шину, накапливает running_sum per account.
Сверяет SUM(o.rp + fee + funding + liquidation) = Dequity против balance_snapshots.
Закрывает разрыв −$435 (комиссии + funding не учтены в simulated_trades).
"""
from __future__ import annotations
import time, logging
from typing import Dict, Optional
from core.execution.domain import LedgerEvent, FillEvent, LedgerEntry

logger = logging.getLogger(__name__)


class AccountLedger:
    """Накопитель леджера для одного аккаунта."""
    def __init__(self, account_id: int, initial_equity: float = 0.0):
        self.account_id = account_id
        self.initial_equity = initial_equity
        # running sums по категориям
        self.realized_pnl: float = 0.0     # o.rp — реализованный PnL из FillEvent
        self.commission: float = 0.0        # o.n — комиссии из FillEvent
        self.funding_fee: float = 0.0       # a.m=FUNDING_FEE
        self.liquidation: float = 0.0       # o.o=LIQUIDATION
        self.entry_count: int = 0

    def apply(self, entry: LedgerEntry) -> None:
        """Применить одну запись леджера."""
        if entry.kind == "REALIZED_PNL":
            self.realized_pnl += entry.amount
        elif entry.kind == "COMMISSION":
            self.commission += entry.amount
        elif entry.kind == "FUNDING_FEE":
            self.funding_fee += entry.amount
        elif entry.kind == "LIQUIDATION":
            self.liquidation += entry.amount
        else:
            logger.debug("[ExecutionLedger] unknown entry kind: %s", entry.kind)
        self.entry_count += 1

    def running_sum(self) -> float:
        """Сумма всех денежных потоков по леджеру."""
        return self.realized_pnl + self.commission + self.funding_fee + self.liquidation

    def reconcile(self, current_equity: float) -> dict:
        """Сверка с текущим equity. Возвращает разбивку."""
        expected = self.initial_equity + self.running_sum()
        gap = current_equity - expected
        return {
            "account": self.account_id,
            "initial_equity": self.initial_equity,
            "current_equity": current_equity,
            "ledger_realized_pnl": self.realized_pnl,
            "ledger_commission": self.commission,
            "ledger_funding": self.funding_fee,
            "ledger_liquidation": self.liquidation,
            "ledger_total": self.running_sum(),
            "expected_equity": expected,
            "gap": gap,
            "entry_count": self.entry_count,
        }


class ExecutionLedger:
    """Shadow-накопитель. Подключается к шине через on_event().
    НЕ влияет на торговлю — только считает."""
    
    def __init__(self):
        self._accounts: Dict[int, AccountLedger] = {}
        logger.info("[ExecutionLedger] initialized (shadow)")

    # ── публичные методы (вызываются из ExecutionSphere.on_event) ──

    def on_ledger_event(self, event: LedgerEvent) -> None:
        """WS: FUNDING_FEE / LIQUIDATION."""
        acc = self._get_or_create(event.account)
        acc.apply(event.entry)

    def on_fill_event(self, event: FillEvent) -> None:
        """WS: fill с realized_pnl и fee."""
        acc = self._get_or_create(event.account)
        fill = event.fill
        # Каждый fill — это один ордер. PnL и комиссия в $.
        if fill.realized_pnl:
            acc.apply(LedgerEntry(
                account=event.account, ts=time.time(),
                kind="REALIZED_PNL", amount=fill.realized_pnl,
                symbol=fill.symbol))
        if fill.fee:
            acc.apply(LedgerEntry(
                account=event.account, ts=time.time(),
                kind="COMMISSION", amount=-abs(fill.fee),
                symbol=fill.symbol))

    def set_initial_equity(self, account: int, equity: float) -> None:
        """Задать начальный equity для сверки (из cold-start снимка)."""
        acc = self._get_or_create(account)
        if acc.initial_equity == 0.0:
            acc.initial_equity = equity

    def running_sum(self, account: int) -> float:
        """Текущая сумма $-потоков по леджеру."""
        return self._accounts[account].running_sum() if account in self._accounts else 0.0

    def reconcile(self, account: int, current_equity: float) -> Optional[dict]:
        """Сверка леджера с текущим equity. Возвращает разбивку или None если нет аккаунта."""
        if account not in self._accounts:
            return None
        return self._accounts[account].reconcile(current_equity)

    def reconcile_all(self, equity_map: Dict[int, float]) -> list[dict]:
        """Массовая сверка по всем аккаунтам."""
        results = []
        for acc_id, equity in equity_map.items():
            r = self.reconcile(acc_id, equity)
            if r:
                results.append(r)
        return results

    def snapshot(self) -> dict:
        """Полный снимок состояния для дашборда/логов."""
        return {
            acc_id: {
                "initial_equity": acc.initial_equity,
                "running_sum": acc.running_sum(),
                "realized_pnl": acc.realized_pnl,
                "commission": acc.commission,
                "funding_fee": acc.funding_fee,
                "liquidation": acc.liquidation,
                "entry_count": acc.entry_count,
            }
            for acc_id, acc in self._accounts.items()
        }

    # ── приватные ──

    def _get_or_create(self, account: int) -> AccountLedger:
        if account not in self._accounts:
            self._accounts[account] = AccountLedger(account)
        return self._accounts[account]
