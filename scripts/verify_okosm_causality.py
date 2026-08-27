# -*- coding: utf-8 -*-
"""ШАГ 0: ПРОВЕРКА ДЕТЕКТОРА OKO-SM ПЕРЕД СБОРКОЙ (запрос Егора 20.08.2026).

Егор: «инструмент возможно проверен на неверной детекции, нужна перепроверка».
Прежняя верификация была ВИЗУАЛЬНОЙ (метки графика BTC 15/15, SOL 93%). Здесь —
машинные проверки, которые визуально не видны и ловят другой класс ошибок:

  A. ПРИЧИННОСТЬ — разметка на df[:k] совпадает с разметкой на полном df для баров < k.
     Если движок переписывает прошлое, любая механика поверх него будет ложной,
     а в бэктесте это выглядит как «эдж» ([[flags_realtime_lag_audit]]).
  B. ЛАГ СОБЫТИЙ — на сколько баров позже реального экстремума появляется CHoCH/BOS.
     Событие обязано быть видно на СВОЁМ баре, иначе вход опаздывает.
  C. СТАБИЛЬНОСТЬ НОГИ — как часто origin/extreme текущей ноги переписывается назад.
  D. ГЕОМЕТРИЯ — сколько ног, их длины: даёт ли движок структуру или «одну палку».

Запуск: python scripts/verify_okosm_causality.py [N_SYM] [TF]
"""
import json
import sqlite3
import sys
import urllib.request

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_fib import is_junk

N_SYM = int(sys.argv[1]) if len(sys.argv) > 1 else 6
TF = sys.argv[2] if len(sys.argv) > 2 else "1h"
BARS = 900


def klines(sym: str, tf: str = "1h", limit: int = BARS):
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
           f"&interval={tf}&limit={limit}")
    try:
        arr = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "oko"}), timeout=20))
    except Exception as e:                                     # noqa: BLE001
        return None
    d = pd.DataFrame(arr, columns=["t", "open", "high", "low", "close", "volume",
                                   "ct", "qv", "n", "tb", "tq", "ig"])
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = d[c].astype(float)
    d.index = pd.to_datetime(d.t, unit="ms", utc=True)
    return d[["open", "high", "low", "close", "volume"]]


c = sqlite3.connect("file:ohlcv_cache.db?mode=ro", uri=True)
rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
                 "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()
c.close()
syms = [s.split("/")[0] for s, _ in rows if not is_junk(s)][:N_SYM]

print("=" * 108)
print(f"ПРОВЕРКА OKO-SM · {TF} · {len(syms)} монет · окно {BARS} баров")
print("=" * 108)

tot_events = tot_mismatch = tot_leg_rewrite = 0
lags = []
for sym in syms:
    df = klines(sym, TF)
    if df is None or len(df) < 500:
        print(f"  {sym:<8} — нет данных")
        continue
    dd = df.reset_index(drop=True)
    full = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)

    # ── A. причинность: события, видимые на срезе, должны совпасть с полными ──
    cut = len(dd) - 120
    part = run_structure(dd.iloc[:cut].copy(), swing_len=50, internal_len=5, record_legs=True)
    ev_full = {(e.i, e.kind, e.bull, e.internal) for e in full.events if e.i < cut}
    ev_part = {(e.i, e.kind, e.bull, e.internal) for e in part.events}
    miss = ev_full ^ ev_part                     # симметричная разность
    tot_events += len(ev_full)
    tot_mismatch += len(miss)

    # ── C. стабильность ноги: переписывается ли origin назад ──
    legs = full.leg_history
    rewrites = 0
    prev = None
    for lg in legs:
        if not lg or lg.get("origin") is None:
            continue
        cur = (lg.get("origin"), lg.get("trend"))
        if prev is not None and cur[1] == prev[1] and cur[0] != prev[0]:
            rewrites += 1                        # origin сменился БЕЗ смены направления
        prev = cur
    tot_leg_rewrite += rewrites

    # ── B. лаг события относительно экстремума, который оно подтверждает ──
    hi, lo = dd.high.values, dd.low.values
    for e in full.events:
        if e.i < 60:
            continue
        w0 = max(0, e.i - 50)
        ext_i = (int(np.argmax(hi[w0:e.i + 1])) + w0 if e.bull
                 else int(np.argmin(lo[w0:e.i + 1])) + w0)
        lags.append(e.i - ext_i)

    # ── D. геометрия ──
    seq, prev_key = [], None
    for lg in legs:
        if not lg or lg.get("origin") is None:
            continue
        k = (lg.get("origin"), lg.get("trend"))
        if k != prev_key:
            seq.append(k)
            prev_key = k
    n_sw = sum(1 for e in full.events if not e.internal)
    print(f"  {sym:<8} событий {len(full.events):<4} (SWING {n_sw:<3}) · уникальных ног {len(seq):<4}"
          f" · причинность: {'✅' if not miss else f'❌ {len(miss)}'}"
          f" · перезаписей origin {rewrites}")

print("\n" + "─" * 108)
print(f"A. ПРИЧИННОСТЬ    : {tot_events} событий на срезах · расхождений "
      f"{tot_mismatch} → {'✅ ЧИСТО' if tot_mismatch == 0 else '🔴 ПЕРЕПИСЫВАЕТ ПРОШЛОЕ'}")
if lags:
    a = np.array(lags)
    print(f"B. ЛАГ СОБЫТИЙ    : медиана {np.median(a):.0f} баров · q90 {np.percentile(a, 90):.0f} "
          f"· максимум {a.max()} (событие подтверждает экстремум, лаг ожидаем)")
print(f"C. ПЕРЕЗАПИСЬ НОГИ: {tot_leg_rewrite} случаев смены origin без смены направления "
      f"{'✅' if tot_leg_rewrite == 0 else '⚠️ нога тянется за ценой'}")
print("\n🔴 Машинные проверки НЕ заменяют сверку с индикатором на графике —")
print("   они ловят переписывание прошлого и лаг, но не то, ПРАВИЛЬНУЮ ли ногу движок метит.")
