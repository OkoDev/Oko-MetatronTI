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
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


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
# 04.10: пауза между проходами, пока вселенная ещё не обойдена окном ни разу. Не ноль —
# чтобы дать скану и прочим лупам вдохнуть между двумя подряд проходами по 120 пар.
CATCHUP_SLEEP_SEC = 20
# 🔴 05.10 Сколько пар обрабатывается ОДНОВРЕМЕННО. Егор: «нужен параллелизм, но очень
# осторожно!». 98% времени прохода — ожидание общего канала со сканом, поэтому выигрыш есть,
# но и жадность здесь уже стоила нам HARD timeout скана (история MAX_SYMBOLS 120 → 40 → 20 → 120).
# 🔴 НАБЛЮДЕНИЕ 05.10: при PARALLEL=4 темп `HARD timeout при сборе сигналов` за первые 8 минут
# вырос с 0.32 до 0.75 в минуту. Выборка мала и первый проход после рестарта всегда тяжелее
# (ctx_seen пуст → контекст считается для ВСЕХ пар окна), поэтому вина параллелизма НЕ доказана —
# но принцип осторожности важнее возможного выигрыша: снижено до 2 и наблюдаем.
# Поднимать обратно ТОЛЬКО с замером темпа таймаутов до/после на окне от часа.
# PARALLEL = 1 полностью возвращает прежнее последовательное поведение.
PARALLEL = 2

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
# на 200 — 471/480 (98%). 🔴 В бою любой запрос глубже канона кэша (200) идёт в REST, а при открытом предохранителе API
# (≈350 раз в сутки, хроника скана) возвращает пусто: 4h 500 дал 59 «4h None» из 97, 1D 250 — 41 «1d<60» из 83.
# Поэтому обе глубины = канон кэша: покрытие важнее 2% расхождения ноги. Неудачные пары пересчитываются на следующем проходе.
CTX_4H_BARS, CTX_1D_BARS = 200, 200


# 🔴 04.10 ПЕРСИСТ ВОЛНОВОГО КОНТЕКСТА (Егор: «как сократить прогрев?» → «1+2, согласен»).
# Замер 04.10: контекста в шине 0 из 100 пар через 25 мин после рестарта, хотя каузальный
# расчёт сетапы находит; до рестарта было накоплено 497 пар — всё терялось, потому что
# `wave5_setup` жил ТОЛЬКО в памяти процесса. Полный прогрев 569 пар занимает ~75 минут,
# а бот 04.10 перезапускался 11 раз за сутки — значит заметную часть времени потребители
# (`wave_zone_for` → features_json сделок) видели пусто и считали «импульса нет».
# Решение: снимок полей в файл после каждого прохода, восстановление при старте.
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "wave_ctx_state.json"
# Ядро считается на 4h-баре, то есть живёт 4 часа. Старше 12 ч не поднимаем: лучше пусто,
# чем древний контекст, который потребитель примет за свежий.
STATE_MAX_AGE_H = 12.0
# поля, которые дорого считать и которые наполняются медленно (фазу `elliott_*` не сохраняем:
# она пересчитывается на каждом проходе за 31 мс и не зависит от нового 4h-бара)
_PERSIST_FIELDS = ("wave_leg_up", "wave_leg_dn", "wave5_setup", "wave_ctx_updated_at",
                   "leg_dir", "leg_span_bars", "leg_age_origin", "leg_pos", "leg_retr",
                   "leg_minor_breaks", "leg_tf", "leg_updated_at")


def _save_ctx_state(bus) -> int:
    """Снимок волнового контекста всех пар шины в файл. Возвращает число сохранённых пар."""
    out = {}
    for sym in bus.all_symbols():
        st = bus.get(sym)
        upd = getattr(st, "wave_ctx_updated_at", None)
        if upd is None:
            continue
        rec = {}
        for f in _PERSIST_FIELDS:
            v = getattr(st, f, None)
            rec[f] = v.isoformat() if isinstance(v, datetime) else v
        out[sym] = rec
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:                                       # noqa: BLE001
        logger.warning("[S20] снимок контекста не сохранён: %s", e)
        return 0
    return len(out)


def _load_ctx_state(bus) -> tuple[int, int]:
    """Восстановить контекст в шину после рестарта. → (поднято, пропущено по возрасту)."""
    if not STATE_FILE.exists():
        return 0, 0
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:                                       # noqa: BLE001
        logger.warning("[S20] снимок контекста не прочитан: %s", e)
        return 0, 0
    ok = old = 0
    now = _now()
    for sym, rec in data.items():
        upd = rec.get("wave_ctx_updated_at")
        try:
            t = datetime.fromisoformat(str(upd))
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except Exception:                                        # noqa: BLE001
            continue
        if (now - t).total_seconds() / 3600 > STATE_MAX_AGE_H:
            old += 1
            continue
        fields = {k: v for k, v in rec.items() if v is not None}
        for k in ("wave_ctx_updated_at", "leg_updated_at"):
            if fields.get(k):
                try:
                    tt = datetime.fromisoformat(str(fields[k]))
                    fields[k] = tt if tt.tzinfo else tt.replace(tzinfo=timezone.utc)
                except Exception:                                # noqa: BLE001
                    fields.pop(k, None)
        try:
            bus.update(sym, **fields)
            ok += 1
        except Exception:                                        # noqa: BLE001
            continue
    return ok, old


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
    # 04.10: метки для селфтеста Куба. Без них «разметки в шине нет» нельзя отличить
    # от «бот только что перезапущен»: первый проход начинается через 90 с и идёт ~8 мин,
    # поэтому сразу после рестарта сфера выглядела бы мёртвой (ложная тревога каждый раз).
    from datetime import datetime as _dt, timezone as _tz
    bot.wave_started_at = _dt.now(_tz.utc)
    bot.wave_last_pass_at = None
    logger.info("[S20] Wave Service запущена (SHADOW), интервал %dс, окно %d пар за проход, "
                "ротация по кругу (покрытие всей вселенной — за len(шина)/%d проходов)",
                INTERVAL_SEC, MAX_SYMBOLS, MAX_SYMBOLS)

    # 🔑 04.10 ПРОГРЕВ: поднимаем контекст прошлого запуска ДО первой паузы, иначе 75 минут
    # после каждого рестарта потребители видят пусто (замер: 0 из 100 пар через 25 мин).
    _rest, _old = _load_ctx_state(bus)
    if _rest or _old:
        logger.info("[S20] контекст прошлого запуска: поднято %d пар · пропущено по возрасту "
                    "(>%.0f ч) %d · файл %s", _rest, STATE_MAX_AGE_H, _old, STATE_FILE.name)

    await asyncio.sleep(90)          # дать скану прогреть кэш свечей после старта
    ctx_seen: dict = {}              # sym → последний закрытый 4h-бар, на котором посчитан волновой контекст
    touched: set = set()             # пары, которые окно уже проходило (для решения «спать или догонять»)
    offset = 0                       # начало окна ротации (см. ниже)

    while True:
        try:
            # 🔴 02.10: БЫЛО `all_symbols()[:MAX_SYMBOLS]` — срез от НАЧАЛА, а порядок
            # `dict.keys()` стабилен, поэтому разметку получали ВСЕГДА одни и те же 120 пар,
            # а остальные ~464 из 584 — никогда (в логе «в шине 118» не рос между проходами).
            # Теперь окно едет по кругу: вселенная покрывается за ~5 проходов (75 мин), что
            # чаще нового 4h-бара (240 мин), а нагрузка на проход та же.
            # 🔑 Почему не подняли MAX_SYMBOLS: замер 02.10 — расчёт стоит 49 мс/пару
            # (584 пары = 29 с CPU = 3% интервала), но проход идёт 450-490 с на 119 пар,
            # потому что время уходит в получение свечей (5 `get_ohlcv` на пару через
            # HtfStore + 3 `to_thread`), а не в вычисления. На 584 парах проход занял бы
            # ~2250 с против интервала 900 с — луп отставал бы втрое.
            allsym = list(bus.all_symbols())
            n_all = len(allsym)
            if n_all:
                offset %= n_all
                take = min(MAX_SYMBOLS, n_all)
                syms = [allsym[(offset + i) % n_all] for i in range(take)]
                win = f"окно {offset}..{(offset + take - 1) % n_all}"
                offset = (offset + take) % n_all
            else:
                syms, win = [], "окно пусто"
            done, phases, recounts, skipped, legs, ctxs = 0, Counter(), 0, 0, 0, 0
            ctx_why: Counter = Counter(); ctx_err = None
            t0 = asyncio.get_event_loop().time()
            logger.info("[S20] проход начат: пар в шине %d, берём %d (%s)",
                        n_all, len(syms), win)
            # 🔴 05.10 ПАРАЛЛЕЛИЗМ, ОСТОРОЖНО (Егор: «нужен, но очень осторожно!»).
            # Замер 04.10: данные и расчёт стоят 83 мс на пару (чтение баров из хранилища
            # 6-21 мс + расчёт 49 мс), а проход тратит 4.4 с/пару — то есть 98% времени луп
            # ЖДЁТ в очередях (`to_thread` + семафор `get_ohlcv`), а не работает. Поэтому
            # несколько пар одновременно дают почти линейный выигрыш.
            # 🔴 Почему мало и через семафор: канал — общее узкое место со сканом, и история
            # MAX_SYMBOLS (120 → 40 → 20 → 120) ровно про это. Откат к прежнему поведению —
            # PARALLEL = 1, тогда gather вырождается в последовательный обход.
            _sem = asyncio.Semaphore(PARALLEL)

            async def _one(sym: str) -> dict:
                """Обработка одной пары. Возвращает счётчики — агрегируем ПОСЛЕ gather,
                чтобы параллельные задачи не делили изменяемое состояние."""
                r = {"done": 0, "skipped": 0, "legs": 0, "ctxs": 0, "phase": None,
                     "why": None, "err": None, "sym": sym}
                async with _sem:
                    try:
                        frames = await _load_frames(bot, sym)
                        if frames is None:
                            r["skipped"] = 1
                            return r
                        d4, d1, dl = frames
                        # расчёт ~42 мс — в поток, чтобы не держать event loop
                        ph = await asyncio.to_thread(
                            svc.compute_and_publish, sym, d4, d1, dl, bus)
                        # ДВУХМАСШТАБНАЯ нога — то, на чём стоит находка ARCH-137.
                        # Счёт волн выше её НЕ покрывает: там один мелкий масштаб.
                        leg = await asyncio.to_thread(current_leg, d1, "1h")
                        if leg:
                            bus.update(sym, leg_updated_at=_now(), **leg)
                            r["legs"] = 1
                        # волновой контекст аналитика: дневные ноги + 4h-пятёрка (раз на закрытый бар)
                        try:
                            ctx, why = await _wave_ctx(bot, sym, ctx_seen)
                            r["why"] = why.split(" (")[0]
                            if ctx:
                                bus.update(sym, **ctx)
                                r["ctxs"] = 1
                            elif why not in ("тот же 4h-бар",):
                                r["err"] = f"{sym}: {why}"
                        except Exception as e:                   # noqa: BLE001
                            r["why"] = "ошибка"
                            r["err"] = f"{sym}: {type(e).__name__} {e}"
                        r["done"] = 1
                        r["phase"] = getattr(ph, "phase", None) or "undefined"
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:                       # noqa: BLE001
                        logger.debug("[S20] %s: %s", sym, e)
                    finally:
                        # пара пройдена окном — даже если данных не хватило. Иначе «догоняющий»
                        # режим ниже крутился бы вечно из-за пар, у которых контекста не будет
                        # никогда (4h<150, 1d<60 — их в каждом проходе 5-8).
                        touched.add(sym)
                return r

            for _res in await asyncio.gather(*(_one(s) for s in syms), return_exceptions=True):
                if isinstance(_res, BaseException):
                    logger.debug("[S20] задача упала: %s", _res)
                    continue
                done += _res["done"]; skipped += _res["skipped"]
                legs += _res["legs"]; ctxs += _res["ctxs"]
                if _res["phase"]:
                    phases[_res["phase"]] += 1
                if _res["why"]:
                    ctx_why[_res["why"]] += 1
                if _res["err"] and ctx_err is None:
                    ctx_err = _res["err"]
                recounts += svc.recount_count(_res["sym"])
            el = asyncio.get_event_loop().time() - t0
            if done:
                bot.wave_last_pass_at = _dt.now(_tz.utc)   # селфтест: луп не завис
                top = " · ".join(f"{k} {v}" for k, v in phases.most_common(4))
                logger.info("[S20] разметка по %d парам за %.0fс · %s · ног %d · "
                            "пересчётов %d · волновой контекст обновлён %d (в шине %d)%s", done, el, top, legs, recounts,
                            ctxs, len(ctx_seen), f" · пропущено {skipped}" if skipped else "")
                if ctx_why:
                    logger.info("[S20] волновой контекст: %s%s", dict(ctx_why), f" · пример: {ctx_err}" if ctx_err else "")
                # 🔑 04.10 снимок на диск — чтобы следующий старт не ждал 75 минут
                _saved = _save_ctx_state(bus)
                if _saved:
                    logger.debug("[S20] снимок контекста: %d пар → %s", _saved, STATE_FILE.name)
            else:
                logger.warning("[S20] НИ ОДНОЙ пары не размечено за %.0fс "
                               "(пропущено %d) — проверьте свечи/лимиты", el, skipped)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[S20] ошибка цикла: %s", e, exc_info=True)
        # 🔑 04.10 ДОГОНЯЮЩИЙ РЕЖИМ (Егор: «как сократить прогрев?»). Пока окно не обошло
        # вселенную хотя бы раз, спать полный интервал незачем: проход занимает ~9 мин, а
        # интервал 15 — то есть на каждом круге мы ДАРИЛИ 6 минут простоя, и прогрев 569 пар
        # растягивался с 45 до 75 минут. После полного круга возвращаемся к штатному интервалу:
        # разметка меняется на 4h-баре, чаще считать незачем.
        _left = max(0, len(bus.all_symbols()) - len(touched))
        if _left:
            logger.info("[S20] догоняю прогрев: без разметки ещё %d пар → следующий проход сразу", _left)
            await asyncio.sleep(CATCHUP_SLEEP_SEC)
        else:
            await asyncio.sleep(INTERVAL_SEC)
