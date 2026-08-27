# -*- coding: utf-8 -*-
"""CHoCH → ОТКАТ 0.236 → ВОЛНА C — единственный калькулятор механики (18.08.2026).

Механика прошла OOS ([[choch_pullback_waveC_oos_passed]]): OOS-монеты × OOS-время
n=1150, WR 53.1%, PF 1.17; 5 соседних настроек дают PF 1.13–1.19 (плато, не пик).

    1. структура OKO-SM (swing_len=50) → последний swing-CHoCH ВНИЗ;
    2. нога импульса из leg_history[i] (origin/extreme) — каузально, по бару слома;
    3. лимит на продажу = extreme + 0.236 × длина ноги;
    4. стоп = origin × 1.001 (инвалидация ноги), цель = вход − длина ноги × 1.0.

🔑 ПОЧЕМУ НОГА ИЗ leg_history, А НЕ «от свинга до свинга»: замер 18.08 показал, что
грубая нога расходится со структурной в 4.06× по длине и в 44% по НАПРАВЛЕНИЮ.
Зона входа считается от ноги → неверная нога = неверная зона. См. [[oko_sm_engine_ported]].

🔴 ТОЛЬКО SHORT. LONG-зеркало измерено и НЕ прошло: база PF 0.76, все схемы выхода
в минусе (живо лишь `pivot_above_R1_1W` PF 1.18, n=199) — [[choch_boosters_exits_oos]].

Один калькулятор на скрипт и на луп ([[principle_reuse_not_duplication]]):
различия задаются параметрами, формулы не дублируются.
"""
from __future__ import annotations

import re

import pandas as pd

from core.smc.oko_sm_engine import run_structure
from core.smc.smc_engine import _swings_luxalgo

# Параметры механики. Значения — центр плато устойчивости, не подогнанный пик.
PULLBACK = 0.236       # глубина отката для лимита
TARGET_K = 1.0         # цель = длина ноги A (волна C)
WAIT_BARS = 12         # столько баров лимит остаётся актуальным
SWING_LEN = 50         # ТОЛЬКО swing-масштаб: internal (len5) даёт PF 0.59 при частоте ×5.5
MIN_BARS = 300         # структуре нужна история; ниже — leg_history недостоверен

# Веса источников магнитов (кластеризация уровней вокруг пути цены).
_W = {"fvg": 3.0, "swing": 2.5, "pivot_1D": 2.0, "pivot_1W": 3.0, "struct": 2.0}

# Пороги усилителей — OOS-числа из [[choch_boosters_exits_oos]].
BLOCK_CLEAN = 34.0     # помеха на пути ≤34 → PF 1.50 (вес кластера ОБРАТНЫЙ: чисто = лучше)
SHIELD_LIGHT = 96.0    # уровней у стопа мало → PF 1.32
ATR_HIGH = 1.59        # высокая волатильность → PF 1.29 (+трейлинг: PF 1.33, WR 61.5%)
GOOD_HOUR_MAX = 7      # час входа ≤7 UTC → PF 1.39

# 🔴 ФИЛЬТР СИНТЕТИКИ: BingX торгует не только крипту — под теми же тикерами идут акции,
# индексы и сырьё (NCSKMU=Micron, NCSISP500=S&P, NCCOPALLADIUM). В скане 120 пар ПЯТЬ из
# семи сетапов оказались такими. Вся статистика механики считана на крипто-фьючерсах.
# Аудит 18.08 на живой вселенной: 848 пар → 532 крипто, 316 отсеяно, почти все по `^NC`.
# 🔑 `SPX` из списка УБРАН: на BingX это SPX6900 (мем-коин, $0.32), а не индекс S&P —
# индексная версия идёт как NCSISP5002USD и ловится по `^NC`. Было ложное срабатывание.
# XAUT (Tether Gold, $4327) отсекается намеренно: токен, но ходит как золото.
JUNK = re.compile(r"^(NC|FX|IDX)|EUR|GBP|JPY|XAU|XAG|OIL|NDX|SP500|META2|USD1"
                  r"|GOLD|SILVER|PALLADIUM|PLATINUM", re.I)


def is_junk(symbol: str) -> bool:
    """True для не-крипто инструмента (акция/индекс/сырьё под видом свопа)."""
    return bool(JUNK.search(symbol.split("/")[0]))


def _fvg_mids(df: pd.DataFrame, upto: int) -> list[float]:
    """Середины FVG на окне [upto-300, upto]. Порог — 2× средний гэп окна."""
    high, low, close = df.high.values, df.low.values, df.close.values
    out, lo = [], max(2, upto - 300)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(lo, upto + 1)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(lo, upto + 1):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                out.append((high[i - 2] + low[i]) / 2)
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                out.append((high[i] + low[i - 2]) / 2)
    return out


def _pivots(df_dt: pd.DataFrame, rule: str) -> dict:
    """Классические пивоты по ПРЕДЫДУЩЕМУ периоду (iloc[-2]) — незакрытый не берём."""
    g = df_dt.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(g) < 2:
        return {}
    h, l, c = float(g.high.iloc[-2]), float(g.low.iloc[-2]), float(g.close.iloc[-2])
    pp = (h + l + c) / 3
    return {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h, "R2": pp + (h - l),
            "S2": pp - (h - l), "R3": h + 2 * (pp - l), "S3": l - 2 * (h - pp)}


def _weight_between(levels: list, lo: float, hi: float) -> float:
    return sum(w for p, w in levels if lo <= p <= hi)


def find_setup(df: pd.DataFrame, *, symbol: str = "", pullback: float = PULLBACK,
               target_k: float = TARGET_K, wait_bars: int = WAIT_BARS,
               swing_len: int = SWING_LEN, drop_last: bool = True) -> dict | None:
    """Ищет живой SHORT-сетап на 1h. Возвращает dict или None (нет сетапа).

    df: OHLCV с DatetimeIndex (UTC). drop_last=True отбрасывает незакрытый бар —
    без этого вход считается по цене, которой ещё нет ([[oko_suite_trend_wt_validated]],
    класс-1 look-ahead).

    Ключ `reason` в ответе присутствует ТОЛЬКО когда сетапа нет, и объясняет почему.
    """
    if df is None or len(df) < MIN_BARS:
        return {"symbol": symbol, "reason": "мало данных"}
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if drop_last:
        d = d.iloc[:-1]
    dd = d.reset_index(drop=True)
    try:
        st = run_structure(dd, swing_len=swing_len, internal_len=5, record_legs=True)
        sw_big = _swings_luxalgo(dd, swing_len)
        sw_int = _swings_luxalgo(dd, 5)
    except Exception as e:                                    # noqa: BLE001
        return {"symbol": symbol, "reason": f"структура: {str(e)[:50]}"}

    legs = st.leg_history
    if not legs or len(legs) != len(dd):
        return {"symbol": symbol, "reason": "нет leg_history"}

    downs = [e for e in st.events if e.kind == "CHoCH" and not e.internal and not e.bull]
    if not downs:
        return {"symbol": symbol, "reason": "swing-CHoCH вниз не найден"}

    ev = downs[-1]
    i, n = int(ev.i), len(dd)
    age = n - 1 - i
    leg = legs[i]
    # Нога обязана совпасть с направлением слома — иначе зона входа строится не от того
    # движения. Замер 18.08: несогласованные масштабы дали PF 0.55 при совпадении 44%.
    if not leg or leg.get("trend") == "long":
        return {"symbol": symbol, "reason": "нога не совпала со сломом"}

    origin, extreme = float(leg["origin"]), float(leg["extreme"])
    leg_len = abs(extreme - origin)
    if leg_len <= 0:
        return {"symbol": symbol, "reason": "нулевая нога"}

    entry = extreme + leg_len * pullback
    sl = origin * 1.001
    tp = entry - leg_len * target_k
    if sl <= entry:
        return {"symbol": symbol, "reason": "стоп ниже входа"}

    price = float(dd.close.iloc[-1])
    stop_pct = (sl - entry) / entry * 100
    # Лимит уже отрабатывался / стоп уже пробит на прошедших барах → сетап не наш.
    filled = bool((dd.high.values[i + 1:] >= entry).any())
    invalid = bool((dd.high.values[i + 1:] >= sl).any())

    lv = [(p, _W["fvg"]) for p in _fvg_mids(dd, n - 1)]
    lv += [(float(x[1]), _W["swing"]) for x in sw_big if x[0] <= n - 1][-12:]
    lv += [(float(x[1]), _W["struct"]) for x in sw_int if x[0] <= n - 1][-20:]
    p1d, p1w = _pivots(d, "1D"), _pivots(d, "1W")
    lv += [(v, _W["pivot_1D"]) for v in p1d.values()]
    lv += [(v, _W["pivot_1W"]) for v in p1w.values()]
    # 🔑 Вес кластера ОБРАТНЫЙ: лёгкий PF 1.46 / тяжёлый 0.93. Магниты — сопротивление
    # движению, а не цель. Это противоположно логике core/smc/tp_selector.py.
    block = _weight_between(lv, tp, entry)        # помеха на пути вход→цель
    shield = _weight_between(lv, entry, sl)       # уровни в зоне вход→стоп

    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                    (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = float((tr.ewm(alpha=1 / 43, adjust=False).mean() / d.close * 100).median())

    return {
        "symbol": symbol, "price": price, "i": i, "age": age,
        "origin": origin, "extreme": extreme, "leg_len": leg_len,
        "entry": entry, "sl": sl, "tp": tp, "stop_pct": stop_pct,
        "filled": filled, "invalid": invalid,
        "block": block, "shield": shield, "atr_pct": atr_pct,
        "under_s1w": bool(p1w and price < p1w.get("S1", 1e18)),
        "choch_ts": str(d.index[i])[:16],
        "live": bool(not invalid and not filled and age <= wait_bars),
    }


def boosters(s: dict, hour_utc: int | None = None) -> dict:
    """Усилители, пережившие OOS. Возвращает флаги + счётчик сработавших.

    Каждый по отдельности режет частоту в 5–10 раз; ПАРЫ дают PF 2.0–2.31 при
    ПОЛОЖИТЕЛЬНОМ безтоп10% — первый случай, когда плюс держится не на верхних 10%.
    """
    f = {
        "clean_path": s["block"] <= BLOCK_CLEAN,      # PF 1.50
        "light_shield": s["shield"] <= SHIELD_LIGHT,  # PF 1.32
        "high_atr": s["atr_pct"] > ATR_HIGH,          # PF 1.29 (+трейлинг → 1.33)
        "under_s1w": bool(s["under_s1w"]),            # PF 1.84 — сильнейший одиночный
    }
    if hour_utc is not None:
        f["good_hour"] = hour_utc <= GOOD_HOUR_MAX    # PF 1.39
    f["count"] = sum(1 for k, v in f.items() if k != "count" and v)
    return f
