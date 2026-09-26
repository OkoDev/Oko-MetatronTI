# -*- coding: utf-8 -*-
"""ЧЕСТНЫЙ point-in-time бэктест method_v2_mtf (после находки look-ahead, DS 05.07).

Look-ahead: сетап с w3-сломом на баре e_ts виден в full-df, но НЕ виден live в момент e_ts
(свинги в хвосте df не подтверждены confirmed_swings). Тест lookahead_true: 16/19 исчезают.

ЧЕСТНАЯ методика (per-setup передетект — быстро, O(сетапов), а не O(баров)):
  1. detect_v2_mtf(full) → кандидаты (могут содержать look-ahead).
  2. Для каждого: обрезать df до e_ts + LAG баров, ПЕРЕДЕТЕКТИТЬ на срезе.
     Если на срезе есть свежий сетап того же направления → он РЕАЛЕН, берём его
     point-in-time entry/sl/targets, вход по цене close[confirm_bar]. Иначе отбрасываем.
  3. LAG подбираем так, чтобы слом реально подтвердился (свинг закрыт).

Вход сдвинут на LAG баров вперёд от e_ts = реалистичная задержка подтверждения слома.
% net, интрабар, TRAIN/TEST split.

Запуск: python scripts/test_v2_mtf_honest.py [--liquid N] [--lag K]
"""
import argparse
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.smc.method_v2_mtf import detect_v2_mtf
from scripts.test_method_v2 import load_df

CACHE = "ohlcv_cache.db"
COSTS = 0.2
SHARES = (0.4, 0.3, 0.3)
TIMEOUT_BARS = 800
LEN_LTF = 5


def liquid(tf, topn):
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?", (tf,))]
    rk = []
    for s in syms:
        try:
            df = load_df(s, tf)
            if len(df) >= 600:
                rk.append(((df["close"] * df["volume"]).median(), s))
        except Exception:
            pass
    rk.sort(reverse=True)
    return [s for _, s in rk[:topn]]


def simulate(d15, ei, direction, entry, sl, tps):
    high, low, close = d15["high"].values, d15["low"].values, d15["close"].values
    n = len(d15)
    lng = direction == "LONG"
    rem, pnl = 1.0, 0.0
    hit = [False, False, False]
    tg = list(tps)
    for j in range(ei + 1, min(ei + 1 + TIMEOUT_BARS, n)):
        if (low[j] <= sl) if lng else (high[j] >= sl):
            move = (sl - entry) / entry * 100 if lng else (entry - sl) / entry * 100
            pnl += rem * move; rem = 0.0; break
        for k in range(3):
            if hit[k] or rem <= 0:
                continue
            if (high[j] >= tg[k]) if lng else (low[j] <= tg[k]):
                move = (tg[k] - entry) / entry * 100 if lng else (entry - tg[k]) / entry * 100
                pnl += SHARES[k] * move; rem -= SHARES[k]; hit[k] = True
                if k == 0:
                    sl = entry
        if rem <= 1e-9:
            break
    if rem > 1e-9:
        jl = min(ei + 1 + TIMEOUT_BARS, n) - 1
        move = (close[jl] - entry) / entry * 100 if lng else (entry - close[jl]) / entry * 100
        pnl += rem * move
    return pnl - COSTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liquid", type=int, default=30)
    ap.add_argument("--lag", type=int, default=LEN_LTF, help="баров задержки на подтверждение слома")
    args = ap.parse_args()
    syms = liquid("15m", args.liquid)
    print(f"символов: {len(syms)} · lag={args.lag} 15m-баров (per-setup передетект)")

    res = []
    n_cand = n_survive = 0
    for si, sym in enumerate(syms):
        try:
            d4 = load_df(sym, "4h")
            d15 = load_df(sym, "15m")
            if len(d4) < 100 or len(d15) < 700:
                continue
            cands = detect_v2_mtf(d4, d15)
            n_cand += len(cands)
            idx15 = d15.index
            pos = {ts: i for i, ts in enumerate(idx15)}
            for s in cands:
                e_i = pos.get(s.entry_ts)
                if e_i is None:
                    continue
                conf_i = e_i + args.lag
                if conf_i >= len(d15):
                    continue
                conf_ts = idx15[conf_i]
                d15c = d15.iloc[:conf_i + 1]
                d4c = d4[d4.index <= conf_ts]
                if len(d4c) < 100:
                    continue
                re = detect_v2_mtf(d4c, d15c)
                if not re:
                    continue
                # свежий сетап того же направления, вход в пределах [e_ts .. conf_ts]
                match = [x for x in re if x.direction == s.direction and x.entry_ts >= s.entry_ts]
                if not match:
                    continue
                sm = match[-1]  # самый свежий, посчитан point-in-time
                n_survive += 1
                entry_now = float(d15["close"].iloc[conf_i])  # цена момента подтверждения
                lng = sm.direction == "LONG"
                if (sm.targets[0] <= entry_now) if lng else (sm.targets[0] >= entry_now):
                    continue
                if (entry_now <= sm.sl) if lng else (entry_now >= sm.sl):
                    continue
                net = simulate(d15, conf_i, sm.direction, entry_now, sm.sl, sm.targets)
                res.append({"net": net, "dir": sm.direction, "sym": sym, "year": str(conf_ts)[:4],
                            "t1": None})
        except Exception as e:
            print(f"  {sym}: {e}")
        if (si + 1) % 10 == 0:
            print(f"  ...{si+1}/{len(syms)}, кандидатов {n_cand}, выжило {n_survive}, сделок {len(res)}", flush=True)

    print(f"\nкандидатов (full-detect): {n_cand} · выжило point-in-time: {n_survive} "
          f"({n_survive/max(n_cand,1)*100:.0f}%) · торговано: {len(res)}")
    if not res:
        print("сделок нет"); return

    def stat(lst):
        if not lst:
            return "n=0"
        nets = [x["net"] for x in lst]
        return (f"n={len(nets):5d} net={sum(nets)/len(nets):+.3f}% "
                f"WR={sum(1 for v in nets if v>0)/len(nets)*100:.0f}% sum={sum(nets):+.0f}%")

    print(f"\n═══ ЧЕСТНЫЙ point-in-time (вход по цене момента подтверждения, +{args.lag} баров) ═══")
    print("  ALL: ", stat(res))
    for d in ("LONG", "SHORT"):
        print(f"  {d}:", stat([x for x in res if x["dir"] == d]))
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
