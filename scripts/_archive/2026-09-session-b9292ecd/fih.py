# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import warnings; warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from research_harness import load, universe, COST_LIMIT

HOLD = 60
STOP_ATR = 3.0
WARMUP = 600


def _atr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def collect_symbol(sym, tf, step, max_bars):
    from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse
    df = load(sym, tf)
    if len(df) < 2000:
        return [], []
    if max_bars and len(df) > max_bars:
        df = df.iloc[-max_bars:]
    idx = df.index
    df = df.reset_index(drop=True)
    n = len(df)
    atr = _atr(df)
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values

    seen = {}
    order = []
    for t in range(WARMUP, n, step):
        try:
            imps = detect_elliott_impulse(zigzag_atr(df.iloc[:t]))
        except Exception:
            continue
        for i in imps:
            w = i["waves"]
            a, b = int(w[0][0]), int(w[-1][0])
            if b in seen or b >= t or b <= a:
                continue
            move = (w[-1][1] / w[0][1] - 1) * 100
            seen[b] = {"a": a, "b": b, "dir": i["direction"], "move": move}
            order.append((t, b, seen[b]))

    def _exit(entry_bar, long_, sl_):
        e = float(o[entry_bar])
        for j in range(entry_bar, min(entry_bar + HOLD, n)):
            if (l[j] <= sl_) if long_ else (h[j] >= sl_):
                return (sl_ - e) / e * 100 * (1 if long_ else -1) - COST_LIMIT
        x = float(c[min(entry_bar + HOLD, n - 1)])
        return (x - e) / e * 100 * (1 if long_ else -1) - COST_LIMIT

    fade_rows = []
    for t, b, f in order:
        entry_bar = t
        if entry_bar + HOLD >= n or not np.isfinite(atr[entry_bar]) or atr[entry_bar] <= 0:
            continue
        up = f["dir"] == "up"
        e = float(o[entry_bar])
        dd_ = 1.0 if up else -1.0
        sl_ = e + dd_ * STOP_ATR * atr[entry_bar]
        long_ = dd_ < 0
        side = "long" if long_ else "short"
        stop_pct = abs(sl_ - e) / e * 100
        pnl = _exit(entry_bar, long_, sl_)
        fade_rows.append({
            "sym": sym, "dir": f["dir"], "side": side,
            "year": int(pd.Timestamp(idx[entry_bar]).year),
            "stop_pct": stop_pct, "amp_pct": f["move"], "pnl": pnl,
        })

    rng = np.random.default_rng(abs(hash(sym)) % (2**32))
    ctrl_rows = []
    n_ctrl = len(fade_rows)
    if n_ctrl:
        cand = np.arange(WARMUP, n - HOLD - 1)
        picks = rng.choice(cand, size=min(n_ctrl, len(cand)), replace=False)
        sides = rng.integers(0, 2, size=len(picks))
        for bar, sflag in zip(picks, sides):
            if not np.isfinite(atr[bar]) or atr[bar] <= 0:
                continue
            long_ = bool(sflag)
            e = float(o[bar])
            sl_ = e - STOP_ATR * atr[bar] if long_ else e + STOP_ATR * atr[bar]
            pnl = _exit(bar, long_, sl_)
            ctrl_rows.append({
                "sym": sym, "side": "long" if long_ else "short",
                "year": int(pd.Timestamp(idx[bar]).year),
                "stop_pct": STOP_ATR * atr[bar] / e * 100, "pnl": pnl,
            })
    return fade_rows, ctrl_rows


def line(v, tag):
    if len(v) < 20:
        return f"  {tag:<28} n={len(v):<5} - malo"
    p = v.pnl.values
    s = np.sort(p)[::-1]
    w, gl = p[p > 0].sum(), -p[p <= 0].sum()
    pf = w / gl if gl else float("inf")
    bt = s[int(len(s) * 0.1):].sum()
    cov = (v.groupby("sym").pnl.sum() > 0).mean() * 100
    return (f"  {tag:<28} n={len(p):<5} WR{100*(p>0).mean():4.0f}% "
            f"MED{np.median(p):+6.2f}% avg{p.mean():+6.2f}% PF{pf:5.2f} "
            f"beztop10%{bt:+8.0f}% cov{cov:4.0f}%")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1h"
    n_sym = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    max_bars = int(sys.argv[4]) if len(sys.argv) > 4 else (14000 if tf == "1h" else 9000)

    syms = universe(tf, n=n_sym)
    print(f"universe {len(syms)} coins - {tf} - step {step} - window <= {max_bars} bars "
          f"- stop {STOP_ATR}xATR - hold {HOLD} bars")
    t0 = time.time()
    fade, ctrl = [], []
    for i, s in enumerate(syms, 1):
        try:
            f, c = collect_symbol(s, tf, step, max_bars)
            fade += f; ctrl += c
        except Exception as e:
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        print(f"  ... {i}/{len(syms)} - fade={len(fade)} - {time.time()-t0:.0f}s", flush=True)
    F = pd.DataFrame(fade); C = pd.DataFrame(ctrl)
    if F.empty:
        print("ZERO fade trades - refusal.")
        return
    print(f"\ncollected FADE {len(F)} - CONTROL {len(C)} - coins {F.sym.nunique()} - {time.time()-t0:.0f}s total\n")

    print("=" * 110)
    print(f"BASE FADE ({tf})")
    print("=" * 110)
    print(line(F, "ALL FADE"))
    print(line(F[F.dir == "up"], "  short vs up-impulse"))
    print(line(F[F.dir == "down"], "  long vs down-impulse"))
    print(line(C, "RANDOM ENTRY (control)"))

    print("\nBY YEAR:")
    for y in sorted(F.year.unique()):
        print(line(F[F.year == y], f"  {y}"))
    print("  -- short vs up by year --")
    for y in sorted(F.year.unique()):
        print(line(F[(F.year == y) & (F.dir == "up")], f"  {y}"))
    print("  -- long vs down by year --")
    for y in sorted(F.year.unique()):
        print(line(F[(F.year == y) & (F.dir == "down")], f"  {y}"))

    print("\nBY STOP SIZE:")
    for lo, hi in ((0, 2), (2, 4), (4, 8), (8, 100)):
        print(line(F[(F.stop_pct >= lo) & (F.stop_pct < hi)], f"  {lo}-{hi}%"))

    print("\nCONCENTRATION BY COIN (short vs up-impulse):")
    S = F[F.dir == "up"]
    per = S.groupby("sym").pnl.sum().sort_values(ascending=False)
    pos = per[per > 0]
    if len(pos):
        top3 = pos.head(3).sum()
        print(f"  positive coins: {len(pos)} of {per.shape[0]} - "
              f"top3 {list(pos.head(3).index)} give {top3/pos.sum()*100:.0f}% of total positive")
    print(f"  total coins in short-vs-up: {S.sym.nunique()}")

    print("\nCONCENTRATION BY COIN (long vs down-impulse):")
    S2 = F[F.dir == "down"]
    per2 = S2.groupby("sym").pnl.sum().sort_values(ascending=False)
    pos2 = per2[per2 > 0]
    if len(pos2):
        top3b = pos2.head(3).sum()
        print(f"  positive coins: {len(pos2)} of {per2.shape[0]} - "
              f"top3 {list(pos2.head(3).index)} give {top3b/pos2.sum()*100:.0f}% of total positive")

    F.to_parquet(str(ROOT / "cache" / f"_fade_impulse_htf_{tf}.parquet"))
    if not C.empty:
        C.to_parquet(str(ROOT / "cache" / f"_fade_impulse_htf_{tf}_ctrl.parquet"))
    print(f"\nsaved: cache/_fade_impulse_htf_{tf}.parquet (+_ctrl)")


if __name__ == "__main__":
    main()
