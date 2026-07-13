# -*- coding: utf-8 -*-
"""ВЫХОД для РАЗВОРОТА — кандидат reversal-CHoCH+conf≥3 слаб (+0.046) из-за раннер-выхода.

Гипотеза (truth-state): разворот ≠ продолжение. Раннер до противоположного CHoCH сливает прибыль.
Разворот надо закрывать по measured-target. Сравниваем ПОЛИТИКИ ВЫХОДА на ОДНОЙ когорте входов:
  - runner   = противоположный CHoCH (текущий, baseline +0.046)
  - TP@kR    = фикс тейк на k×risk (k = 1.0 / 1.5 / 2.0 / 3.0), SL=импульс-1.0
  - be_trail = после +1R двинуть SL в BE, далее до отдачи BE / window
Плюс MFE-распределение: как далеко реально едут (потолок выхода).
SL = импульс-1.0 (структурный, РЕАЛИСТИЧНЫЙ — не тугой, без R-инфляции). Без lookahead (walk bar-by-bar).
Когорта: CHoCH (reversal) + conf≥3, раздельно short/long. BOS для контраста.
Запуск: python scripts/ote_reversal_exit_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--ote-reversal-exit"
BUF, RETEST, MAXHOLD, RT = 0.0015, 60, 480, 0.10
TPS = [1.0, 1.5, 2.0, 3.0]   # тестируемые фикс-тейки в R


def _load(conn, sym):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='15m' ORDER BY time",
                           conn, params=(sym,))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _conf_count(imp, ote_lo, ote_hi, want, detF, detOB, detSB, detSC, detEQ):
    """Число подтверждений в OTE из окна импульса (как live _collect_triggers)."""
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


def _exits(d, entry, slv, ei, x_end, lo, hi, cl):
    """Считает net R для всех политик выхода + MFE. Один проход bar-by-bar (без lookahead)."""
    risk = abs(entry - slv)
    fee = RT / (risk / entry * 100)
    res = {}
    # --- фикс TP@kR + SL ---
    for k in TPS:
        tp = entry - k * risk if d == "short" else entry + k * risk
        outR = None
        for j in range(ei, x_end + 1):
            hit_sl = (hi[j] >= slv) if d == "short" else (lo[j] <= slv)
            hit_tp = (lo[j] <= tp) if d == "short" else (hi[j] >= tp)
            if hit_sl and hit_tp:   # обе в одном баре — консервативно SL первым
                outR = -1.0; break
            if hit_sl: outR = -1.0; break
            if hit_tp: outR = k; break
        if outR is None:   # не дошли — закрытие по окну
            outR = ((entry - cl[x_end]) if d == "short" else (cl[x_end] - entry)) / risk
        res[f"TP{k}"] = outR - fee
    # --- BE+trail: после +1R SL→entry ---
    be = False; outR = None
    for j in range(ei, x_end + 1):
        fav = ((entry - lo[j]) if d == "short" else (hi[j] - entry)) / risk
        sl_now = entry if be else slv
        hit_sl = (hi[j] >= sl_now) if d == "short" else (lo[j] <= sl_now)
        if hit_sl:
            outR = 0.0 if be else -1.0; break
        if not be and fav >= 1.0: be = True
    if outR is None:
        outR = ((entry - cl[x_end]) if d == "short" else (cl[x_end] - entry)) / risk
    res["be_trail"] = outR - fee
    # --- MFE (потолок), стоп при SL ---
    mfe = 0.0
    for j in range(ei, x_end + 1):
        fav = ((entry - lo[j]) if d == "short" else (hi[j] - entry)) / risk
        mfe = max(mfe, fav)
        hit_sl = (hi[j] >= slv) if d == "short" else (lo[j] <= slv)
        if hit_sl: break
    res["_mfe"] = mfe
    return res, fee


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
        ei = None
        for j in range(ci + 1, min(ci + 1 + RETEST, n)):
            if lo[j] <= ote_hi and hi[j] >= ote_lo: ei = j; break
        if ei is None: continue
        try: imp = df.loc[s["from"][0]:s["choch_ts"]]
        except Exception: imp = df.iloc[max(0, ci - 30):ci + 1]
        conf = _conf_count(imp, ote_lo, ote_hi, want, detect_fvg, detect_order_blocks, detect_structure_breaks, detect_sponsored_candle, detect_equal_levels)
        if ei >= 1 and ((d == "long" and wt1[ei] > wt1[ei - 1]) or (d == "short" and wt1[ei] < wt1[ei - 1])): conf += 1
        w0 = max(0, ei - 10)
        if (d == "long" and dbull[w0:ei + 1].any()) or (d == "short" and dbear[w0:ei + 1].any()): conf += 1
        entry = (ote_lo + ote_hi) / 2.0
        slv = s["levels"][1.0] * (1 - BUF) if d == "long" else s["levels"][1.0] * (1 + BUF)
        if abs(entry - slv) <= 0: continue
        # окно: до противоположного CHoCH (runner-baseline) / maxhold
        opp = "short" if d == "long" else "long"
        xi = None
        for s2 in setups[si + 1:]:
            if s2["direction"] == opp:
                j = pos.get(s2["choch_ts"])
                if j is not None and j > ei: xi = j; break
        x_end = xi if xi is not None else min(ei + MAXHOLD, n - 1)
        # runner-baseline (как ote_confluence)
        risk = abs(entry - slv); fee = RT / (risk / entry * 100)
        rex = None
        for k in range(ei, x_end + 1):
            if (d == "long" and lo[k] <= slv) or (d == "short" and hi[k] >= slv): rex = slv; break
        if rex is None: rex = cl[x_end]
        runner = ((rex - entry) if d == "long" else (entry - rex)) / risk - fee
        ex, _ = _exits(d, entry, slv, ei, x_end, lo, hi, cl)
        ex["runner"] = runner
        ex["dir"] = d; ex["mode"] = kind; ex["conf"] = conf
        ex["ts"] = df.index[ei]
        out.append(ex)
    return out


def agg(rows, key):
    vals = [r[key] for r in rows if key in r]
    n = len(vals)
    if not n: return None
    return {"n": n, "net": round(sum(vals) / n, 3), "wr": round(100 * sum(1 for x in vals if x > 0) / n), "sumR": round(sum(vals), 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0); a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[rev-exit] пар: {len(syms)}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[rev-exit] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    policies = ["runner"] + [f"TP{k}" for k in TPS] + ["be_trail"]
    L = [f"# ВЫХОД для РАЗВОРОТА — reversal-CHoCH+conf≥3 (когорта входов фикс) — {len(allr)} сделок\n",
         f"> SL=импульс-1.0 (реалистичный). комса {RT}%. сравнение политик выхода на ОДНИХ входах.\n"]
    for mode in ("CHoCH", "BOS"):
        for d in ("short", "long"):
            coh = [r for r in allr if r["mode"] == mode and r["dir"] == d and r["conf"] >= 3]
            if len(coh) < 30: continue
            L.append(f"\n## {mode} {d} conf≥3 (n={len(coh)})\n| политика | net E[R] | WR | sumR |\n|---|---|---|---|")
            for p in policies:
                m = agg(coh, p)
                if m:
                    flag = "🟢" if m["net"] > 0 else "🔴"
                    L.append(f"| {p} | **{m['net']:+.3f}** {flag} | {m['wr']}% | {m['sumR']:+.1f} |")
            # MFE распределение
            mfe = np.array([r["_mfe"] for r in coh])
            L.append(f"\nMFE (потолок): med {np.median(mfe):.2f}R · ≥1R {round(100*(mfe>=1).mean())}% · ≥2R {round(100*(mfe>=2).mean())}% · ≥3R {round(100*(mfe>=3).mean())}%\n")
            # era-split TP1.0 (держится ли в post-2025?)
            L.append("era-split (TP1.0 / runner):")
            for lab, cut, before in [("2022-2024", "2025-01-01", True), ("2025+", "2025-01-01", False)]:
                sub = [r for r in coh if (str(r["ts"]) < cut) == before]
                m1 = agg(sub, "TP1.0"); mr = agg(sub, "runner")
                if m1: L.append(f"  {lab}: TP1 **{m1['net']:+.3f}** (WR{m1['wr']}% n{m1['n']}) · runner {mr['net']:+.3f}")
            L.append("")
    # п.1: TP1.0 × conf-уровень (нужен ли фильтр conf, или рычаг чисто в выходе?)
    L.append("\n## 🎯 TP@1R × conf-уровень (ВСЕ режимы/направления) — нужен ли фильтр conf?\n| conf | n | TP1.0 net | WR | runner net |\n|---|---|---|---|---|")
    for c in range(0, 7):
        sub = [r for r in allr if (r["conf"] == c if c < 6 else r["conf"] >= 6)]
        m1 = agg(sub, "TP1.0"); mr = agg(sub, "runner")
        if m1 and m1["n"] >= 30:
            lab = str(c) if c < 6 else "6+"
            flag = "🟢" if m1["net"] > 0 else "🔴"
            L.append(f"| {lab} | {m1['n']} | **{m1['net']:+.3f}** {flag} | {m1['wr']}% | {mr['net']:+.3f} |")
    # TP@1R по режиму×conf-порогу (conf≥0 vs ≥2 vs ≥3) — заточить спеку
    L.append("\n## TP@1R по режиму × conf-порогу\n| режим | dir | conf≥0 | conf≥2 | conf≥3 |\n|---|---|---|---|---|")
    for mode in ("CHoCH", "BOS"):
        for d in ("short", "long"):
            cells = []
            for thr in (0, 2, 3):
                m = agg([r for r in allr if r["mode"] == mode and r["dir"] == d and r["conf"] >= thr], "TP1.0")
                cells.append(f"{m['net']:+.3f}(n{m['n']})" if m else "—")
            L.append(f"| {mode} | {d} | {cells[0]} | {cells[1]} | {cells[2]} |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
