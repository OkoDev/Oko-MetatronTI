# -*- coding: utf-8 -*-
"""БАЗА (без фильтров) — метод пользователя: слом 15m → фиба OTE → вход → выход на ПРОТИВОПОЛОЖНОМ CHoCH.

Спека (Егор 21.06): WT/ADX/conf — ПОТОМ. Сначала голая база, обе стороны:
  1. Слом структуры 15m (find_setups_zz) → импульс → OTE-зона (0.5-0.79).
  2. ВХОД = первый ретест в OTE после слома (цена вернулась в зону).
  3. SL = 1.0 фибы (начало импульса = инвалидация структуры) + буфер. РЕАЛИСТИЧНЫЙ (не крошечный).
  4. ВЫХОД = ПРОТИВОПОЛОЖНЫЙ CHoCH (структура сломалась против → раннер до смены тренда).
     Если SL пробит РАНЬШЕ → выход −1R. Без lookahead (walk bar-by-bar).
Метрика: net R (комиссия), WR, распределение R (хвост), по направлению + эре.
Запуск: python scripts/ote_base_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--ote-base"
BUF = 0.0015          # буфер SL за структуру
RETEST_BARS = 60      # окно ретеста в OTE после слома (15m баров)
RT = 0.10             # комиссия round-trip %
MAXHOLD = 480         # макс удержание (15m баров = 5 сут) если CHoCH не пришёл


def _load(conn, sym):
    df = pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='15m' ORDER BY time",
                           conn, params=(sym,))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def test_pair(conn, sym):
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    df = _load(conn, sym)
    if df is None or len(df) < 200: return []
    setups = find_setups_zz(zigzag_atr(df), df)
    if len(setups) < 2: return []
    # 1h WT для фильтра-сплита (asof: последний 1h бар <= вход)
    wt1_1h = None
    df1 = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' ORDER BY time", conn, params=(sym,))
    if not df1.empty:
        df1.index = pd.to_datetime(df1["time"], unit="ms", utc=True)
        try:
            from core.indicators.indicators import calculate_wt
            d1w = calculate_wt(df1)
            d1w.index = pd.to_datetime(df1["time"].values, unit="ms", utc=True)  # calc_wt сбрасывает индекс
            wt1_1h = d1w["wt1"].sort_index()
        except Exception:
            wt1_1h = None
    # 15m WT-дивергенции (combinator эталон _wtx_divergences) для фильтра
    div_bull = div_bear = None
    try:
        import numpy as _np
        from core.indicators.indicators import calculate_wt
        from core.calculators.combinator_core import _wtx_divergences
        _wt = calculate_wt(df.copy())["wt1"].values
        _br, _ber, _bh, _beh = _wtx_divergences(_wt, df["low"].values, df["high"].values)
        div_bull = _np.asarray(_br, bool) | _np.asarray(_bh, bool)   # bull regular|hidden
        div_bear = _np.asarray(_ber, bool) | _np.asarray(_beh, bool)
    except Exception:
        div_bull = div_bear = None
    # позиции CHoCH по времени (для выхода на противоположном)
    pos = {ts: i for i, ts in enumerate(df.index)}
    hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    n = len(df)
    out = []
    for si, s in enumerate(setups):
        d = s["direction"]; ote_lo, ote_hi = s["ote"]
        ci = pos.get(s["choch_ts"])
        if ci is None: continue
        sl = s["levels"][1.0]  # начало импульса = инвалидация
        # ВХОД: первый ретест в OTE после слома
        ei = None
        for j in range(ci + 1, min(ci + 1 + RETEST_BARS, n)):
            if lo[j] <= ote_hi and hi[j] >= ote_lo:
                ei = j; break
        if ei is None: continue
        entry = (ote_lo + ote_hi) / 2.0
        slv = sl * (1 - BUF) if d == "long" else sl * (1 + BUF)
        risk = abs(entry - slv)
        if risk <= 0: continue
        # ВЫХОД: противоположный CHoCH после входа (или SL раньше)
        opp = "short" if d == "long" else "long"
        exit_ts_idx = None
        for s2 in setups[si + 1:]:
            if s2["direction"] == opp:
                xi = pos.get(s2["choch_ts"])
                if xi is not None and xi > ei:
                    exit_ts_idx = xi; break
        x_end = exit_ts_idx if exit_ts_idx is not None else min(ei + MAXHOLD, n - 1)
        # walk: SL раньше выхода?
        exit_price = None; sl_hit = False
        for k in range(ei, x_end + 1):
            if d == "long":
                if lo[k] <= slv: exit_price = slv; sl_hit = True; break
            else:
                if hi[k] >= slv: exit_price = slv; sl_hit = True; break
        if exit_price is None:
            exit_price = cl[x_end]      # вышли на CHoCH (или maxhold)
        R = ((exit_price - entry) if d == "long" else (entry - exit_price)) / risk
        fee = RT / (risk / entry * 100) if risk > 0 else 0.5  # комиссия в R
        w1h = None
        if wt1_1h is not None:
            try:
                v = wt1_1h.asof(df.index[ei])
                if pd.notna(v):
                    w1h = float(v)
            except Exception:
                pass
        has_div = None
        if div_bull is not None:
            w0 = max(0, ei - 10)
            arr = div_bull if d == "long" else div_bear
            has_div = bool(arr[w0:ei + 1].any())
        out.append({"sym": sym, "dir": d, "R": R, "net": R - fee,
                    "sl_pct": round(risk / entry * 100, 3), "sl_hit": sl_hit,
                    "ts": df.index[ei], "exit_choch": exit_ts_idx is not None,
                    "wt1_1h": w1h, "div": has_div})
    return out


def agg(rows):
    n = len(rows)
    if n == 0: return None
    nets = [r["net"] for r in rows]
    wins = sum(1 for r in rows if r["net"] > 0)
    return {"n": n, "net_avg": round(sum(nets) / n, 3), "wr": round(100 * wins / n),
            "sumR": round(sum(nets), 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0); a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[base] пар: {len(syms)}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[base] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    b = agg(allr)
    L = [f"# БАЗА (без фильтров): слом15m → фиба OTE → выход на CHoCH — {len(allr)} сделок\n",
         f"> выход=противоположный CHoCH (раннер) / SL раньше. комиссия {RT}%. реалистичный структурный SL.\n",
         f"\n**ИТОГ:** net_avg **{b['net_avg']:+.3f}R** · WR {b['wr']}% · n={b['n']} · sumR {b['sumR']:+.1f}\n"]
    # по направлению
    L.append("\n## по направлению\n| dir | n | net_avg | WR | sumR |\n|---|---|---|---|---|")
    for d in ("long", "short"):
        m = agg([r for r in allr if r["dir"] == d])
        if m: L.append(f"| {d} | {m['n']} | **{m['net_avg']:+.3f}** | {m['wr']}% | {m['sumR']:+.1f} |")
    # распределение R (хвост)
    L.append("\n## распределение net R\n| бакет | доля |\n|---|---|")
    import numpy as np
    nets = np.array([r["net"] for r in allr])
    for lab, lo, hi in [("≤−1R", -99, -1), ("−1..0", -1, 0), ("0..1", 0, 1), ("1..2", 1, 2), ("2..3", 2, 3), ("3..5", 3, 5), (">5R", 5, 99)]:
        d = round(100 * ((nets > lo) & (nets <= hi)).sum() / max(len(nets), 1))
        L.append(f"| {lab} | {d}% |")
    # выход: choch vs sl vs maxhold
    sl_hit = sum(1 for r in allr if r["sl_hit"]); choch = sum(1 for r in allr if r["exit_choch"] and not r["sl_hit"])
    L.append(f"\n## выход: SL {round(100*sl_hit/max(len(allr),1))}% · CHoCH-раннер {round(100*choch/max(len(allr),1))}% · прочее {round(100*(len(allr)-sl_hit-choch)/max(len(allr),1))}%\n")
    # эра (post/pre 2025)
    L.append("## по эре\n| период | n | net_avg | WR |\n|---|---|---|---|")
    for lab, cut in [("2022-2024", "2024-12-31"), ("2025+", "2025-01-01")]:
        sub = [r for r in allr if (str(r["ts"]) < cut) == (lab == "2022-2024")]
        m = agg(sub)
        if m: L.append(f"| {lab} | {m['n']} | {m['net_avg']:+.3f} | {m['wr']}% |")
    # WT 1h фильтр-сплит (Егор: long лучше из OS, short из OB; div может убрать зону)
    L.append("\n## ФИЛЬТР WT 1h на входе (OS<−53 / OB>+53)\n| состояние | n | net_avg | WR | sumR |\n|---|---|---|---|---|")
    def wtstate(r):
        w = r.get("wt1_1h")
        if w is None: return None
        if r["dir"] == "long":
            return "long+OS✓" if w <= -53 else "long+OB✗" if w >= 53 else "long+mid"
        return "short+OB✓" if w >= 53 else "short+OS✗" if w <= -53 else "short+mid"
    bywt = defaultdict(list)
    for r in allr:
        k = wtstate(r)
        if k: bywt[k].append(r)
    for k in sorted(bywt):
        m = agg(bywt[k])
        if m and m["n"] >= 30:
            L.append(f"| {k} | {m['n']} | **{m['net_avg']:+.3f}** | {m['wr']}% | {m['sumR']:+.1f} |")
    # ДИВЕРГЕНЦИЯ на входе (доки: лучший сигнал; юзер рисует линии на WT)
    L.append("\n## ФИЛЬТР ДИВЕРГЕНЦИЯ 15m на входе (WT regular|hidden, окно 10 баров)\n| состояние | n | net_avg | WR | sumR |\n|---|---|---|---|---|")
    for d in ("long", "short"):
        for dv, lab in [(True, "+div✓"), (False, "no-div")]:
            m = agg([r for r in allr if r["dir"] == d and r.get("div") == dv])
            if m and m["n"] >= 30:
                L.append(f"| {d} {lab} | {m['n']} | **{m['net_avg']:+.3f}** | {m['wr']}% | {m['sumR']:+.1f} |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
