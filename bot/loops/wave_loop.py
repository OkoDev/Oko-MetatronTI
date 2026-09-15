# -*- coding: utf-8 -*-
"""
Сфера 20 / WaveService — волновая разметка в шину, SHADOW (ARCH-132, 02.09.2026).

🔴 ПОЧЕМУ ОТДЕЛЬНЫЙ ЛУП, А НЕ ВРЕЗКА В `scan_loop` — по замеру, не по вкусу:
`compute_and_publish` стоит **41.9 мс на пару** (медиана 20 вызовов на живых данных).
На 520 парах это **21.8 секунды каждый скан** — в цикл, который и так узкое место
(BOT-LOOP-OFFLOAD), такое класть нельзя.

Волновая разметка считается по 4h/1h и меняется за ЧАСЫ, а не за минуту. Поэтому
интервал 15 минут: нагрузка падает в 15 раз и уходит в отдельный поток.

🔑 SHADOW: луп только ПУБЛИКУЕТ разметку в шину. Ничего не гейтит, торговое поведение
не меняет. Порядок ввода тот же, что у `phase_sphere` и Сферы 19 — сначала копим
снимки, решение «гейтить ли фазой» принимается отдельно и по данным.

Свечи берутся через `data_collector.get_ohlcv` — там LRU-кэш ApiEngine, и `scan_loop`
эти же пары уже прогрел, поэтому REST в норме не дёргается.

Подключение (`bot/core/bot.py`, рядом с прочими create_task):

    asyncio.create_task(wave_loop(self))
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)

# 15 минут: волна на масштабе 50 живёт часами, чаще незачем.
INTERVAL_SEC = 900
# 🔴 ИСТОРИЯ ЧИСЛА (чтобы не откатили вслепую): 120 → 40 → 20 → снова 120.
# Пока скан грел 1h всего 160 барами, запросы сферы (1h=400) промахивались мимо кэша
# и уходили в РЕАЛЬНЫЙ REST через общий семафор: 40 пар шли 284 с и скан ловил
# HARD timeout. 02.09 глубина кэша скана поднята (1h→400, 4h→180) — запрос стоит
# столько же (замер: 1.00× при 60/150/400), поэтому промахов больше нет.
# 🔑 Если проход снова затянется — сначала смотреть hit по 1h в логе [OHLCV-CACHE],
# а не резать число пар: причина будет в глубине кэша, а не в объёме работы.
MAX_SYMBOLS = 120

# 🔴 ГЛУБИНА ПОДОБРАНА ПОД КЭШ, а не «побольше на всякий случай».
# Ключ LRU в ApiEngine — (symbol, timeframe), но `get` отдаёт запись только если
# её `limit` НЕ МЕНЬШЕ запрошенного. Скан греет 4h с 180, 1h с 60, 15m со 150;
# первая версия просила 300/400/400 и промахивалась мимо кэша — каждый вызов уходил
# в REST, 360 запросов за проход, и разметка не появлялась в логе вовсе.
# Проверено на 6 парах: фаза при 180/60/150 совпала с фазой при 300/400/400 — 6 из 6.
# Причина: счёт волн смотрит на последние свинги (period 5), а не на всю историю.
#
# 🔴 1h берём 400 — на нём считается ДВУХМАСШТАБНАЯ нога (swing_len=50), и ей нужна
# история. Замер 02.09 против эталона в 1000 баров: при 400 совпало 6/6, при 250 —
# 3/6 (в половине случаев ноги нет вовсе). Скан теперь греет 1h ровно на 400 → кэш.
BARS_4H, BARS_1H, BARS_LTF = 180, 400, 150


# ВОЛНОВОЙ КОНТЕКСТ АНАЛИТИКА (15.09). Глубина проверена против замера (4h 1500 бар BingX, 80 монет × 3 момента):
# 4h-пятёрка на 200 барах совпала 240/240 → берём 200 = канон кэша ApiEngine (без REST). Дневная нога на 250 днях 480/480,
# на 200 — 471/480 → 250 дней 1D (один REST на пару раз в 4 часа). 🔴 Первая версия просила 4h 500 — мимо кэша, и
# 59 из 97 пар получали «4h None» (REST под нагрузкой).
CTX_4H_BARS, CTX_1D_BARS = 200, 250


def _dt_closed(df, tf_hours: float):
    """Бот-формат get_ohlcv (RangeIndex + time ms) → DatetimeIndex UTC, только ЗАКРЫТЫЕ бары."""
    import pandas as pd
    d = df.copy()
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True) if "time" in d.columns else pd.to_datetime(d.index, utc=True)
    d = d[d.index + pd.Timedelta(hours=tf_hours) <= pd.Timestamp.utcnow()]
    return d[["open", "high", "low", "close", "volume"]].astype(float)


async def _wave_ctx(bot, sym: str, seen: dict):
    """Поля шины wave_leg_up/dn, wave5_setup — раз на новый закрытый 4h-бар.
    → (поля | None, причина). Причина пропуска идёт в итог прохода: первый прогон 15.09 обновил 6 пар из 79,
    а причина уходила в debug — молчаливый отказ."""
    import pandas as pd
    from core.waves.wave_analyst import wave_bus_context
    dc = bot.data_collector
    d4 = await dc.get_ohlcv(sym, "4h", limit=CTX_4H_BARS)
    if d4 is None:
        return None, "4h None"
    n4 = len(d4); d4 = _dt_closed(d4, 4)
    if len(d4) < 150:
        return None, f"4h<150 (пришло {n4})"
    if seen.get(sym) == d4.index[-1]:
        return None, "тот же 4h-бар"
    dd = await dc.get_ohlcv(sym, "1d", limit=CTX_1D_BARS)
    if dd is None or len(dd) < 60:
        return None, f"1d<60 (пришло {0 if dd is None else len(dd)})"
    res = await asyncio.to_thread(wave_bus_context, d4, _dt_closed(dd, 24), pd.Timestamp.utcnow())
    seen[sym] = d4.index[-1]
    return res, "ok"


async def _load_frames(bot, sym: str):
    """4h / 1h / 15m для одной пары. None, если данных не хватает."""
    dc = bot.data_collector
    d4 = await dc.get_ohlcv(sym, "4h", limit=BARS_4H)
    d1 = await dc.get_ohlcv(sym, "1h", limit=BARS_1H)
    dl = await dc.get_ohlcv(sym, "15m", limit=BARS_LTF)
    for d in (d4, d1, dl):
        if d is None or len(d) < 60:
            return None
    return d4, d1, dl


async def wave_loop(bot) -> None:
    """Раз в INTERVAL_SEC публикует волновую фазу в шину. Ничего не гейтит."""
    from core.intelligence.wave_service import WaveService, current_leg

    bus = getattr(bot, "pair_context", None)
    if bus is None:
        logger.warning("[S20] pair_context отсутствует — луп не стартует")
        return
    svc = WaveService()
    bot.wave_service = svc          # чтобы состояние было доступно другим потребителям
    logger.info("[S20] Wave Service запущена (SHADOW), интервал %dс, до %d пар",
                INTERVAL_SEC, MAX_SYMBOLS)

    await asyncio.sleep(90)          # дать скану прогреть кэш свечей после старта
    ctx_seen: dict = {}              # sym → последний закрытый 4h-бар, на котором посчитан волновой контекст

    while True:
        try:
            # Берём пары, которые скан уже видел — их свечи в LRU-кэше свежие.
            syms = list(bus.all_symbols())[:MAX_SYMBOLS]
            done, phases, recounts, skipped, legs, ctxs = 0, Counter(), 0, 0, 0, 0
            ctx_why: Counter = Counter(); ctx_err = None
            t0 = asyncio.get_event_loop().time()
            logger.info("[S20] проход начат: пар в шине %d, берём %d",
                        len(bus.all_symbols()), len(syms))
            for sym in syms:
                try:
                    frames = await _load_frames(bot, sym)
                    if frames is None:
                        skipped += 1
                        continue
                    d4, d1, dl = frames
                    # расчёт ~42 мс — в поток, чтобы не держать event loop
                    ph = await asyncio.to_thread(
                        svc.compute_and_publish, sym, d4, d1, dl, bus)
                    # ДВУХМАСШТАБНАЯ нога — то, на чём стоит находка ARCH-137.
                    # Счёт волн выше её НЕ покрывает: там один мелкий масштаб.
                    leg = await asyncio.to_thread(current_leg, d1, "1h")
                    if leg:
                        bus.update(sym, leg_updated_at=_now(), **leg)
                        legs += 1
                    # волновой контекст аналитика: дневные ноги + 4h-пятёрка (раз на закрытый 4h-бар)
                    try:
                        ctx, why = await _wave_ctx(bot, sym, ctx_seen)
                        ctx_why[why.split(" (")[0]] += 1
                        if ctx:
                            bus.update(sym, **ctx)
                            ctxs += 1
                        elif why not in ("тот же 4h-бар",) and ctx_err is None:
                            ctx_err = f"{sym}: {why}"
                    except Exception as e:
                        ctx_why["ошибка"] += 1
                        if ctx_err is None:
                            ctx_err = f"{sym}: {type(e).__name__} {e}"
                    done += 1
                    phases[getattr(ph, "phase", None) or "undefined"] += 1
                    # пересчёт разметки — сам по себе сигнал (счёт волн сломался)
                    recounts += svc.recount_count(sym)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug("[S20] %s: %s", sym, e)
            el = asyncio.get_event_loop().time() - t0
            if done:
                top = " · ".join(f"{k} {v}" for k, v in phases.most_common(4))
                logger.info("[S20] разметка по %d парам за %.0fс · %s · ног %d · "
                            "пересчётов %d · волновой контекст обновлён %d (в шине %d)%s", done, el, top, legs, recounts,
                            ctxs, len(ctx_seen), f" · пропущено {skipped}" if skipped else "")
                if ctx_why:
                    logger.info("[S20] волновой контекст: %s%s", dict(ctx_why), f" · пример: {ctx_err}" if ctx_err else "")
            else:
                logger.warning("[S20] НИ ОДНОЙ пары не размечено за %.0fс "
                               "(пропущено %d) — проверьте свечи/лимиты", el, skipped)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[S20] ошибка цикла: %s", e, exc_info=True)
        await asyncio.sleep(INTERVAL_SEC)
