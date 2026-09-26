# -*- coding: utf-8 -*-
"""ГЛАВНЫЙ МАЙН (B) — OTE nested-pull на полной истории (Data Vision), честные метрики.

Идея (валидир. [[ote_nested_mtf_strategy]]): HTF-зона (4h/1h) задаёт OTE → LTF (1h/15m/5m) даёт
nested-вход внутри зоны → тугой SL за LTF-структуру (risk ×10) → forward-MFE = правда раннера.
Метрика = MFE в R (от ТУГОГО LTF-SL) + MFE %цены + хвост ≥2R/≥3R + ЧАСТОТА (сигналов/нед) =
обкатываемость. БД-R/exit НЕ используется (мерим потенциал входа, не сломанный выход).

Переиспользует ПРОД-детекторы (один калькулятор): smc_engine.zigzag_atr + find_setups_zz (OTE-зоны),
augment_snap.compute_augment_snap (ADX/n_down/elliott/fib).

Вывод: data/research/<date>--ote-remine/RESULTS.md + CSV.
Запуск: python scripts/ote_remine.py [--pairs N] [--htf 4h 1h]
"""
import argparse
import csv
import sqlite3
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402
import numpy as np   # noqa: E402

CACHE = ROOT / "ohlcv_cache.db"
OUT_DIR = ROOT / "data" / "research" / f"{datetime.now(timezone.utc):%Y-%m-%d}--ote-remine"

# nested: HTF-зона → допустимые LTF-входы (строго ниже)
NEST = {"4h": ["1h", "15m", "5m"], "1h": ["15m", "5m"]}
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
BUF = 0.0015          # буфер SL за структуру (0.15%)
SL_LOOKBACK = 6       # баров LTF назад для LTF-структурного SL
FWD_BARS = 240        # окно вперёд для MFE (раннер)
ZONE_ACTIVE_HTF = 14  # сколько HTF-баров зона «живая» для поиска входа
MIN_N = 40            # мин. сделок в бакете для вывода


def _load(conn, sym, tf):
    df = pd.read_sql_query(
        "SELECT time,open,high,low,close,volume FROM ohlcv_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time", conn, params=(sym, tf))
    if df.empty:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def _nested_entry(dfl, direction, lo, hi, act_ts, end_ts):
    """Первый LTF-бар в [act_ts, end_ts], зашедший в OTE-зону. → (entry, sl, entry_idx) | None."""
    win = dfl.loc[(dfl.index >= act_ts) & (dfl.index <= end_ts)]
    if len(win) < SL_LOOKBACK + 2:
        return None
    for i in range(SL_LOOKBACK, len(win)):
        bar = win.iloc[i]
        in_zone = bar["low"] <= hi and bar["high"] >= lo
        if not in_zone:
            continue
        seg = win.iloc[i - SL_LOOKBACK:i + 1]
        if direction == "long":
            entry = min(float(bar["close"]), hi)
            sl = float(seg["low"].min()) * (1 - BUF)
            if entry <= sl:
                continue
            return entry, sl, win.index[i]
        else:
            entry = max(float(bar["close"]), lo)
            sl = float(seg["high"].max()) * (1 + BUF)
            if sl <= entry:
                continue
            return entry, sl, win.index[i]
    return None


def _forward_mfe(dfl, direction, entry, sl, entry_ts):
    """MFE вперёд от входа СО СТОПОМ: walk bar-by-bar, если SL пробит первым → раннер обрывается.
    Консервативно интрабар (SL проверяется ПЕРВЫМ → нет lookahead). → (mfe_R, mfe_pct, sl_pct) | None."""
    fwd = dfl.loc[dfl.index > entry_ts].head(FWD_BARS)
    if fwd.empty:
        return None
    one_r = abs(entry - sl)
    if one_r <= 0:
        return None
    best = 0.0
    highs = fwd["high"].values
    lows = fwd["low"].values
    for h, l in zip(highs, lows):
        if direction == "long":
            if l <= sl:          # стоп выбит этим баром → обрыв (бар не засчитываем = консервативно)
                break
            fav = float(h) - entry
        else:
            if h >= sl:
                break
            fav = entry - float(l)
        if fav > best:
            best = fav
    best = max(best, 0.0)
    return best / one_r, best / entry * 100.0, one_r / entry * 100.0


def remine_pair(conn, sym):
    out = []
    dfs = {}
    for tf in ("4h", "1h", "15m", "5m"):
        d = _load(conn, sym, tf)
        if d is not None:
            dfs[tf] = d
    try:
        from core.smc.smc_engine import zigzag_atr, find_setups_zz
        from core.indicators.augment_snap import compute_augment_snap
    except Exception:
        return out
    for htf, ltfs in NEST.items():
        dfh = dfs.get(htf)
        if dfh is None or len(dfh) < 120:
            continue
        try:
            setups = find_setups_zz(zigzag_atr(dfh), dfh)
        except Exception:
            continue
        zone_span = pd.Timedelta(minutes=TF_MIN[htf] * ZONE_ACTIVE_HTF)
        for s in setups:
            direction = s.get("direction")
            ote = s.get("ote")
            act = s.get("choch_ts")
            if not ote or direction not in ("long", "short") or act is None:
                continue
            lo, hi = ote
            act_ts = pd.Timestamp(act) if not isinstance(act, pd.Timestamp) else act
            end_ts = act_ts + zone_span
            for ltf in ltfs:
                dfl = dfs.get(ltf)
                if dfl is None:
                    continue
                ent = _nested_entry(dfl, direction, lo, hi, act_ts, end_ts)
                if not ent:
                    continue
                entry, sl, ets = ent
                mfe = _forward_mfe(dfl, direction, entry, sl, ets)
                if not mfe:
                    continue
                mfe_r, mfe_pct, sl_pct = mfe
                aug = {}
                try:
                    aug = compute_augment_snap(dfl.loc[dfl.index <= ets].tail(220))
                except Exception:
                    pass
                el = aug.get("elliott") or {}
                out.append({
                    "sym": sym, "setup": f"{htf}->{ltf}", "dir": direction,
                    "ts": ets.isoformat(), "mfe_r": round(mfe_r, 3),
                    "mfe_pct": round(mfe_pct, 3), "sl_pct": round(sl_pct, 3),
                    "adx": aug.get("adx"), "rsi": aug.get("rsi"),
                    "n_up": aug.get("n_up"), "n_down": aug.get("n_down"),
                    "ell_textbook": el.get("textbook"), "ell_scale": el.get("scale"),
                    "in_ote": aug.get("in_ote"),
                })
    return out


def _agg(rows, span_days):
    """rows(list dict) → метрики по бакету."""
    n = len(rows)
    if n == 0:
        return None
    mr = [r["mfe_r"] for r in rows]
    mp = [r["mfe_pct"] for r in rows]
    return {
        "n": n, "sig_wk": round(n / max(span_days, 1) * 7, 1),
        "mfe_pct": round(sum(mp) / n, 2),
        "p1": round(100 * sum(1 for r in mr if r >= 1) / n),
        "p2": round(100 * sum(1 for r in mr if r >= 2) / n),
        "p3": round(100 * sum(1 for r in mr if r >= 3) / n),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=0, help="лимит пар (0=все)")
    args = ap.parse_args()

    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='1h' ORDER BY symbol")]
    if args.pairs:
        syms = syms[:args.pairs]
    print(f"[remine] пар: {len(syms)}", flush=True)

    allrows = []
    tmin = tmax = None
    for i, sym in enumerate(syms):
        try:
            rr = remine_pair(conn, sym)
            allrows.extend(rr)
            for r in rr:
                t = pd.Timestamp(r["ts"])
                tmin = t if tmin is None or t < tmin else tmin
                tmax = t if tmax is None or t > tmax else tmax
        except Exception:
            print(f"[remine] ERR {sym}: {traceback.format_exc()[:200]}", flush=True)
        if (i + 1) % 50 == 0:
            print(f"[remine] {i+1}/{len(syms)} | сделок {len(allrows)}", flush=True)
    conn.close()

    span_days = max(1, (tmax - tmin).days) if (tmin and tmax) else 365
    print(f"[remine] всего сделок: {len(allrows)} | окно {span_days} дн", flush=True)

    # baseline + измерения
    base = _agg(allrows, span_days)
    DIMS = {
        "setup×dir": lambda r: f"{r['setup']} {r['dir']}",
        "ADX<25 (pull)": lambda r: ("ADX<25" if (r["adx"] is not None and r["adx"] < 25) else "ADX>=25") if r["adx"] is not None else None,
        "n_down(SHORT)": lambda r: (f"n_down={r['n_down']}" if r["dir"] == "short" and r["n_down"] is not None and r["n_down"] <= 5 else None),
        "n_up(LONG)": lambda r: (f"n_up={r['n_up']}" if r["dir"] == "long" and r["n_up"] is not None and r["n_up"] <= 5 else None),
        "elliott_textbook": lambda r: (None if r["ell_textbook"] is None else f"textbook={int(bool(r['ell_textbook']))}"),
        "in_ote(augment)": lambda r: (None if r["in_ote"] is None else f"in_ote={int(bool(r['in_ote']))}"),
        "sl_tightness": lambda r: ("SL<0.5%" if r["sl_pct"] < 0.5 else "SL0.5-1%" if r["sl_pct"] < 1 else "SL>1%"),
    }

    lines = [f"# OTE RE-MINE (B) — nested-pull на полной истории Data Vision\n",
             f"> {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · сделок {len(allrows)} · окно {span_days} дн · "
             f"метрика MFE-R (от ТУГОГО LTF-SL) + хвост + частота\n",
             f"\n**BASELINE:** n={base['n']} · {base['sig_wk']}/нед · MFE% {base['mfe_pct']} · "
             f"≥1R {base['p1']}% · ≥2R {base['p2']}% · ≥3R {base['p3']}%\n",
             "\n> Ищем: высокий хвост ≥3R × высокая частота (обкатываемость). MFE-R = от тугого LTF-SL (nested risk×10).\n"]
    for name, fn in DIMS.items():
        buckets = defaultdict(list)
        for r in allrows:
            k = fn(r)
            if k is not None:
                buckets[k].append(r)
        res = [(k, _agg(v, span_days)) for k, v in buckets.items()]
        res = [(k, m) for k, m in res if m and m["n"] >= MIN_N]
        res.sort(key=lambda x: x[1]["p3"], reverse=True)
        if not res:
            continue
        lines.append(f"\n## {name}\n")
        lines.append("| бакет | n | сиг/нед | MFE% | ≥1R | ≥2R | ≥3R | хвост vs base |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for k, m in res:
            lift = m["p3"] - base["p3"]
            flag = "🟢" if lift >= 3 else "🔴" if lift <= -3 else ""
            lines.append(f"| {k} | {m['n']} | {m['sig_wk']} | {m['mfe_pct']} | {m['p1']}% | {m['p2']}% | {m['p3']}% | {lift:+d}pp {flag} |")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    if allrows:
        with open(OUT_DIR / "signals.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(allrows[0].keys()))
            w.writeheader(); w.writerows(allrows)
    print("\n".join(lines))
    print(f"\n→ {OUT_DIR/'RESULTS.md'}")


if __name__ == "__main__":
    main()
