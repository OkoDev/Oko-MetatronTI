# -*- coding: utf-8 -*-
"""ЧЕСТНЫЙ point-in-time бэктест ПРАВИЛЬНОГО движка метода Егора (05.07).

После находки: method_v2_mtf был ДУБЛЁМ (голый detect_structure_breaks, ждёт length, вход
на BOS) — выброшен. Метод Егора = вход на ОТКАТЕ/РЕТЕСТЕ после слома, нога дорисована live
через append_provisional_leg (chart-builder, глазами верифицирован). Движок УЖЕ есть:
`ote_retest_setups(provisional=True)` — слом CHoCH → OTE → ретест = вход.

Честно: provisional активен ТОЛЬКО на КРАЕ df. Значит идём point-in-time скользящим окном
(каждый срез = «сейчас», как живой чарт), вход при СВЕЖЕМ ретесте, цена момента. Тугой
стоп за 1.0 импульса (из движка), цель = R-лестница (асимметрия метода: стоп короткий,
цель дальняя). % net, интрабар.

Запуск: python scripts/test_ote_retest_honest.py [--liquid N] [--tf 1h] [--step K] [--win W]
"""
import argparse
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.smc.smc_engine import ote_retest_setups
from core.smc.ote_matrix import structure_trend
from core.smc.method_egor import detect_method_egor
from scripts.test_method_v2 import load_df

CACHE = "ohlcv_cache.db"
COSTS = 0.2
SHARES = (0.4, 0.3, 0.3)
RMULTS = (2.0, 4.0, 6.0)   # асимметрия: тугой стоп, дальняя цель
TIMEOUT_BARS = 300


def liquid(tf, topn):
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?", (tf,))]
    rk = []
    for s in syms:
        try:
            df = load_df(s, tf)
            if len(df) >= 3000:
                rk.append(((df["close"] * df["volume"]).median(), s))
        except Exception:
            pass
    rk.sort(reverse=True)
    return [s for _, s in rk[:topn]]


def simulate(df, ei, direction, entry, sl, tps=None):
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    lng = direction in ("LONG", "long")
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    # tps=None → R-лестница (изолирует вход); иначе явные цели (OTE большого импульса)
    tg = list(tps) if tps is not None else [entry + m * risk if lng else entry - m * risk for m in RMULTS]
    # цели должны быть по правильную сторону входа
    if lng and not all(t > entry for t in tg):
        return None
    if not lng and not all(t < entry for t in tg):
        return None
    rem, pnl = 1.0, 0.0
    hit = [False, False, False]
    cur_sl = sl
    for j in range(ei + 1, min(ei + 1 + TIMEOUT_BARS, n)):
        if (low[j] <= cur_sl) if lng else (high[j] >= cur_sl):
            move = (cur_sl - entry) / entry * 100 if lng else (entry - cur_sl) / entry * 100
            pnl += rem * move; rem = 0.0; break
        for k in range(3):
            if hit[k] or rem <= 0:
                continue
            if (high[j] >= tg[k]) if lng else (low[j] <= tg[k]):
                move = (tg[k] - entry) / entry * 100 if lng else (entry - tg[k]) / entry * 100
                pnl += SHARES[k] * move; rem -= SHARES[k]; hit[k] = True
                if k == 0:
                    cur_sl = entry   # BE после TP1
        if rem <= 1e-9:
            break
    if rem > 1e-9:
        jl = min(ei + 1 + TIMEOUT_BARS, n) - 1
        move = (close[jl] - entry) / entry * 100 if lng else (entry - close[jl]) / entry * 100
        pnl += rem * move
    return pnl - COSTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liquid", type=int, default=8)
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--step", type=int, default=2, help="шаг детекции в барах (реалистичный live-скан)")
    ap.add_argument("--win", type=int, default=1500, help="скользящее окно детекции (баров)")
    ap.add_argument("--depth", type=int, default=11)
    ap.add_argument("--side", type=int, default=0,
                    help="0=нет · 1=trend-follow gate · 2=REVERSAL у экстремума большого 4h + OTE-цели")
    ap.add_argument("--edge", type=float, default=0.65, help="порог близости к экстремуму (side=2)")
    args = ap.parse_args()
    syms = liquid(args.tf, args.liquid)
    side_tf = "4h"
    tag = {0: "БЕЗ стороны", 1: "+trend-follow gate",
           2: "+РАЗВОРОТ у экстремума 4h + OTE-цели"}[args.side]
    print(f"символов: {len(syms)} · tf={args.tf} · окно={args.win} · step={args.step} · {tag} (point-in-time, provisional)")

    res = []
    n_side_block = 0
    for si, sym in enumerate(syms):
        try:
            df = load_df(sym, args.tf)
            n = len(df)
            if n < args.win + 500:
                continue
            idx = df.index
            close = df["close"].values
            # СТОРОНА: предпосчёт 4h structure_trend по каждому 4h-бару (point-in-time срезы),
            # потом lookup последнего 4h ≤ момента T. O(n4h) вместо O(n1h/step) — быстрее.
            side_ts = side_ctx = None
            if args.side:
                import numpy as np
                df4 = load_df(sym, side_tf)
                s_ts, s_ctx = [], []
                for j in range(60, len(df4)):
                    st = structure_trend(df4.iloc[:j + 1].tail(400))
                    s_ts.append(df4.index[j])
                    s_ctx.append((st.get("trend"), st.get("break_level"), st.get("extreme")))
                side_ts = np.array(s_ts); side_ctx = s_ctx
            busy_until = -1
            import numpy as np
            for T in range(args.win, n, args.step):
                if T <= busy_until:
                    continue
                win = df.iloc[T - args.win:T + 1]
                entry_now = float(close[T])
                if args.side == 2:
                    # МЕТОД ЕГОРА через единое ядро core.smc.method_egor (reuse с SHADOW)
                    k = int(np.searchsorted(side_ts, idx[T], side="right")) - 1
                    trend, brk, ext = side_ctx[k] if k >= 0 else (None, None, None)
                    ms = detect_method_egor(win, htf_trend=trend, htf_break=brk, htf_extreme=ext,
                                            entry_price=entry_now, edge=args.edge, depth=args.depth,
                                            fresh_bars=args.step)
                    if not ms:
                        n_side_block += 1; continue
                    m = ms[0]
                    net = simulate(df, T, m["direction"], m["entry"], m["sl"], m["targets"])
                    if net is None:
                        continue
                    res.append({"net": net, "dir": m["direction"], "sym": sym,
                                "year": str(idx[T])[:4], "conf": m["confluence"]})
                    busy_until = T + TIMEOUT_BARS
                    continue
                # side 0/1: baseline / trend-follow (R-цели) — для сравнения
                setups = ote_retest_setups(win, provisional=True, only_choch=True, depth=args.depth)
                if not setups:
                    continue
                cutoff = win.index[-args.step]
                fresh = [s for s in setups if s["entry_ts"] >= cutoff]
                if not fresh:
                    continue
                s = fresh[-1]
                lng = s["direction"] == "long"
                sl = s["sl"]
                if args.side == 1:
                    k = int(np.searchsorted(side_ts, idx[T], side="right")) - 1
                    trend = side_ctx[k][0] if k >= 0 else None
                    if trend != s["direction"]:
                        n_side_block += 1; continue
                if (entry_now <= sl) if lng else (entry_now >= sl):
                    continue
                net = simulate(df, T, s["direction"], entry_now, sl)
                if net is None:
                    continue
                res.append({"net": net, "dir": "LONG" if lng else "SHORT",
                            "sym": sym, "year": str(idx[T])[:4], "conf": s["confluence"]})
                busy_until = T + TIMEOUT_BARS     # один сетап на символ пока живёт (дедуп)
        except Exception as e:
            print(f"  {sym}: {type(e).__name__}: {e}")
        print(f"  ...{si+1}/{len(syms)} {sym}: сделок всего {len(res)}", flush=True)

    if not res:
        print("сделок нет"); return

    def stat(lst):
        if not lst:
            return "n=0"
        nets = [x["net"] for x in lst]
        return (f"n={len(nets):5d} net={sum(nets)/len(nets):+.3f}% "
                f"WR={sum(1 for v in nets if v>0)/len(nets)*100:.0f}% sum={sum(nets):+.0f}%")

    if args.side:
        print(f"\n(СТОРОНА отсеяла {n_side_block} входов против HTF-тренда)")
    print(f"\n═══ ЧЕСТНЫЙ ote_retest (вход на ОТКАТЕ, provisional, point-in-time) · {tag} ═══")
    print("  ALL: ", stat(res))
    for d in ("LONG", "SHORT"):
        print(f"  {d}:", stat([x for x in res if x["dir"] == d]))
    print("  conf (вход в конфлюэнции OB/FVG):")
    print("    conf≥1:", stat([x for x in res if x["conf"] >= 1]))
    print("    conf=0:", stat([x for x in res if x["conf"] == 0]))
    print("  по годам:")
    for y in sorted(set(x["year"] for x in res)):
        print(f"    {y}:", stat([x for x in res if x["year"] == y]))
    train = [x for x in res if x["year"] <= "2024"]
    test = [x for x in res if x["year"] >= "2025"]
    print("  WALK-FORWARD:")
    print("    TRAIN(≤2024):", stat(train))
    print("    TEST (≥2025):", stat(test))


if __name__ == "__main__":
    main()
