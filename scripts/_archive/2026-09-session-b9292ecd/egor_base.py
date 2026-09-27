# -*- coding: utf-8 -*-
"""ПОЛНАЯ БАЗА КАК ВТОРОЙ КОНТРОЛЬ (10.09.2026).

Превышение схемы +2.5 п.п. мерилось против случайного бара в ±30 дней от сигнала (C1).
На 1m-окне C1 оказался ХУЖЕ полной базы C2 (−0.229% против +0.901%) ⇒ сигналы
кучкуются в периоды, неудобные для C1, и превышение могло быть завышено.

Здесь считается C2 на полном окне 1h 2022-2026: КАЖДЫЙ 20-й бар, обе стороны,
тот же выход (разворот в противоположной зоне, таймаут 200). Если превышение
схемы над C2 близко к нулю — заявленные +2.5 п.п. были свойством выбора контроля.
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
MED_LEN, OS, OB, TIMEOUT, COST, STEP = 34, -60.0, 60.0, 200, 0.35, 20
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='1h' "
    "group by symbol having count(*) > 12000 order by symbol")]
print(f"символов: {len(syms)} · шаг {STEP} баров\n", flush=True)

rows = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='1h' order by time",
                    con, params=(sym,))
    if len(d) < 12000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    zone_up, zone_dn = cd & (w1 > OB), cu & (w1 < OS)
    cl, op = d.close.values, d.open.values
    yr = d.index.year.values
    for side in (1, -1):
        zone = zone_up if side == 1 else zone_dn
        for ii in range(MED_LEN + 6, n - 4, STEP):
            lim = min(ii + TIMEOUT, n - 1)
            jz = np.where(zone[ii + 1:lim + 1])[0]
            end = ii + 1 + int(jz[0]) if len(jz) else lim
            e = op[ii]
            rows.append((sym, side, (cl[end] - e) / e * 100 * side - COST,
                         end - ii, int(yr[ii])))
    if fi % 40 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

B = pd.DataFrame(rows, columns=["sym", "side", "pnl", "bars", "year"])
B.to_pickle(D + r"\egor_base.pkl")
S = pd.read_pickle(D + r"\egor_years_sig.pkl")
C = pd.read_pickle(D + r"\egor_years_ctl.pkl")
print(f"\nбаза C2: {len(B):,} · сигналов {len(S):,} · C1 {len(C):,}\n")

print("=== ТРИ УРОВНЯ: СИГНАЛ · C1 (±30д) · C2 (полная база) ===")
print(f"{'стор':>6} {'что':>22} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6} {'баров':>7}")
for side, sn in [(1, "long"), (-1, "short")]:
    for lbl, g in [("C0 сигнал", S[S.side == side]),
                   ("C1 случайный ±30д", C[C.side == side]),
                   ("C2 полная база", B[B.side == side])]:
        print(f"{sn:>6} {lbl:>22} {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% "
              f"{g.bars.median():>7.0f}")
    s_ = S[S.side == side].pnl
    print(f"{'':>6} {'превышение над C1':>22} "
          f"{s_.mean()-C[C.side==side].pnl.mean():+8.3f} п.п.")
    print(f"{'':>6} {'превышение над C2':>22} "
          f"{s_.mean()-B[B.side==side].pnl.mean():+8.3f} п.п.")
    print()

print("=== ПО ГОДАМ: сигнал − C2 (настоящее превышение над базой) ===")
print(f"{'стор':>6} {'год':>5} {'сигнал':>9} {'C1':>9} {'C2':>9} {'сиг−C1':>9} "
      f"{'сиг−C2':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for y in sorted(S.year.unique()):
        g = S[(S.side == side) & (S.year == y)]
        c1 = C[(C.side == side) & (C.year == y)]
        c2 = B[(B.side == side) & (B.year == y)]
        if len(g) < 40 or len(c2) < 40:
            continue
        m1 = c1.pnl.mean() if len(c1) > 20 else np.nan
        print(f"{sn:>6} {y:>5} {g.pnl.mean():+8.3f}% {m1:+8.3f}% {c2.pnl.mean():+8.3f}% "
              f"{g.pnl.mean()-m1:+8.3f}% {g.pnl.mean()-c2.pnl.mean():+8.3f}%")
    print()

print("=== ХРУПКОСТЬ БАЗЫ C2 (для сравнения с сигналом) ===")
for side, sn in [(1, "long"), (-1, "short")]:
    g = B[B.side == side]
    v = np.sort(g.pnl.values)[::-1]
    print(f"  {sn:>5}: всё {g.pnl.mean():+.3f}% · безтоп10% "
          f"{v[int(len(v)*.1):].mean():+.3f}% · медиана {g.pnl.median():+.3f}%")
