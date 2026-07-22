# -*- coding: utf-8 -*-
"""OTE-EGOR-LEG — решающий бэктест: ожидающий лимит на НОГАХ ЕГОРА (23.07).

Нога = oko_sm_engine (порт OKO-SM v163, верифицирован 1:1 с графиком: BTC 15/15, ETH 13/13).
Правило Егора (23.07, прямая речь): «пока структура старшего не сломана — внутреннее движение
коррекционно; на OTE-зоне старшего развилка: откат от зоны → сопровождать ПО старшему на
обновление экстремума; пробой насквозь → слом (это наш SL за fib 1.0)».

Механика (каузально: нога бара t-1 → решение на баре t):
  senior trend определён → ожидающий лимит на fib F старшей ноги (retracement к origin),
  направление ПО тренду. SL за fib 1.0 (origin ± буфер). TP = extreme (fib 0, «обновление»).
  Нога растёт (trail) → лимит переставляется. Тренд флипнул → pending отмена; позиция живёт до SL/TP.
  Fill: касание лимита баром. Конфликт в баре: SL приоритет (консервативно).

Свип fib: 0.618 / 0.705 / 0.786 / 0.886. net% = ход − costs (0.1%). ЗАКОН №1.
Данные: ohlcv_cache 4h (2022-01..2026-05), топ-N ликвидных. По годам + LONG/SHORT.
Запуск: python scripts/ote_egor_leg_backtest.py [--syms 50]
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from core.smc.oko_sm_engine import run_structure

CACHE = "ohlcv_cache.db"
FIBS = (0.618, 0.705, 0.786, 0.886)
COSTS = 0.10
SL_BUF = 0.0015


def _liquid_universe(o, n):
    """Топ-N по $-обороту (avg volume*close последних 2000 баров 4h)."""
    syms = [r[0] for r in o.execute(
        "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='4h' AND symbol NOT LIKE '%:%'")]
    turn = []
    for s in syms:
        r = o.execute(
            "SELECT AVG(volume*close) FROM (SELECT volume, close FROM ohlcv_cache "
            "WHERE symbol=? AND timeframe='4h' ORDER BY time DESC LIMIT 2000)", (s,)).fetchone()
        if r and r[0]:
            turn.append((s, r[0]))
    turn.sort(key=lambda x: -x[1])
    return [s for s, _ in turn[:n]]


def _load(o, sym):
    rows = o.execute("SELECT time,open,high,low,close FROM ohlcv_cache "
                     "WHERE symbol=? AND timeframe='4h' ORDER BY time", (sym,)).fetchall()
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def backtest_symbol(df, fib):
    """→ list[(year, dir, net%)] по правилу Егора для одного fib."""
    st = run_structure(df, record_legs=True)
    legs = st.leg_history
    hv, lv, tv = df["high"].values, df["low"].values, df["time"].values
    n = len(df)
    trades = []
    pos = None      # dict(dir, entry, sl, tp, t_in)
    for t in range(1, n):
        leg = legs[t - 1]           # нога ПОСЛЕ бара t-1 — каузально
        # управление открытой позицией (SL приоритет)
        if pos is not None:
            if pos["dir"] == "long":
                if lv[t] <= pos["sl"]:
                    exitp = pos["sl"]
                elif hv[t] >= pos["tp"]:
                    exitp = pos["tp"]
                else:
                    exitp = None
                if exitp is not None:
                    net = (exitp - pos["entry"]) / pos["entry"] * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "LONG", net))
                    pos = None
            else:
                if hv[t] >= pos["sl"]:
                    exitp = pos["sl"]
                elif lv[t] <= pos["tp"]:
                    exitp = pos["tp"]
                else:
                    exitp = None
                if exitp is not None:
                    net = (pos["entry"] - exitp) / pos["entry"] * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "SHORT", net))
                    pos = None
            continue                 # одна позиция на символ; pending не работает пока в позиции

        if leg is None:
            continue
        o_, e_ = leg["origin"], leg["extreme"]
        if leg["trend"] == "long":
            # откат ВНИЗ к origin: fib f цена = extreme - f*(extreme-origin)
            lim = e_ - fib * (e_ - o_)
            sl = o_ * (1 - SL_BUF)
            if lim <= sl:
                continue
            if lv[t] <= lim:         # ожидающий лимит-BUY зафилился
                entry = lim
                # добит ли SL тем же баром (консервативно)
                if lv[t] <= sl:
                    net = (sl - entry) / entry * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "LONG", net))
                else:
                    pos = {"dir": "long", "entry": entry, "sl": sl, "tp": e_, "t_in": t}
        else:
            lim = e_ + fib * (o_ - e_)
            sl = o_ * (1 + SL_BUF)
            if lim >= sl:
                continue
            if hv[t] >= lim:
                entry = lim
                if hv[t] >= sl:
                    net = (entry - sl) / entry * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "SHORT", net))
                else:
                    pos = {"dir": "short", "entry": entry, "sl": sl, "tp": e_, "t_in": t}
    return trades


def _st(a):
    if not a:
        return 0, 0.0, 0.0
    return len(a), 100 * sum(1 for x in a if x > 0) / len(a), sum(a) / len(a)


def main():
    nsyms = 50
    if "--syms" in sys.argv:
        nsyms = int(sys.argv[sys.argv.index("--syms") + 1])
    o = sqlite3.connect(CACHE)
    uni = _liquid_universe(o, nsyms)
    print(f"🏛️ OTE НА НОГАХ ЕГОРА (oko_sm_engine) · 4h 2022-2026 · топ-{len(uni)} ликвидных")
    print(f"   правило: лимит на fib старшей ноги ПО тренду · SL за fib1.0 · TP=extreme\n")
    allres = {f: [] for f in FIBS}
    for i, sym in enumerate(uni):
        df = _load(o, sym)
        if len(df) < 300:
            continue
        for f in FIBS:
            allres[f].extend(backtest_symbol(df, f))
        if (i + 1) % 10 == 0:
            print(f"   … {i+1}/{len(uni)} символов")
    print(f"\n{'fib':>7} {'n':>6} {'WR':>5} {'net/сд':>9} | LONG net (n) | SHORT net (n)")
    print("   " + "─" * 66)
    for f in FIBS:
        tr = allres[f]
        n, wr, net = _st([x[2] for x in tr])
        ln = [x[2] for x in tr if x[1] == "LONG"]
        sh = [x[2] for x in tr if x[1] == "SHORT"]
        nl, _, netl = _st(ln)
        ns_, _, nets = _st(sh)
        mark = "🟢" if net > 0.10 else ("🔴" if net < -0.10 else "⚪")
        print(f"{mark} {f:5.3f} {n:6} {wr:4.0f}% {net:+8.3f}% | {netl:+7.3f} ({nl}) | {nets:+7.3f} ({ns_})")
    # по годам для лучшего fib
    best = max(FIBS, key=lambda f: _st([x[2] for x in allres[f]])[2] if allres[f] else -9)
    print(f"\n── fib {best:.3f} по годам ──")
    for y in (2022, 2023, 2024, 2025, 2026):
        yr = [x[2] for x in allres[best] if x[0] == y]
        n, wr, net = _st(yr)
        if n:
            mark = "🟢" if net > 0.10 else ("🔴" if net < -0.10 else "⚪")
            print(f"   {mark} {y}: n={n:5} WR{wr:3.0f}% net={net:+.3f}%")


if __name__ == "__main__":
    main()
