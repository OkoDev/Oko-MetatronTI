# -*- coding: utf-8 -*-
"""ТЕСТ ВИДИМОСТИ УРОВНЕЙ В ОБЕ СТОРОНЫ (шаг 1 сборки, 20.08.2026).

🔴 Зачем в обе стороны. Мы уже теряли месяц на FVG-overlap: проверка ловила
ЗАПАЗДЫВАНИЕ (виден ли уровень на своём баре), но не ВЫЖИВАНИЕ (не отбираем ли мы
только те уровни, что дожили до конца истории). Оба класса дают «эдж» в бэктесте.

Проверяем каждый источник уровней, который пойдёт в общую сетку:
  A. ЗАПАЗДЫВАНИЕ — уровень, видимый на срезе df[:k], обязан быть виден и в полном df
     с тем же индексом. Иначе разметка прошлого зависит от будущего.
  B. ВЫЖИВАНИЕ — доля уровней, которые в полном прогоне помечены иначе (например
     «не собран» против «собран»), чем на момент среза. Если фильтровать по итоговой
     метке — берём только выжившие, а это survivorship.
  C. ЛАГ — на сколько баров позже своего экстремума уровень становится известен.

Запуск: python scripts/verify_levels_visibility.py [N_SYM]
"""
import json
import sqlite3
import sys
import urllib.request

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from core.smc.impulse_fib import is_junk
from core.smc.swing_points import detect_swing_points
from core.smc.liquidity import detect_liquidity, detect_equal_highs_lows
from core.smc.fvg import detect_fvg
from core.smc.dc_legs import find_legs, enforce_alternation

N_SYM = int(sys.argv[1]) if len(sys.argv) > 1 else 5
CUTS = (400, 500, 600)


def klines(sym: str, limit: int = 800):
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
           f"&interval=1h&limit={limit}")
    arr = json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "oko"}), timeout=20))
    d = pd.DataFrame(arr, columns=["t", "open", "high", "low", "close", "volume",
                                   "ct", "qv", "n", "tb", "tq", "ig"])
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = d[c].astype(float)
    return d[["open", "high", "low", "close", "volume"]]


def swings_set(df, limit=None):
    sa = detect_swing_points(df, period=5)
    out = set()
    for s in list(sa.highs) + list(sa.lows):
        i = int(s.index)
        if limit is None or i < limit:
            out.add((i, round(float(s.value), 8)))
    return out


def fvg_set(df, limit=None):
    fa = detect_fvg(df, min_size_pct=0.05, max_zones=999)
    out = set()
    for f in getattr(fa, "all_fvgs", []) or []:
        i = int(getattr(f, "index", -1))
        if i < 0 or (limit is not None and i >= limit):
            continue
        out.add((i, round(float(getattr(f, "midpoint", 0)), 8)))
    return out


def liq_set(df, limit=None):
    sa = detect_swing_points(df, period=5)
    la = detect_liquidity(df, sa, cluster_tolerance_pct=0.3, track_sweeps=True)
    out = set()
    for z in (la.buy_side or []) + (la.sell_side or []):
        out.add((round(float(z.level), 8), z.side))
    return out


def liq_swept(df):
    """Метки swept — для проверки ВЫЖИВАНИЯ."""
    sa = detect_swing_points(df, period=5)
    la = detect_liquidity(df, sa, cluster_tolerance_pct=0.3, track_sweeps=True)
    return {round(float(z.level), 8): bool(z.swept)
            for z in (la.buy_side or []) + (la.sell_side or [])}


def legs_set(df, limit=None):
    legs = enforce_alternation(find_legs(df, atr_mult=2.0))
    return {(l.ext_i, round(float(l.ext_price), 8)) for l in legs
            if limit is None or l.conf_i < limit}


c = sqlite3.connect("file:ohlcv_cache.db?mode=ro", uri=True)
rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
                 "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()
c.close()
syms = [s.split("/")[0] for s, _ in rows if not is_junk(s)][:N_SYM]

SRC = (("свинги (period=5)", swings_set),
       ("FVG", fvg_set),
       ("ноги DC (2.0*ATR)", legs_set),
       ("зоны ликвидности", liq_set))

print("=" * 112)
print(f"ТЕСТ ВИДИМОСТИ УРОВНЕЙ · {len(syms)} монет · срезы {CUTS}")
print("=" * 112)

agg = {name: [0, 0] for name, _ in SRC}       # [всего, расхождений]
surv = [0, 0]                                  # [всего зон, сменивших метку swept]
for sym in syms:
    df = klines(sym)
    if df is None or len(df) < max(CUTS) + 50:
        continue
    for cut in CUTS:
        part = df.iloc[:cut].copy()
        for name, fn in SRC:
            try:
                a = fn(df, cut)
                b = fn(part, cut) if name != "зоны ликвидности" else fn(part)
            except Exception as e:                             # noqa: BLE001
                print(f"  {sym} {name}: ошибка {str(e)[:50]}")
                continue
            if name == "зоны ликвидности":
                a = fn(df)                     # уровни считаются от всей истории
            agg[name][0] += len(a | b)
            agg[name][1] += len(a ^ b)
        # ── ВЫЖИВАНИЕ: менялась ли метка swept ──
        try:
            sw_full, sw_part = liq_swept(df), liq_swept(part)
            common = set(sw_full) & set(sw_part)
            surv[0] += len(common)
            surv[1] += sum(1 for k in common if sw_full[k] != sw_part[k])
        except Exception:
            pass

print(f"\n{'источник':<24}{'всего':>10}{'расхождений':>14}{'доля':>9}   вердикт")
for name, _ in SRC:
    tot, mis = agg[name]
    if tot == 0:
        print(f"{name:<24}{'—':>10}")
        continue
    pct = mis / tot * 100
    verdict = "✅ чисто" if pct < 1 else ("⚠️ лаг подтверждения" if pct < 12 else "🔴 ПЕРЕСМАТРИВАЕТ")
    print(f"{name:<24}{tot:>10}{mis:>14}{pct:>8.1f}%   {verdict}")

if surv[0]:
    pct = surv[1] / surv[0] * 100
    print(f"\nВЫЖИВАНИЕ (метка swept): зон {surv[0]} · сменили метку {surv[1]} ({pct:.1f}%)")
    print("  🔑 Это НЕ баг детектора: зону действительно могут собрать позже. Баг возникает,")
    print("     если фильтровать по ИТОГОВОЙ метке — тогда в выборку попадут только те,")
    print("     что дожили. В замерах брать метку НА МОМЕНТ СИГНАЛА, а не финальную.")
