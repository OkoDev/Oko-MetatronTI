# -*- coding: utf-8 -*-
"""
limit_lifecycle — ЕДИНОЕ ПРАВИЛО постановки лимитной заявки (DEV-244, 19.10.2026).

Повод. Развилка «после submit лимитного входа» была СКОПИРОВАНА в каждый луп стратегии
(`impulse_fib_runner`, `choch_wavec_loop`, `ote_observer_loop`, `scan_loop`/atr_s2) своей
копией. Копии разъехались: одни при отсутствии биржевого ордера слали заявку в CANCELLED,
другие оставляли её OPEN-тенью. Из-за этого DEV-243: у источника на паузе (`mode: off`)
ордера нет ПО ЗАМЫСЛУ, а копия считала это ошибкой и убивала SIM-заявку до того, как её
рассудит по свече `core.trading.sim_fill.resolve_sim_pending` — `impulse_fib_15m` дал 448
заявок и 0 филлов за октябрь. Правка в одном файле не доезжала до других: это и есть корень.

Единое правило (одно на всех):
    трейда нет (router отбил)         → 'none'  — делать нечего
    биржа ВКЛ, ордера нет (гейт/сбой) → 'cancelled' — ошибка; OPEN-строку подхватил бы TSL
                                        и испортил стоп позиции, которой на бирже нет (ARB #58349)
    биржа ВКЛ, ордер есть             → 'pending'     — ждём биржевой fill
    биржа ВЫКЛ (пауза/тень)           → 'pending_sim' — ордера нет ПО ЗАМЫСЛУ; заявку судит
                                        свеча (resolve_sim_pending), это честный SIM-форвард

🜂 СФЕРА. Жизненный цикл заявки принадлежит Сфере Исполнения (`core/execution`). Здесь он
собран как доменный модуль; ПОЛНОЕ вливание в `ExecutionSphere` (лупы зовут Sphere.open(),
а не пишут в `simulated_trades` напрямую) — это cutover ARCH-128, на который стратегии ещё
НЕ переключены. До него этот модуль — единая точка правды для старого пути.

🔴 НЕ покрывает `radar` (live) из `radar_armed_loop:1180`: у него намеренно НЕТ ветки
CANCELLED (при неушедшем ордере строка остаётся OPEN SIM-тенью). Перевод radar на это
правило МЕНЯЕТ его поведение на живых деньгах → отдельный шаг с замером baseline.
"""
from __future__ import annotations

import logging
import sqlite3

from core.trading.source_registry import trades_on_exchange

logger = logging.getLogger(__name__)


def mark_pending(db_path, trade_id: int) -> bool:
    """OPEN → PENDING_ENTRY: LIMIT поставлен НА БИРЖУ, fill не подтверждён (actual_entry пуст).

    Требует `exchange_order_id`: для ЖИВОГО источника пустой oid означает «ордер не ушёл»,
    и такую строку держать в PENDING нельзя — её снимает ветка CANCELLED в `finalize_limit_entry`.
    PENDING-строка невидима для get_open_trades → TSL/BE/close-by-price/live-guard её не трогают;
    орфан-детект видит её отдельной выборкой (position_sync._detect_orphans).
    """
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            cur = c.execute(
                "UPDATE simulated_trades SET status='PENDING_ENTRY' WHERE id=? AND status='OPEN' "
                "AND (actual_entry_price IS NULL OR actual_entry_price <= 0) "
                "AND exchange_order_id IS NOT NULL AND exchange_order_id != ''",
                (trade_id,))
            c.commit()
            return cur.rowcount > 0
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[limit_lifecycle] mark_pending #%s: %s", trade_id, e)
        return False


def mark_pending_sim(db_path, trade_id: int) -> bool:
    """OPEN → PENDING_ENTRY для SIM-источника БЕЗ биржевого ордера (пауза/тень).

    13.10 DEV-243: у источника с выключенной биржей (`mode: off` / `exchange_enabled: false`)
    биржевого ордера нет ПО ЗАМЫСЛУ. `mark_pending` такую строку не переводит (требует oid).
    Для SIM-источника пустой oid — норма, и прежде её убивала ветка «нет oid → CANCELLED»,
    не доводя заявку до `sim_fill.resolve_sim_pending` (который судит SIM-лимитку по свече):
    `impulse_fib_15m` за октябрь дал 448 заявок и 0 филлов. Перевод разрешён ИМЕННО при
    пустом/`SIM` oid — защита живого пути («нет ордера → CANCELLED») не ослабляется.
    PENDING невидим для TSL/BE/close-by-price, как и у обычной лимитки.
    """
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            cur = c.execute(
                "UPDATE simulated_trades SET status='PENDING_ENTRY' WHERE id=? AND status='OPEN' "
                "AND (actual_entry_price IS NULL OR actual_entry_price <= 0) "
                "AND (exchange_order_id IS NULL OR exchange_order_id IN ('', 'SIM'))",
                (trade_id,))
            c.commit()
            return cur.rowcount > 0
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[limit_lifecycle] mark_pending_sim #%s: %s", trade_id, e)
        return False


def finalize_limit_entry(db_path, res, source: str, *, tag: str, log=None) -> str:
    """Единое правило исхода лимитной заявки после `trade_router.submit`.

    Параметры
      res    — SubmitResult (нужны `trade_id`, `exchange_order_id`)
      source — имя источника (ключ политики): решает, биржевой он или SIM
      tag    — префикс лога источника (`IMPULSE`, `CHOCH-C`, `OTE VST`…)

    Возвращает исход: 'none' | 'cancelled' | 'pending' | 'pending_sim'.
    Зовущий сам решает, что делать с исходом (ote, например, при 'cancelled' делает return,
    чтобы не слать уведомление о несуществующей сделке).
    """
    log = log or logger
    tid = getattr(res, "trade_id", None)
    if not tid:
        return "none"
    oid = getattr(res, "exchange_order_id", None)
    exch_on = trades_on_exchange(source)

    if not oid and exch_on:
        # 🔴 Биржа ВКЛ, а ордер не ушёл (гейт/ошибка) — позиции нет, записи быть не должно.
        # OPEN-строку без ордера подхватывает TSL и тащит стоп за несуществующей позицией
        # (ARB #58349: стоп ушёл выше входа). Снимаем.
        try:
            with sqlite3.connect(db_path, timeout=10) as c:
                c.execute("UPDATE simulated_trades SET status='CANCELLED' "
                          "WHERE id=? AND status='OPEN' AND (exchange_order_id "
                          "IS NULL OR exchange_order_id='') AND "
                          "(actual_entry_price IS NULL OR actual_entry_price<=0)",
                          (int(tid),))
                c.commit()
            log.warning("[%s] #%s ордер на биржу не ушёл → CANCELLED", tag, tid)
        except Exception as e:                               # noqa: BLE001
            log.warning("[%s] #%s finalize CANCELLED: %s", tag, tid, e)
        return "cancelled"

    # Биржа ВКЛ и ордер есть → ждём биржевой fill. Биржа ВЫКЛ → oid нет ПО ЗАМЫСЛУ, судит свеча.
    outcome = "pending" if exch_on else "pending_sim"
    try:
        ok = (mark_pending if exch_on else mark_pending_sim)(db_path, int(tid))
        if ok:
            log.info("[%s] #%s → PENDING_ENTRY (%s)", tag, tid,
                     "лимитка ждёт фила" if exch_on else "SIM, судит свеча")
        # 🔴 ОКНО ГОНКИ: между INSERT (OPEN) и переводом в PENDING проходит 10-20 с, и TSL-цикл
        # успевает зацепить строку (XRP #58346: стоп 1.0723 → 1.1541, ВЫШЕ входа). Пока фила
        # нет, стоп обязан быть исходным — восстанавливаем из original_sl. Условие actual_entry
        # гарантирует, что реальную позицию (где трейлинг законен) мы не трогаем.
        with sqlite3.connect(db_path, timeout=10) as c:
            r = c.execute(
                "UPDATE simulated_trades SET stop_loss=original_sl, tsl_activated=0 "
                "WHERE id=? AND original_sl IS NOT NULL AND original_sl>0 "
                "AND stop_loss<>original_sl "
                "AND (actual_entry_price IS NULL OR actual_entry_price<=0)",
                (int(tid),))
            c.commit()
            if r.rowcount:
                log.warning("[%s] #%s стоп восстановлен из original_sl "
                            "(TSL зацепил строку до PENDING)", tag, tid)
    except Exception as e:                                   # noqa: BLE001
        log.warning("[%s] #%s finalize pending: %s", tag, tid, e)
    return outcome
