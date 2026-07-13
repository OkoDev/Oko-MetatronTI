# -*- coding: utf-8 -*-
"""СТРАТЕГИЯ #2 LIQUIDITY GRAB (research) — sweep EQH/EQL → возврат → разворот.

Из 7-strategy дока юзера. Самый НОВЫЙ механизм (у нас не меренный): маркет-мейкер
снимает стопы за очевидным уровнем (EQH/EQL) и разворачивает. Вход на возврате.
  - EQL sweep (пробили лои, вернулись выше) → LONG (разворот вверх).
  - EQH sweep (пробили хаи, вернулись ниже) → SHORT.
  SL = фитиль sweep (экстремум пробоя) — ЧЕСТНЫЙ структурный, не тугой.
  ВЫХОД = наш доказанный TP@1R / hybrid TSL / runner (контраст).
«Сначала без фильтров» (юзер): база = sweep+возврат. CHoCH-подтверждение = опц-фильтр (флаг).
Код БОТА не трогаем — это research на ohlcv_cache (87M баров).
Запуск: python scripts/ote_liqgrab_test.py [--pairs N] [--choch]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa
from core.trading.tsl_engine import compute_hybrid_tsl, TSL_PROFILES

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--liqgrab"
BUF, RT, MAXHOLD = 0.0015, 0.10, 480
SWEEP_WIN = 8       # баров на пробой+возврат (быстрый sweep, 1-3 свечи + запас)
RETURN_BARS = 5     # за сколько баров цена должна вернуться за уровень
TF_MIN_15 = 15
POLICIES = ["tp1", "hybrid", "runner"]


def _load(conn, sym, tf="15m"):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _walk_exits(D, entry, slv, ei, x_end, lo, hi, cl):
    risk = abs(entry - slv); fee = RT / (risk / entry * 100)
    def adv(j, lvl):
        tgt = entry - lvl * risk if D == "short" else entry + lvl * risk
        return (lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)
    def slhit(j, slp):
        return (hi[j] >= slp) if D == "short" else (lo[j] <= slp)
    def close_R():
        return ((entry - cl[x_end]) if D == "short" else (cl[x_end] - entry)) / risk
    res = {}
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
        if adv(j, 1.0): r = 1.0; break
    res["tp1"] = (r if r is not None else close_R()) - fee
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
    res["runner"] = (r if r is not None else close_R()) - fee
    ds = "LONG" if D == "long" else "SHORT"
    prof = TSL_PROFILES.get("ote_nested")
    cur = slv; r = None
    for j in range(ei, x_end + 1):
        if (hi[j] >= cur) if D == "short" else (lo[j] <= cur):
            r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
        dec = compute_hybrid_tsl(ds, entry, cl[j], slv, duration_minutes=(j - ei) * TF_MIN_15, profile=prof)
        if dec.new_sl and dec.new_sl > 0:
            cur = min(cur, dec.new_sl) if D == "short" else max(cur, dec.new_sl)
    res["hybrid"] = (r if r is not None else close_R()) - fee
    mfe = 0.0
    for j in range(ei, x_end + 1):
        fav = ((entry - lo[j]) if D == "short" else (hi[j] - entry)) / risk
        mfe = max(mfe, fav)
        if slhit(j, slv): break
    res["mfe"] = mfe; res["sl_pct"] = round(risk / entry * 100, 3)
    return res


def test_pair(conn, sym, require_choch):
    from core.smc.smc_engine import detect_equal_levels, zigzag_atr, find_setups_zz
    df = _load(conn, sym)
    if df is None or len(df) < 300: return []
    eqs = detect_equal_levels(df)
    if not eqs: return []
    pos = {ts: i for i, ts in enumerate(df.index)}
    lo = df["low"].values; hi = df["high"].values; cl = df["close"].values; n = len(df)
    # CHoCH-моменты (для опц-фильтра) — по направлению
    choch_idx = {"long": set(), "short": set()}
    if require_choch:
        for s in find_setups_zz(zigzag_atr(df), df):
            ci = pos.get(s["choch_ts"])
            if ci is not None and s.get("kind") == "CHoCH":
                choch_idx[s["direction"]].add(ci)
    out = []
    for (t1, p1, t2, p2, lab) in eqs:
        lvl = (p1 + p2) / 2.0
        i2 = pos.get(t2)
        if i2 is None or i2 + SWEEP_WIN >= n: continue
        D = "long" if lab == "EQL" else "short"
        # sweep: пробой за уровень + возврат за уровень в течение RETURN_BARS
        ei = None; sweep_ext = None
        for j in range(i2 + 1, min(i2 + 1 + SWEEP_WIN, n)):
            broke = (lo[j] < lvl) if D == "long" else (hi[j] > lvl)
            if not broke: continue
            ext = lo[j] if D == "long" else hi[j]   # фитиль sweep
            # ищем возврат за уровень в RETURN_BARS
            for k in range(j, min(j + 1 + RETURN_BARS, n)):
                back = (cl[k] > lvl) if D == "long" else (cl[k] < lvl)
                ext = min(ext, lo[k]) if D == "long" else max(ext, hi[k])
                if back:
                    ei = k; sweep_ext = ext; break
            if ei is not None: break
        if ei is None: continue
        if require_choch and not any(c >= ei - 3 and c <= ei + 1 for c in choch_idx[D]):
            continue
        entry = cl[ei]
        slv = sweep_ext * (1 - BUF) if D == "long" else sweep_ext * (1 + BUF)
        if (D == "long" and entry <= slv) or (D == "short" and entry >= slv): continue
        x_end = min(ei + MAXHOLD, n - 1)
        ex = _walk_exits(D, entry, slv, ei, x_end, lo, hi, cl)
        ex["dir"] = D
        out.append(ex)
    return out


def net_of(rows, key):
    vals = [r[key] for r in rows if key in r]
    n = len(vals)
    if not n: return None
    return {"n": n, "net": round(sum(vals) / n, 3), "wr": round(100 * sum(1 for x in vals if x > 0) / n)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=0)
    ap.add_argument("--choch", action="store_true", help="требовать CHoCH-подтверждение")
    a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[liqgrab] пар: {len(syms)} · choch-фильтр: {a.choch}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym, a.choch))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[liqgrab] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    L = [f"# LIQUIDITY GRAB (#2) — sweep EQH/EQL → разворот — {len(allr)} сделок\n",
         f"> SL=фитиль sweep (честный). выход TP@1R/hybrid/runner. choch-фильтр={a.choch}. комса {RT}%.\n",
         "\n## по направлению × политика выхода\n| dir | n | tp1 | hybrid | runner | MFEmed | SL%med |\n|---|---|---|---|---|---|---|"]
    for D in ("long", "short"):
        sub = [r for r in allr if r["dir"] == D]
        if len(sub) < 30: continue
        def c(p):
            m = net_of(sub, p); return f"{m['net']:+.3f}({m['wr']}%)"
        mfm = round(float(np.median([r["mfe"] for r in sub])), 2)
        slm = round(float(np.median([r["sl_pct"] for r in sub])), 2)
        L.append(f"| {D} | {len(sub)} | {c('tp1')} | **{c('hybrid')}** | {c('runner')} | {mfm} | {slm} |")
    L.append("\n## ИТОГ (все)\n| политика | n | net | WR |\n|---|---|---|---|")
    for p in POLICIES:
        m = net_of(allr, p)
        if m:
            flag = "🟢" if m["net"] > 0 else "🔴"
            L.append(f"| {p} | {m['n']} | **{m['net']:+.3f}** {flag} | {m['wr']}% |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
