# -*- coding: utf-8 -*-
"""
Сфера 19 / Market Data — публикация внешних данных в шину (ARCH-129, 01.09.2026).

🔴 ПОЧЕМУ ОТДЕЛЬНЫЙ ЛУП, А НЕ ВРЕЗКА В `scan_loop`:

1. **Частоты не совпадают.** `scan_loop` крутится раз в 60 сек по каждой паре.
   Данные Сферы 19 меняются медленно: OI — раз в 5-15 мин (`radar_state` пишет
   `oi_fast_poller`), фандинг — раз в 4-8 часов. Дёргать их на каждой итерации
   скана — работа впустую.
2. **`scan_loop` уже узкое место.** BOT-LOOP-OFFLOAD (🔴 в TASKS): event loop
   задушен сканом, замер показал 135-байт ответ = 2 сек очереди, `full_stats`
   1.4с SQL → 45с через бота. Добавлять туда синхронный SQLite на каждую пару —
   усугублять доказанную проблему.
3. **Данные уже готовы батчем.** `radar_state` отдаёт ВСЕ 389 символов одним
   SELECT — на весь рынок уходит один запрос, а не 389.
4. **Торговый цикл не трогаем.** Луп только ПУБЛИКУЕТ в шину и ничего не гейтит,
   поэтому его включение не меняет торгового поведения (порядок ввода тот же,
   что у `phase_sphere` и WaveService: сначала SHADOW, гейты — потом и отдельно).

Подключение (одна строка в `bot/core/bot.py`, рядом с прочими `create_task`):

    asyncio.create_task(market_data_loop(self))

Требует рестарта бота и проверки `SelfTest N/N`.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Реальная БД oko_feed. 🔴 В КОРНЕ проекта лежит одноимённая пустышка на 0 байт —
# `sqlite3.connect` на ней молча создаст пустую БД, и луп «успешно» отработает
# ни на чём (класс OPS-ROOT-DBCOPIES). Поэтому путь абсолютный и проверяется.
_FEED_DB = Path(__file__).resolve().parents[2] / "oko_feed" / "external_data.db"

INTERVAL_SEC = 300          # 5 минут: чаще radar_state всё равно не обновляется
STATE_MAX_AGE_SEC = 1800    # снимок старше 30 мин считаем протухшим, не публикуем
MARKET_EVERY_N = 3          # доминацию считаем раз в 3 цикла (15 мин) — см. ниже

_OHLCV_DB = Path(__file__).resolve().parents[2] / "ohlcv_cache.db"


def _usdt_d_history() -> list[tuple[str, float]]:
    """USDT.D по дням из `mcap_meta`. Дёшево: SQLite, 37 строк."""
    if not _OHLCV_DB.exists():
        return []
    con = sqlite3.connect(f"file:{_OHLCV_DB}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute("SELECT date, usdt_mcap, total_snapshot FROM mcap_meta "
                           "WHERE total_snapshot > 0 ORDER BY date").fetchall()
        return [(d, 100.0 * u / t) for d, u, t in rows]
    except sqlite3.Error as e:
        logger.debug("[S19] mcap_meta: %s", e)
        return []
    finally:
        con.close()


def _drift_snapshot() -> dict:
    """
    Дрейф вселенной в шину (ARCH-129.4).

    🔑 Расчёт НЕ дублируем: `core/context/universe_drift.py` уже единственный источник
    с кэшем (замер 01.09 — 2.3 мс). Задача 129.4 писалась как «каждая стратегия считает
    заново», но к 01.09 это уже неверно: дрейф централизован в модуле, магниты читаются
    из шины (ARCH-122). Что оставалось — сделать дрейф видимым ВСЕМ сферам, а не только
    двум лупам impulse_fib, которые его импортируют напрямую.
    """
    out: dict = {}
    try:
        from core.context import universe_drift as ud
        d = ud.get_drift()
        if d:
            out.update(ud_drift30=d.get("drift30"), ud_drift90=d.get("drift90"),
                       ud_drift180=d.get("drift180"), ud_slope180=d.get("slope180"),
                       ud_n_coins=d.get("n_coins"), ud_day=d.get("day"))
        z = ud.in_short_zone()
        if z is not None:
            out["ud_short_zone"] = bool(z)
    except Exception as e:
        logger.debug("[S19] universe_drift: %s", e)

    # Часовой режим радара — ДРУГОЙ дрейф (48 монет), кладётся под своими именами.
    if _FEED_DB.exists() and _FEED_DB.stat().st_size > 0:
        try:
            con = sqlite3.connect(f"file:{_FEED_DB}?mode=ro", uri=True, timeout=5)
            try:
                r = con.execute("SELECT drift, breadth, label FROM regime_state "
                                "ORDER BY ts DESC LIMIT 1").fetchone()
                if r:
                    out.update(regime_drift_1h=r[0], regime_breadth=r[1], regime_label=r[2])
            finally:
                con.close()
        except sqlite3.Error as e:
            logger.debug("[S19] regime_state: %s", e)
    return out


def _market_snapshot() -> dict:
    """
    Снимок рынка. 🔴 БЛОКИРУЮЩАЯ функция: `live_dominance` ходит в сеть (замер 01.09 —
    1.9с, `rotation_now` — 2.7с). Вызывать ТОЛЬКО через `asyncio.to_thread`, иначе
    event loop встанет на ~4.6с (BOT-LOOP-OFFLOAD — доказанная проблема этого бота).
    """
    from core.context.marketcap_engine import live_dominance, rotation_now

    out: dict = {}
    dom = live_dominance()
    if dom:
        out.update(usdt_d=dom.get("usdt_d"), btc_d=dom.get("btc_d"),
                   eth_d=dom.get("eth_d"), alt_d=dom.get("alt_d"),
                   total_mcap=dom.get("total_mcap"), alt_mcap=dom.get("alt_mcap"),
                   n_coins=dom.get("n"), source=dom.get("source", "self_computed"))
    rot = rotation_now()
    if rot:
        out["rotation_verdict"] = rot.get("verdict")

    hist = _usdt_d_history()
    cur = out.get("usdt_d")
    if hist and cur is not None:
        vals = [v for _, v in hist]
        below = sum(1 for v in vals if v < cur)
        out["usdt_d_pctile"] = round(100.0 * below / len(vals), 1)
        # 🔴 глубина публикуется рядом: истории 37 дней, а не 120, как просила спека.
        # Перцентиль «за 120 дней» на 37 днях — это молча врущее число.
        out["usdt_d_hist_days"] = len(vals)
        if len(vals) >= 2:
            out["usdt_d_d1"] = round(cur - vals[-1], 4)
        if len(vals) >= 8:
            out["usdt_d_d7"] = round(cur - vals[-8], 4)
    return out


def _read_radar_state() -> list[tuple]:
    """Батч-чтение OI по всем символам. Один запрос на весь рынок."""
    if not _FEED_DB.exists() or _FEED_DB.stat().st_size == 0:
        logger.warning("[S19] %s пуста или отсутствует — публиковать нечего", _FEED_DB)
        return []
    con = sqlite3.connect(f"file:{_FEED_DB}?mode=ro", uri=True, timeout=5)
    try:
        cutoff = int(time.time()) - STATE_MAX_AGE_SEC
        return con.execute(
            "SELECT symbol, ts, oi_d5, oi_d15, oi_d1d, quadrant, funding "
            "FROM radar_state WHERE ts > ?", (cutoff,)).fetchall()
    except sqlite3.Error as e:
        logger.warning("[S19] чтение radar_state: %s", e)
        return []
    finally:
        con.close()


async def market_data_loop(bot) -> None:
    """Раз в INTERVAL_SEC публикует OI и фандинг в шину. Ничего не гейтит."""
    from core.context.market_data_sphere import MarketDataSphere

    bus = getattr(bot, "pair_context", None)
    if bus is None:
        logger.warning("[S19] pair_context отсутствует — луп не стартует")
        return
    sphere = MarketDataSphere(bus)
    logger.info("[S19] Market Data Sphere запущена, интервал %dс, БД %s",
                INTERVAL_SEC, _FEED_DB.name)

    cycle = 0
    while True:
        try:
            # ── L3 рынок (ARCH-129.6): реже и ОБЯЗАТЕЛЬНО в потоке ──────────
            # Данные глобальные и медленные (доминация меняется за часы), а вызов
            # дорогой и сетевой — поэтому раз в 15 мин и через to_thread.
            if cycle % MARKET_EVERY_N == 0:
                try:
                    snap = await asyncio.to_thread(_market_snapshot)
                    if snap:
                        bus.update_market(**snap)
                        logger.info("[S19] рынок: USDT.D %.3f%% (перц. %s%% на %s дн) · "
                                    "BTC.D %.2f%% · ротация: %s",
                                    snap.get("usdt_d") or 0.0,
                                    snap.get("usdt_d_pctile"), snap.get("usdt_d_hist_days"),
                                    snap.get("btc_d") or 0.0,
                                    (snap.get("rotation_verdict") or "—")[:60])
                except Exception as e:
                    logger.warning("[S19] снимок рынка не получен: %s", e)
            cycle += 1

            # Дрейф — КАЖДЫЙ цикл: он дешёвый (2.3 мс, кэш в модуле) и на нём стоит
            # боевой гейт, поэтому в шине он должен быть свежим, а не раз в 15 мин.
            drift = _drift_snapshot()
            if drift:
                bus.update_market(**drift)

            rows = _read_radar_state()
            n_oi = n_sq = 0
            for sym, _ts, d5, d15, d1d, quadrant, funding in rows:
                pair = f"{sym}/USDT"
                sq = sphere.publish_oi(pair, d5=d5, d15=d15, d1d=d1d, quadrant=quadrant)
                n_oi += 1
                if sq:
                    n_sq += 1
                # radar пишет фандинг той же строкой — источник и интервал у него
                # не указаны, поэтому помечаем честно и интервал не выдумываем.
                if funding is not None:
                    sphere.observe_and_publish(pair, float(funding),
                                               interval_h=None, source="radar")
            if n_oi:
                _m = bus.get_market()
                logger.info("[S19] опубликовано OI по %d парам · сквизов %d · "
                            "дрейф30 %s (зона short: %s) · режим %s",
                            n_oi, n_sq,
                            f"{_m.ud_drift30:.2f}" if _m.ud_drift30 is not None else "—",
                            _m.ud_short_zone, _m.regime_label)
            else:
                logger.debug("[S19] свежих строк radar_state нет")
        except asyncio.CancelledError:
            raise
        except Exception as e:                      # луп данных не должен ронять бота
            logger.error("[S19] ошибка цикла: %s", e, exc_info=True)
        await asyncio.sleep(INTERVAL_SEC)
