# -*- coding: utf-8 -*-
"""RE-MINE v2 — РЕАЛЬНЫЙ OTE-движок (ote_retest_setups) с КОНФЛЮЕНЦИЕЙ (OB/FVG в зоне).

v1 брал голое касание зоны → WR=ПОЛ. v2 использует живой движок (один калькулятор),
который даёт `confluence` = счёт OB+FVG той же стороны в OTE-зоне. Сплитуем по confluence:
0 (голо) vs 1 vs 2+ → видим, поднимают ли РЕАЛЬНЫЕ триггеры WR/net (ответ на «WR не радует»).
Вход = nested LTF (тугой SL), метрика net@3R (1:3, рабочая точка).
Запуск: python scripts/ote_remine_v2.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / f"{datetime.now(timezone.utc):%Y-%m-%d}--ote-remine-v2"
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
NEST = {"4h": ["15m", "5m"], "1h": ["15m", "5m"]}
BUF, SL_LB, FWD, ZONE_HTF, RT = 0.0015, 6, 240, 14, 0.10
TP = 3.0  # рабочая точка 1:3
MIN_N = 60


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _entry(dfl, d, lo, hi, a, e):
    win = dfl.loc[(dfl.index >= a) & (dfl.index <= e)]
    if len(win) < SL_LB + 2: return None
    for i in range(SL_LB, len(win)):
        b = win.iloc[i]
        if not (b["low"] <= hi and b["high"] >= lo): continue
        seg = win.iloc[i - SL_LB:i + 1]
        if d == "long":
            en = min(float(b["close"]), hi); sl = float(seg["low"].min()) * (1 - BUF)
            if en > sl: return en, sl, win.index[i]
        else:
            en = max(float(b["close"]), lo); sl = float(seg["high"].max()) * (1 + BUF)
            if sl > en: return en, sl, win.index[i]
    return None


def _mfe(dfl, d, en, sl, ts):
    fwd = dfl.loc[dfl.index > ts].head(FWD)
    if fwd.empty: return None
    one = abs(en - sl)
    if one <= 0: return None
    best = 0.0
    for h, l in zip(fwd["high"].values, fwd["low"].values):
        if d == "long":
            if l <= sl: break
            best = max(best, float(h) - en)
        else:
            if h >= sl: break
            best = max(best, en - float(l))
    return best / one


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0); a = ap.parse_args()
    from core.smc.smc_engine import ote_retest_setups
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='1h' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[v2] пар: {len(syms)}", flush=True)
    rows = []
    tmin = tmax = None
    for idx, sym in enumerate(syms):
        try:
            dfs = {tf: _load(conn, sym, tf) for tf in ("4h", "1h", "15m", "5m")}
            for htf, ltfs in NEST.items():
                dfh = dfs.get(htf)
                if dfh is None or len(dfh) < 120: continue
                setups = ote_retest_setups(dfh, only_choch=False)  # живой движок (как generate)
                span = pd.Timedelta(minutes=TF_MIN[htf] * ZONE_HTF)
                for s in setups:
                    d = s["direction"]; lo, hi = s["ote"]; confl = s.get("confluence", 0)
                    az = pd.Timestamp(s["choch_ts"])
                    for ltf in ltfs:
                        dfl = dfs.get(ltf)
                        if dfl is None: continue
                        ent = _entry(dfl, d, lo, hi, az, az + span)
                        if not ent: continue
                        en, sl, ets = ent
                        mr = _mfe(dfl, d, en, sl, ets)
                        if mr is None: continue
                        rows.append({"setup": f"{htf}->{ltf}", "dir": d, "confl": confl,
                                     "mfe_r": mr, "sl_pct": abs(en - sl) / en * 100})
                        if tmin is None or ets < tmin: tmin = ets
                        if tmax is None or ets > tmax: tmax = ets
        except Exception:
            pass
        if (idx + 1) % 50 == 0: print(f"[v2] {idx+1}/{len(syms)} | {len(rows)}", flush=True)
    conn.close()
    span_days = max(1, (tmax - tmin).days) if (tmin and tmax) else 365

    def netwr(sub):
        n = len(sub)
        if n == 0: return None
        w = sum(1 for r in sub if r["mfe_r"] >= TP); tot = 0
        for r in sub:
            fee = RT / r["sl_pct"] if r["sl_pct"] > 0 else .5
            tot += (TP - fee) if r["mfe_r"] >= TP else (-1 - fee)
        return round(100 * w / n), round(tot / n, 3), n, round(n / span_days * 7, 1)

    def cb(c): return "confl0(голо)" if c == 0 else "confl1" if c == 1 else "confl2+"
    base = netwr(rows)
    L = [f"# RE-MINE v2 — реальный движок ote_retest_setups + конфлюенция (net@{TP}R, комса {RT}%)\n",
         f"> {datetime.now(timezone.utc):%Y-%m-%d %H:%M} · {len(rows)} входов · {span_days}д\n",
         f"\n**BASELINE:** WR{base[0]}% net{base[1]:+.3f} n={base[2]} {base[3]}/нед\n",
         "\n## По КОНФЛЮЕНЦИИ (главный вопрос: триггеры поднимают WR/net?)\n",
         "| confluence | WR | net@3R | n | сиг/нед |", "|---|---|---|---|---|"]
    byc = defaultdict(list)
    for r in rows: byc[cb(r["confl"])].append(r)
    for k in ("confl0(голо)", "confl1", "confl2+"):
        v = byc.get(k, [])
        if len(v) >= MIN_N:
            m = netwr(v); L.append(f"| {k} | {m[0]}% | **{m[1]:+.3f}** | {m[2]} | {m[3]} |")
    # setup×dir при confluence>=1 (реальный вход)
    L.append("\n## setup×dir, ТОЛЬКО confluence≥1 (реальный триггер) net@3R\n")
    L.append("| сетап | WR | net@3R | n | сиг/нед |"); L.append("|---|---|---|---|---|")
    real = [r for r in rows if r["confl"] >= 1]
    byd = defaultdict(list)
    for r in real: byd[f"{r['setup']} {r['dir']}"].append(r)
    res = [(k, netwr(v)) for k, v in byd.items()]
    res = [(k, m) for k, m in res if m and m[2] >= MIN_N]
    res.sort(key=lambda x: x[1][1], reverse=True)
    for k, m in res:
        L.append(f"| {k} | {m[0]}% | **{m[1]:+.3f}** | {m[2]} | {m[3]} |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
