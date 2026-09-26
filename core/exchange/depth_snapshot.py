# -*- coding: utf-8 -*-
"""СНИМОК СТАКАНА В МОМЕНТ СДЕЛКИ (ЭПИК A, 04.09.2026).

Егор: «стакан ради исполнения». Не постоянный поллер по всей вселенной (он бил бы
в тот же домашний канал, который уже узкое место скана — см. [[scan_bottleneck_is_the_channel]]),
а ОДИН снимок глубины в момент регистрации сделки.

🔴 ЗАЧЕМ ИМЕННО ТАК. Стакана в проекте нет ни за один день, и накопить историю для
исследовательских срезов (сторона × год × режим) невозможно — год мы не покроем
никогда. Зато для ИСПОЛНЕНИЯ снимок полезен с первой же сделки:

  · достижимость лимитки — сколько денег стоит между ценой и нашим лимитом;
  · adverse selection — сейчас он у радара НЕ вычтен, и это блокирует гипотезу
    «лимит на откате» из аудита 04.09 (у impulse_fib он измерен: идеальный фил
    PF 1.90 против пробитых насквозь 1.03 — вычитать нечем, кроме стакана);
  · реальная ликвидность против прокси по обороту — ось ликвидности в проекте
    НЕ СВЕДЕНА: пять замеров дают взаимоисключающие выводы, потому что каждый
    мерил свой прокси (амплитуда импульса / оборот в долларах / спред).

Ключевая метрика — `cost_to_move_*`: сколько долларов надо съесть, чтобы сдвинуть
цену на 0.1% / 0.3%. Это прямой ответ «пройдёт ли наш размер», в отличие от
суточного оборота, который ничего не говорит о моменте входа.

Запись — в отдельную таблицу, привязка по trade_id. Ошибки НЕ должны ронять
регистрацию сделки: снимок опционален по определению.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEPTH_LIMIT = 50            # уровней с каждой стороны — хватает для 0.3% на ликвидных
_MIN_INTERVAL_SEC = 20.0    # не чаще раза в 20 с на символ (канал уже узкое место)
_last_call: Dict[str, float] = {}


def _ddl(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS depth_snapshots (
        trade_id      INTEGER,
        symbol        TEXT NOT NULL,
        ts            INTEGER NOT NULL,
        mid           REAL,
        spread_pct    REAL,
        bid_usd_10bp  REAL,   -- $ на бидах в пределах 0.1% от mid
        ask_usd_10bp  REAL,
        bid_usd_30bp  REAL,
        ask_usd_30bp  REAL,
        imbalance     REAL,   -- bid/(bid+ask) в пределах 0.3%: >0.5 = перевес покупателей
        cost_move_dn  REAL,   -- $, чтобы продавить цену на 0.1% ВНИЗ (съесть биды)
        cost_move_up  REAL,   -- $, чтобы поднять на 0.1% ВВЕРХ (съесть аски)
        levels        INTEGER,
        PRIMARY KEY (symbol, ts))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_depth_trade ON depth_snapshots(trade_id)")


def analyze_book(book: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Сырой стакан ccxt → метрики исполнения. None, если стакан пустой/битый."""
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    try:
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return None
    mid = (best_bid + best_ask) / 2.0

    def _side_usd(levels, lo: float, hi: float) -> float:
        """Сумма в долларах на уровнях, попавших в ценовой коридор [lo, hi]."""
        s = 0.0
        for lv in levels:
            try:
                px, qty = float(lv[0]), float(lv[1])
            except (TypeError, ValueError, IndexError):
                continue
            if lo <= px <= hi:
                s += px * qty
        return s

    b10 = _side_usd(bids, mid * 0.999, mid)
    a10 = _side_usd(asks, mid, mid * 1.001)
    b30 = _side_usd(bids, mid * 0.997, mid)
    a30 = _side_usd(asks, mid, mid * 1.003)
    tot30 = b30 + a30
    return {
        "mid": mid,
        "spread_pct": (best_ask - best_bid) / mid * 100.0,
        "bid_usd_10bp": b10, "ask_usd_10bp": a10,
        "bid_usd_30bp": b30, "ask_usd_30bp": a30,
        # >0.5 — в стакане больше денег на покупку в пределах 0.3%
        "imbalance": (b30 / tot30) if tot30 > 0 else 0.5,
        # сдвинуть цену на 0.1% = съесть всё, что стоит в этом коридоре
        "cost_move_dn": b10,
        "cost_move_up": a10,
        "levels": float(min(len(bids), len(asks))),
    }


async def capture(exchange, symbol: str, db_path: str,
                  trade_id: Optional[int] = None) -> Optional[Dict[str, float]]:
    """Снять стакан и записать. Никогда не бросает — снимок опционален.

    `exchange` — уже инициализированный ccxt-клиент (переиспользуем боевой,
    свой не создаём: ключ один на аккаунт, и лишний клиент = лишний вес на канал).
    """
    now = time.time()
    prev = _last_call.get(symbol, 0.0)
    if now - prev < _MIN_INTERVAL_SEC:
        return None
    _last_call[symbol] = now
    try:
        book = await exchange.fetch_order_book(symbol, limit=DEPTH_LIMIT)
    except Exception as e:  # noqa: BLE001
        logger.debug("[DEPTH] %s fetch error: %s: %s", symbol, type(e).__name__, str(e)[:80])
        return None
    m = analyze_book(book)
    if not m:
        return None
    try:
        # 🔴 Снимок ОПЦИОНАЛЕН — он не имеет права конкурировать за БД с регистрацией
        # сделки. В логе уже есть «database is locked» от `trade_simulator`, поэтому
        # ждём коротко (3 с) и отступаем: потерять снимок безопасно, задержать
        # регистрацию — нет. WAL позволяет читателям не блокировать писателя.
        c = sqlite3.connect(db_path, timeout=3)
        try:
            c.execute("PRAGMA busy_timeout=3000")
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except Exception:      # noqa: BLE001
                pass
            _ddl(c)
            c.execute(
                "INSERT OR IGNORE INTO depth_snapshots "
                "(trade_id,symbol,ts,mid,spread_pct,bid_usd_10bp,ask_usd_10bp,"
                " bid_usd_30bp,ask_usd_30bp,imbalance,cost_move_dn,cost_move_up,levels) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (trade_id, symbol, int(now), m["mid"], m["spread_pct"],
                 m["bid_usd_10bp"], m["ask_usd_10bp"], m["bid_usd_30bp"], m["ask_usd_30bp"],
                 m["imbalance"], m["cost_move_dn"], m["cost_move_up"], int(m["levels"])),
            )
            c.commit()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("[DEPTH] %s write error: %s", symbol, str(e)[:80])
    return m
