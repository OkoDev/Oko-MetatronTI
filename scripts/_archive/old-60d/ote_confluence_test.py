# -*- coding: utf-8 -*-
"""КОНФЛЮЕНЦИЯ в OTE — гипотеза Егора: «чем больше подтверждений в OTE, тем лучше отработка».

Считаем СКОЛЬКО подтверждений стакается в OTE-зоне (из окна импульса, как живой _collect_triggers):
  OB + FVG + SC + EQL (smc_engine детекторы) + WT-cross + div (на входе).
Сплит net по ЧИСЛУ подтверждений (0/1/2/3+). Режим: cont (BOS) vs reversal (CHoCH) раздельно.
SL = импульс-1.0 (база, WR25%, не тугой-OB что выбивало). Выход = противоположный CHoCH (раннер).
Вопрос: больше conf → выше net? (gravity-тезис, conf_score).
Запуск: python scripts/ote_confluence_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--ote-confluence"
BUF, RETEST, MAXHOLD, RT = 0.0015, 60, 480, 0.10


def _load(conn, sym):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='15m' ORDER BY time",
                           conn, params=(sym,))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _conf_count(imp, ote_lo, ote_hi, want, detF, detOB, detSB, detSC, detEQ):
    """Число подтверждений в OTE из окна импульса (как _collect_triggers)."""
    c = 0
    try:
        for fv in detF(imp):
            top, bot, dr = max(fv[1], fv[2]), min(fv[1], fv[2]), fv[3]
            if dr == want and bot <= ote_hi and top >= ote_lo: c += 1; break
    except Exception: pass
    try:
        for ob in detOB(imp, detSB(imp, length=5)):
            if ob.kind == want and min(ob.top, ob.bottom) <= ote_hi and max(ob.top, ob.bottom) >= ote_lo: c += 1; break
    except Exception: pass
    try:
        for sc in detSC(imp):
            if sc.direction == want and (ote_lo <= sc.bottom <= ote_hi or ote_lo <= sc.top <= ote_hi): c += 1; break
    except Exception: pass
    try:
        for (t1, p1, t2, p2, lab) in detEQ(imp):
            lvl = (p1 + p2) / 2
            ok = (want == "bull" and lab == "EQL") or (want == "bear" and lab == "EQH")
            if ok and ote_lo <= lvl <= ote_hi: c += 1; break
    except Exception: pass
    return c


def test_pair(conn, sym):
    from core.smc.smc_engine import (zigzag_atr, find_setups_zz, detect_structure_breaks,
                                     detect_order_blocks, detect_fvg, detect_sponsored_candle, detect_equal_levels)
    from core.indicators.indicators import calculate_wt
    from core.calculators.combinator_core import _wtx_divergences
    df = _load(conn, sym)
    if df is None or len(df) < 300: return []
    setups = find_setups_zz(zigzag_atr(df), df)
    if len(setups) < 2: return []
    pos = {ts: i for i, ts in enumerate(df.index)}
    wt1 = calculate_wt(df.copy())["wt1"].values
    _br, _ber, _bh, _beh = _wtx_divergences(wt1, df["low"].values, df["high"].values)
    dbull = np.asarray(_br, bool) | np.asarray(_bh, bool); dbear = np.asarray(_ber, bool) | np.asarray(_beh, bool)
    lo = df["low"].values; hi = df["high"].values; cl = df["close"].values; n = len(df)
    out = []
    for si, s in enumerate(setups):
        d = s["direction"]; ote_lo, ote_hi = s["ote"]; kind = s.get("kind", "")
        ci = pos.get(s["choch_ts"])
        if ci is None: continue
        want = "bull" if d == "long" else "bear"
        # вход: ретест в OTE
        ei = None
        for j in range(ci + 1, min(ci + 1 + RETEST, n)):
            if lo[j] <= ote_hi and hi[j] >= ote_lo: ei = j; break
        if ei is None: continue
        # confluence в OTE (окно импульса from..choch)
        try:
            imp = df.loc[s["from"][0]:s["choch_ts"]]
        except Exception:
            imp = df.iloc[max(0, ci - 30):ci + 1]
        conf = _conf_count(imp, ote_lo, ote_hi, want, detect_fvg, detect_order_blocks, detect_structure_breaks, detect_sponsored_candle, detect_equal_levels)
        # + WT-cross и div на входе
        if ei >= 1 and ((d == "long" and wt1[ei] > wt1[ei - 1]) or (d == "short" and wt1[ei] < wt1[ei - 1])): conf += 1
        w0 = max(0, ei - 10)
        if (d == "long" and dbull[w0:ei + 1].any()) or (d == "short" and dbear[w0:ei + 1].any()): conf += 1
        # вход/SL (импульс-SL, база)
        entry = (ote_lo + ote_hi) / 2.0
        slv = s["levels"][1.0] * (1 - BUF) if d == "long" else s["levels"][1.0] * (1 + BUF)
        risk = abs(entry - slv)
        if risk <= 0: continue
        # выход: противоположный CHoCH / SL
        opp = "short" if d == "long" else "long"
        xi = None
        for s2 in setups[si + 1:]:
            if s2["direction"] == opp:
                j = pos.get(s2["choch_ts"])
                if j is not None and j > ei: xi = j; break
        x_end = xi if xi is not None else min(ei + MAXHOLD, n - 1)
        ex = None
        for k in range(ei, x_end + 1):
            if (d == "long" and lo[k] <= slv) or (d == "short" and hi[k] >= slv): ex = slv; break
        if ex is None: ex = cl[x_end]
        R = ((ex - entry) if d == "long" else (entry - ex)) / risk
        net = R - RT / (risk / entry * 100)
        out.append({"dir": d, "conf": conf, "mode": kind, "net": net})
    return out


def agg(rows):
    n = len(rows)
    if not n: return None
    nets = [r["net"] for r in rows]
    return {"n": n, "net": round(sum(nets) / n, 3), "wr": round(100 * sum(1 for x in nets if x > 0) / n), "sumR": round(sum(nets), 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0); a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[confl] пар: {len(syms)}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[confl] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    L = [f"# КОНФЛЮЕНЦИЯ в OTE (гипотеза: больше conf → лучше) — {len(allr)} сделок\n",
         f"> conf = OB+FVG+SC+EQL(импульс) + WT-cross + div. выход CHoCH-раннер. комса {RT}%.\n",
         "\n## net по ЧИСЛУ подтверждений в OTE\n| conf | n | net E[R] | WR | sumR |\n|---|---|---|---|---|"]
    for c in range(0, 7):
        lab = f"{c}" if c < 6 else "6+"
        sub = [r for r in allr if (r["conf"] == c if c < 6 else r["conf"] >= 6)]
        m = agg(sub)
        if m and m["n"] >= 20:
            flag = "🟢" if m["net"] > 0 else "🔴"
            L.append(f"| conf={lab} | {m['n']} | **{m['net']:+.3f}** {flag} | {m['wr']}% | {m['sumR']:+.1f} |")
    # cont vs reversal × conf>=3
    L.append("\n## режим × conf≥3 (cont=BOS / reversal=CHoCH)\n| режим | dir | n | net E[R] | WR |\n|---|---|---|---|---|")
    for mode in ("BOS", "CHoCH"):
        for d in ("long", "short"):
            m = agg([r for r in allr if r["mode"] == mode and r["dir"] == d and r["conf"] >= 3])
            if m and m["n"] >= 20:
                L.append(f"| {mode} | {d} | {m['n']} | **{m['net']:+.3f}** | {m['wr']}% |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
