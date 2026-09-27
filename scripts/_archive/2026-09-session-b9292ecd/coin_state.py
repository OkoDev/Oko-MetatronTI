"""Сырьё для ручного разбора монеты: свинги и сломы по ТФ, волновая диагностика ядра, WT, ATRTrend, нога, фибо."""
import sys, json
import numpy as np, pandas as pd
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from core.waves.bingx_klines import fetch_closed
from core.smc.oko_sm_engine import run_structure, _swings
from core.waves.wave5_core import wave_diag, WaveParams, mark_impulse
from core.indicators.indicators import calculate_wt, calculate_trend

SYM = sys.argv[1] if len(sys.argv) > 1 else "BCH"
D = {"1d": fetch_closed(SYM, "1d", 600), "4h": fetch_closed(SYM, "4h", 1500), "1h": fetch_closed(SYM, "1h", 1500), "15m": fetch_closed(SYM, "15m", 1000)}
for k, v in D.items():
    v.to_pickle(f"coin_{SYM}_{k}.pkl")
    print(k, len(v), v.index[0], v.index[-1], "close", v.close.iloc[-1])
px = float(D["15m"].close.iloc[-1]); print("\nЦЕНА", px)
SC = {"1d": [(10, 3), (5, 2)], "4h": [(15, 4), (50, 5)], "1h": [(50, 5), (60, 15)], "15m": [(50, 5)]}
for tf, scs in SC.items():
    d = D[tf]; dr = d.reset_index(drop=True)
    for sw, il in scs:
        sws = _swings(dr.high, dr.low, sw)
        print(f"\n== {tf} свинги len={sw} (последние 9): " + " → ".join(f"{d.index[int(s[1])]:%m-%d %H}h {'H' if s[3] else 'L'} {s[2]:.1f}" for s in sws[-9:]))
        st = run_structure(dr[["open", "high", "low", "close"]], swing_len=sw, internal_len=il)
        ev = st.events[-8:]
        print(f"   сломы (swing={sw}/int={il}): " + " · ".join(f"{d.index[e.i]:%m-%d %H}h {'int' if e.internal else 'SW'} {e.kind} {'↑' if e.bull else '↓'} {e.level:.1f}" for e in ev))
        print(f"   trail: up {st.trail_up} dn {st.trail_dn}")
    wt = calculate_wt(dr.copy()); tr = calculate_trend(dr.copy(), atr_period=43, factor=1.25)
    w1, w2 = wt.wt1.values, wt.wt2.values
    print(f"   WT {tf}: wt1 {w1[-1]:.1f} wt2 {w2[-1]:.1f} (5 баров назад {w1[-6]:.1f}) · ATRTrend {tr.trend.values[-1]} (сменился {int((tr.trend != tr.trend.shift()).values[::-1].argmax())} баров назад)")
for tf, sw, il in (("4h", 15, 4), ("1h", 60, 15)):
    dg = wave_diag(D[tf], WaveParams(sw=sw, il=il))
    print(f"\nwave_diag {tf} {sw}/{il}: {dg['why']}")
    print("   зигзаг: " + " → ".join(f"{t:%m-%d %H}h {'H' if top else 'L'} {p:.1f}" for t, p, top in dg["zz"]))
    print("   сетапы ядра за 30 сут:", [(s["side"], str(s["top_time"])[:13], round(s["p5"], 1), s["core_full"]) for s in mark_impulse(D[tf], pd.Timestamp.utcnow(), WaveParams(sw=sw, il=il), tf, lookback=180)])
