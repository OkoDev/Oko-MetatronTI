"""core.execution.position_store — PositionStore (Ф3.3, Даат).

ЕДИНСТВЕННЫЙ владелец состояния позиций (дизайн §1/§6). Заменяет три конкурирующих
источника (WS pa=0 ∥ REST polling open_pairs ∥ SIM свеча) одним: WS-истина + cold-start.
Консенсус роя 5/5: PositionStore из WS + cold-start REST = индустриальный паттерн.

Чистое in-memory состояние (без IO/БД) — БД метит ExecutionSphere по флагу flat отсюда.
PositionStore НЕ закрывает сделки сам; он отдаёт:
  - apply_position(pa=0) → Position которая стала ФЛЭТ (триггер close для Sphere)
  - take_exit() → ExitInfo (цена/realized/статус из закрывающего fill) для классификации
  - staleness() → сек без WS-события (bounded-staleness watchdog §6, страховка от дропа WS)

Hedge-aware: ключ (account, symbol, side).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from core.execution.domain import FillEvent, Position, PositionEvent

# order_type → статус закрытия БД (как _ORDER_TYPE_TO_STATUS в position_sync, единый смысл)
_STATUS_BY_ORDER_TYPE = {
    "STOP": "SL", "STOP_MARKET": "SL",
    "TAKE_PROFIT": "TP", "TAKE_PROFIT_MARKET": "TP",
    "TRAILING_STOP_MARKET": "TSL", "TRAILING_TP_SL": "TSL",
    "LIQUIDATION": "LIQUIDATION",
}


def classify_exit(order_type: str, realized_pnl: float = 0.0) -> str:
    """Тип закрывающего ордера → статус. MARKET reduceOnly (ручное/emergency) → по знаку PnL."""
    ot = (order_type or "").upper()
    if ot in _STATUS_BY_ORDER_TYPE:
        return _STATUS_BY_ORDER_TYPE[ot]
    # MARKET reduceOnly или неизвестный — классифицируем по результату
    return "TP" if realized_pnl >= 0 else "SL"


@dataclass(frozen=True)
class ExitInfo:
    """Данные закрывающего fill — для классификации close в БД (из o.ap/o.rp/o.o)."""
    symbol: str
    side: str
    account: int
    exit_price: float
    realized_pnl: float
    status: str                 # SL | TP | TSL | LIQUIDATION
    order_type: str
    position_id: Optional[str] = None
    ts: float = 0.0


@dataclass
class PositionStore:
    """In-memory WS-истина позиций + stash закрывающих fill'ов + staleness-метрика."""
    _pos: dict = field(default_factory=dict)          # (account, symbol, side) → Position
    _exit: dict = field(default_factory=dict)         # (account, symbol, side) → ExitInfo
    _last_ws_ts: dict = field(default_factory=dict)   # account → monotonic ts
    _cr: dict = field(default_factory=dict)           # (account, symbol, side) → последний cr при pa>0

    # ── cold-start ─────────────────────────────────────────────────────────
    def init_account(self, account: int, positions: list[Position]) -> None:
        """Cold-start снимок (adapter.get_positions). Сбрасывает прежнее состояние аккаунта."""
        for key in [k for k in self._pos if k[0] == account]:
            del self._pos[key]
        for p in positions:
            if not p.is_flat:
                self._pos[(account, p.symbol, p.side)] = p
        self._touch(account)

    # ── WS-события ───────────────────────────────────────────────────────────
    def apply_position(self, ev: PositionEvent) -> Optional[Position]:
        """ACCOUNT_UPDATE P[]. pa=0 → вернуть ставшую ФЛЭТ позицию (триггер close), иначе upsert.

        Возврат != None ⇒ Sphere должен закрыть сделку в БД (единственный авторитетный close).
        """
        p = ev.position
        key = (ev.account, p.symbol, p.side)
        self._touch(ev.account)
        if p.is_flat:
            prev = self._pos.pop(key, None)
            return prev  # была отслеживаемой → флэт-триггер; None если её и не было (idempotent)
        # pa>0 — обновляем/создаём; сохраняем уже известный position_id если WS его не прислал
        if key in self._pos and not p.position_id and self._pos[key].position_id:
            p.position_id = self._pos[key].position_id
        # 🔴 pa-глюк BingX (LAB 13.07: pa 52.2→522.0 ×10 при НЕИЗМЕННОМ ep, без fill'ов):
        # реальный добор сдвинул бы среднюю цену входа — qty-скачок >×2.5 при том же ep =
        # мусор, оставляем прежний qty (иначе CR-DELTA восстановит цену от отравленного qty)
        cur = self._pos.get(key)
        if (cur is not None and cur.qty and p.qty > cur.qty * 2.5
                and p.entry and cur.entry and abs(p.entry - cur.entry) / cur.entry < 1e-6):
            p.qty = cur.qty
        self._pos[key] = p
        # стеш cr при живой позиции: cr сбрасывается при новом цикле (ORDI 13.07) →
        # дельта на закрытии считается от ПОСЛЕДНЕГО виденного значения
        if p.cum_realized is not None:
            self._cr[key] = p.cum_realized
        return None

    def apply_fill(self, ev: FillEvent) -> None:
        """ORDER_TRADE_UPDATE. open-fill → обогатить позицию (entry/positionId);
        close-fill → застешить ExitInfo для последующего pa=0 (классификация)."""
        f = ev.fill
        key = (ev.account, f.symbol, f.pos_side)
        self._touch(ev.account)
        if f.is_open_fill:
            cur = self._pos.get(key)
            if cur is not None:
                if f.position_id:
                    cur.position_id = f.position_id
                if f.avg_price:
                    cur.entry = f.avg_price
            # если позиции ещё нет (pa-апдейт не пришёл) — создадим лёгкую запись
            elif f.total_qty > 0:
                self._pos[key] = Position(
                    symbol=f.symbol, side=f.pos_side, qty=f.total_qty, account=ev.account,
                    entry=f.avg_price or None, position_id=f.position_id, updated_ts=time.time(),
                )
        else:
            # 🔴 14.07 ZBT-класс, рубеж №2: exit-стеш ТОЛЬКО для закрывающей стороны
            # (SELL+LONG | BUY+SHORT). Открывающая сторона (LIMIT-вход радара проскакивал
            # мимо is_open_fill из-за MARKET-фильтра) НЕ exit — иначе pa=0 позже берёт
            # «exit=entry rp=0» и замазывает реальный исход.
            _s, _ps = f.side.upper(), f.pos_side.upper()
            if not ((_s == "SELL" and _ps == "LONG") or (_s == "BUY" and _ps == "SHORT")):
                return
            # ЧАСТИЧНОЕ закрытие (radar TP1, консилиум 13.07): fill заметно меньше живой
            # позиции → это НЕ exit всей позиции. Не стешим (иначе pa=0 позже возьмёт цену
            # частички); позицию уменьшит штатный ACCOUNT_UPDATE pa>0. Финальный кусок
            # (fill ≈ остатку) стешится ниже; при гонке подстрахует CR-DELTA.
            cur = self._pos.get(key)
            if (cur is not None and f.total_qty and cur.qty
                    and (cur.qty - f.total_qty) > cur.qty * 0.02):
                return
            # закрывающий fill (reduceOnly/STOP/TP/LIQUIDATION) → точный exit (o.ap) + realized (o.rp)
            self._exit[key] = ExitInfo(
                symbol=f.symbol, side=f.pos_side, account=ev.account,
                exit_price=f.avg_price, realized_pnl=f.realized_pnl,
                status=classify_exit(f.order_type, f.realized_pnl),
                order_type=f.order_type, position_id=f.position_id, ts=time.time(),
            )

    def take_exit(self, account: int, symbol: str, side: str) -> Optional[ExitInfo]:
        """Извлечь (и удалить) застешенный exit для пары — для close-классификации Sphere."""
        return self._exit.pop((account, symbol, side), None)

    def take_cr_delta(self, account: int, symbol: str, side: str,
                      cr_final: Optional[float]) -> Optional[float]:
        """Δcr = cr(pa=0) − последний стеш при pa>0 → realized сделки (нетто, с fees).

        Первичный резолв гонки fill↔pa=0: ответ в самом закрывающем событии (13.07,
        валидация: AVAAI Δ=−0.17 RIVER −0.15 UAI −0.18 от gross = комиссии). Стеша нет
        (позиция без промежуточных pa>0 событий) → база 0.0 — cr за цикл и есть realized.
        Стеш чистится всегда (закрытие завершает цикл позиции)."""
        base = self._cr.pop((account, symbol, side), 0.0)
        if cr_final is None:
            return None
        return cr_final - base

    # ── чтение состояния (дашборд/сайзинг — из WS-снимка, НЕ REST polling) ───
    def positions(self, account: Optional[int] = None) -> list[Position]:
        if account is None:
            return list(self._pos.values())
        return [p for (acc, _, _), p in self._pos.items() if acc == account]

    def get(self, account: int, symbol: str, side: str) -> Optional[Position]:
        return self._pos.get((account, symbol, side))

    def set_position_id(self, account: int, symbol: str, side: str, pid) -> bool:
        """Backfill positionId в открытую позицию. WS open-fill И ACCOUNT_UPDATE P[] его НЕ
        несут (проверено 20.06) — только REST-снимок (cold_start/get_positions). Без pid close
        при гонке fill↔pa=0 = «?» → CUTOVER оставил бы строку OPEN. Ставим если ещё не задан."""
        p = self._pos.get((account, symbol, side))
        if p is not None and pid and not p.position_id:
            p.position_id = str(pid)
            return True
        return False

    def set_position_id_match(self, symbol: str, side: str, pid) -> bool:
        """Backfill pid по symbol+side (account из БД неизвестен; sticky = 1 акк/символ)."""
        for (acc, s, sd) in list(self._pos):
            if s == symbol and sd == side:
                return self.set_position_id(acc, symbol, side, pid)
        return False

    def by_position_id(self, position_id: str) -> Optional[Position]:
        for p in self._pos.values():
            if p.position_id and str(p.position_id) == str(position_id):
                return p
        return None

    def is_open(self, account: int, symbol: str, side: str) -> bool:
        return (account, symbol, side) in self._pos

    def drop(self, account: int, symbol: str, side: str) -> Optional[Position]:
        """Снять позицию из состояния (watchdog: биржа-флэт подтверждена N циклов)."""
        return self._pos.pop((account, symbol, side), None)

    # ── staleness watchdog (§6, страховка от потерянного WS-события) ─────────
    def _touch(self, account: int) -> None:
        self._last_ws_ts[account] = time.monotonic()

    def staleness(self, account: int) -> Optional[float]:
        """Сек с последнего WS-события аккаунта. None если ни одного ещё не было."""
        ts = self._last_ws_ts.get(account)
        return None if ts is None else (time.monotonic() - ts)
