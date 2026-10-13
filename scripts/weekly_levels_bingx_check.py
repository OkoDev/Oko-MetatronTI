# -*- coding: utf-8 -*-
"""НЕДЕЛЬНЫЕ УРОВНИ: BingX ПРОТИВ Binance НА ВСЕЙ ИСТОРИИ (09.10.2026, «НЕ проверено» из weekly_hypo_lab).

Бэктест гипотез мерился на Binance (G:/oko_lab/tf), бой — на BingX; сверка шла только на 12 общих неделях (94%).
Здесь:
  1. уровни P/R1/S1/R2/S2, режим (наклон P) и зона открытия по ДНЕВКАМ обеих бирж, 2022-08 → 2026-09:
     расхождение уровней в % и доля недель, где совпали режим / зона / правило;
  2. исходы гипотез по ЧАСОВИКАМ обеих бирж (BingX 1h есть с 2025-09): совпадение статуса и доля «цель раньше».
Зона здесь — по ОТКРЫТИЮ понедельничной дневки (одинаково для обеих бирж), а не по первой 15m-цене, как в бою.
Запуск: python scripts/weekly_levels_bingx_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
    pass
from weekly_hypo_lab import RULES, _zone, outcome  # noqa: E402
from core.infra.market_store import read_bars       # noqa: E402

BN = Path("G:/oko_lab/tf")
BX = Path("C:/oko_data/market/bingx")


def weekly(d: pd.DataFrame) -> pd.DataFrame:
    per = d.index.to_period("W-SUN")
    g = d.groupby(per).agg(O=("open", "first"), H=("high", "max"), L=("low", "min"), C=("close", "last"),
                           n=("close", "size"))
    g = g.reindex(pd.period_range(g.index.min(), g.index.max(), freq="W-SUN"))
    P = (g.H + g.L + g.C) / 3
    rng = g.H - g.L
    lv = pd.DataFrame({"P": P, "R1": 2 * P - g.L, "S1": 2 * P - g.H, "R2": P + rng, "S2": P - rng}).shift(1)
    lv["P_prev"] = lv.P.shift(1)
    lv["O"] = g.O
    ok = (g.n == 7) & (g.n.shift(1) == 7) & (g.n.shift(2) == 7) & (lv.S2 > 0)
    lv = lv[ok].copy()
    lv["regime"] = np.where(lv.P > lv.P_prev, "BULL", "BEAR")
    lv["zone"] = [_zone(o, p, r1, s1) for o, p, r1, s1 in zip(lv.O, lv.P, lv.R1, lv.S1)]
    lv["code"] = [RULES.get((r, z), ("—",))[0] for r, z in zip(lv.regime, lv.zone)]
    return lv


def touches(d1h: pd.DataFrame, lv: pd.DataFrame) -> pd.DataFrame:
    """Первое касание R1/R2/S1/S2 по хай/лой 1h внутри недели (минуты от начала недели)."""
    per = d1h.index.to_period("W-SUN")
    keep = per.isin(lv.index)
    b, bp = d1h[keep], per[keep]
    mins = ((b.index - bp.start_time).total_seconds() // 60).astype(int)
    L = lv.loc[bp]
    out = {}
    for name in ("R1", "R2", "S1", "S2"):
        hit = (b.high.to_numpy() >= L[name].to_numpy()) if name[0] == "R" else (b.low.to_numpy() <= L[name].to_numpy())
        out[f"t_{name}_hl"] = pd.Series(np.where(hit, mins, np.inf), index=bp).groupby(level=0).min().replace(np.inf, np.nan)
    full = pd.Series(1, index=bp).groupby(level=0).size()
    T = pd.DataFrame(out)
    return T[full.reindex(T.index) >= 160]                       # неделя часовиков почти полная


def main():
    rows, outs = [], []
    syms = sorted(p.name for p in (BX / "1d").iterdir() if p.is_dir())
    for base in syms:
        f = BN / "1d" / f"{base}USDT.parquet"
        if not f.exists():
            continue
        try:
            bx = read_bars(base, "1d")
        except Exception:
            continue
        bn = pd.read_parquet(f)
        if len(bx) < 60 or len(bn) < 60:
            continue
        bx.index = bx.index.tz_localize(None) if bx.index.tz is not None else bx.index
        A, B = weekly(bn), weekly(bx)
        J = A.join(B, how="inner", lsuffix="_bn", rsuffix="_bx")
        if J.empty:
            continue
        J["sym"] = base
        rows.append(J)
        # исходы по часовикам — где у BingX есть 1h
        try:
            h_bx = read_bars(base, "1h")
        except Exception:
            continue
        fh = BN / "1h" / f"{base}USDT.parquet"
        if len(h_bx) < 24 * 30 or not fh.exists():
            continue
        h_bx.index = h_bx.index.tz_localize(None) if h_bx.index.tz is not None else h_bx.index
        h_bn = pd.read_parquet(fh)
        h_bn = h_bn[h_bn.index >= h_bx.index.min()]
        for ex, h, lv in (("bn", h_bn, A), ("bx", h_bx, B)):
            T = touches(h, lv).join(lv[["regime", "zone", "code", "R1", "R2", "S1", "S2", "O"]], how="inner")
            T["sym"], T["ex"] = base, ex
            T = T.rename(columns={"O": "open"})
            outs.append(T)
    W = pd.concat(rows)
    W["year"] = W.index.start_time.year
    print("═" * 100)
    print(f"УРОВНИ: монет {W.sym.nunique()} · монето-недель {len(W)} · {W.index.min().start_time:%Y-%m-%d} → {W.index.max().start_time:%Y-%m-%d}")
    for L in ("P", "R1", "S1", "R2", "S2"):
        d = (W[f"{L}_bx"] / W[f"{L}_bn"] - 1).abs() * 100
        print(f"  |{L} BingX − Binance|: медиана {d.median():.3f}% · p90 {d.quantile(.9):.3f}% · p99 {d.quantile(.99):.2f}% · >1%: {(d > 1).mean()*100:.1f}% недель")
    agree = pd.DataFrame({"режим": W.regime_bn == W.regime_bx, "зона": W.zone_bn == W.zone_bx, "правило": W.code_bn == W.code_bx})
    print("  совпадение по годам, %:")
    print((agree.groupby(W.year).mean() * 100).round(1).to_string())
    print(f"  всего: режим {agree['режим'].mean()*100:.1f}% · зона {agree['зона'].mean()*100:.1f}% · правило {agree['правило'].mean()*100:.1f}%")

    O = pd.concat(outs)
    O["week"] = O.index
    print("\n" + "═" * 100)
    print(f"ИСХОДЫ по часовикам (BingX 1h с {O[O.ex == 'bx'].week.min().start_time:%Y-%m-%d}): монето-недель {len(O) // 2}")
    for (reg, zone), (code, side, tg, st, inv) in RULES.items():
        res = {}
        for ex in ("bn", "bx"):
            X = O[(O.ex == ex) & (O.code == code)].copy()
            X["res"] = outcome(X, tg, inv, "hl").replace({"AMBIG": "INVALID"})
            res[ex] = X.set_index(["sym", "week"]).res
        both = pd.concat(res, axis=1, join="inner").dropna()
        dec = {ex: both[ex][both[ex].isin(["TARGET", "INVALID"])] for ex in ("bn", "bx")}
        print(f"  {code:15} общих {len(both):>5} · статус совпал {(both.bn == both.bx).mean()*100:5.1f}% · "
              f"цель раньше: Binance {(dec['bn'] == 'TARGET').mean()*100:5.1f}% · BingX {(dec['bx'] == 'TARGET').mean()*100:5.1f}%")


if __name__ == "__main__":
    main()
