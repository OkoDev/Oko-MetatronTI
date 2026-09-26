# -*- coding: utf-8 -*-
"""ТОЧНЫЙ ВХОД — slom15m → fib OTE → вход OB-зона В OTE (или WT-cross) → тугой структурный SL → выход CHoCH.

Диагноз (база −0.06R на 230k): крудо-вход (голое касание зоны) = 63% SL. Точный вход (юзер):
OB-зона внутри OTE + реакция, SL за OB (тугой структурный, risk×10 БЕЗ артефакта — OB реальной высоты).
Вариант входа: WT-cross в OTE. Сравниваем: bare vs OB-in-OTE vs WT-cross. Выход = противоположный CHoCH.
Один калькулятор: detect_order_blocks/detect_structure_breaks/find_setups_zz/calculate_wt.
Запуск: python scripts/ote_precise_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--ote-precise"
BUF = 0.0015
RETEST = 60
MAXHOLD = 480
RT = 0.10
TP_REPORT = 3.0   # для net@3R сводки


def _load(conn, sym):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='15m' ORDER BY time",
                           conn, params=(sym,))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _exit_R(df, d, entry, slv, ei, setups, si, pos):
    """выход на противоположном CHoCH или SL раньше. → net R."""
    risk = abs(entry - slv)
    if risk <= 0: return None
    opp = "short" if d == "long" else "long"
    xi = None
    for s2 in setups[si + 1:]:
        if s2["direction"] == opp:
            j = pos.get(s2["choch_ts"])
            if j is not None and j > ei: xi = j; break
    x_end = xi if xi is not None else min(ei + MAXHOLD, len(df) - 1)
    lo = df["low"].values; hi = df["high"].values; cl = df["close"].values
    ex = None
    for k in range(ei, x_end + 1):
        if d == "long":
            if lo[k] <= slv: ex = slv; break
        else:
            if hi[k] >= slv: ex = slv; break
    if ex is None: ex = cl[x_end]
    R = ((ex - entry) if d == "long" else (entry - ex)) / risk
    fee = RT / (risk / entry * 100)
    return R - fee


def test_pair(conn, sym):
    from core.smc.smc_engine import zigzag_atr, find_setups_zz, detect_structure_breaks, detect_order_blocks
    from core.indicators.indicators import calculate_wt
    df = _load(conn, sym)
    if df is None or len(df) < 300: return []
    setups = find_setups_zz(zigzag_atr(df), df)
    if len(setups) < 2: return []
    pos = {ts: i for i, ts in enumerate(df.index)}
    obs = detect_order_blocks(df, detect_structure_breaks(df, length=5))
    wt1 = calculate_wt(df.copy())["wt1"].values
    lo = df["low"].values; hi = df["high"].values; cl = df["close"].values; n = len(df)
    out = []
    for si, s in enumerate(setups):
        d = s["direction"]; ote_lo, ote_hi = s["ote"]
        ci = pos.get(s["choch_ts"])
        if ci is None: continue
        want = "bull" if d == "long" else "bear"
        # --- РЕЖИМ 1: OB-зона внутри OTE ---
        ob_zone = None
        for ob in obs:
            if ob.kind != want: continue
            t, b = max(ob.top, ob.bottom), min(ob.top, ob.bottom)
            if b <= ote_hi and t >= ote_lo:   # OB пересекает OTE
                ob_zone = (b, t); break
        if ob_zone is not None:
            b, t = ob_zone
            ei = None
            for j in range(ci + 1, min(ci + 1 + RETEST, n)):
                if lo[j] <= t and hi[j] >= b:   # ретест OB
                    ei = j; break
            if ei is not None:
                if d == "long":
                    entry = min(cl[ei], t); slv = b * (1 - BUF)
                else:
                    entry = max(cl[ei], b); slv = t * (1 + BUF)
                if (d == "long" and entry > slv) or (d == "short" and slv > entry):
                    net = _exit_R(df, d, entry, slv, ei, setups, si, pos)
                    if net is not None:
                        out.append({"mode": "OB", "dir": d, "net": net, "sl_pct": round(abs(entry - slv) / entry * 100, 3)})
        # --- РЕЖИМ 2 (вариант): WT-cross в OTE ---
        ei = None
        for j in range(ci + 1, min(ci + 1 + RETEST, n)):
            if not (lo[j] <= ote_hi and hi[j] >= ote_lo): continue
            if j < 1: continue
            cross_up = wt1[j - 1] <= 0 and wt1[j] > wt1[j - 1]  # упрощ: WT разворот вверх
            cross_dn = wt1[j - 1] >= 0 and wt1[j] < wt1[j - 1]
            if (d == "long" and wt1[j] > wt1[j - 1]) or (d == "short" and wt1[j] < wt1[j - 1]):
                ei = j; break
        if ei is not None:
            entry = cl[ei]
            slv = s["levels"][1.0] * (1 - BUF) if d == "long" else s["levels"][1.0] * (1 + BUF)
            if (d == "long" and entry > slv) or (d == "short" and slv > entry):
                net = _exit_R(df, d, entry, slv, ei, setups, si, pos)
                if net is not None:
                    out.append({"mode": "WTcross", "dir": d, "net": net, "sl_pct": round(abs(entry - slv) / entry * 100, 3)})
    return out


def agg(rows, tp=None):
    n = len(rows)
    if n == 0: return None
    nets = [r["net"] for r in rows]
    wins = sum(1 for x in nets if x > 0)
    return {"n": n, "net": round(sum(nets) / n, 3), "wr": round(100 * wins / n), "sumR": round(sum(nets), 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0); a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[precise] пар: {len(syms)}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[precise] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    L = [f"# ТОЧНЫЙ ВХОД: OB-в-OTE vs WT-cross vs (база была −0.060) — {len(allr)} сделок\n",
         f"> выход=противоположный CHoCH (раннер)/SL. комиссия {RT}%. SL: OB=за OB(тугой); WTcross=за 1.0 фибы.\n",
         "\n## по режиму входа × направление (net = E[R] выхода на CHoCH)\n| режим | dir | n | net E[R] | WR | sumR |\n|---|---|---|---|---|---|"]
    for mode in ("OB", "WTcross"):
        for d in ("long", "short"):
            m = agg([r for r in allr if r["mode"] == mode and r["dir"] == d])
            if m and m["n"] >= 20:
                flag = "🟢" if m["net"] > 0 else "🔴"
                L.append(f"| {mode} | {d} | {m['n']} | **{m['net']:+.3f}** {flag} | {m['wr']}% | {m['sumR']:+.1f} |")
    # итоги по режиму
    L.append("\n## итог по режиму\n| режим | n | net E[R] | WR |\n|---|---|---|---|")
    for mode in ("OB", "WTcross"):
        m = agg([r for r in allr if r["mode"] == mode])
        if m: L.append(f"| {mode} | {m['n']} | **{m['net']:+.3f}** | {m['wr']}% |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
