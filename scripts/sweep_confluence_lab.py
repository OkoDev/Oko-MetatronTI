# -*- coding: utf-8 -*-
"""НАБОР НА СВИПЕ: совместная работа ордерблоков, свипа ликвидности, пивотов, ATR и WT на баре ВХОДА (Егор 08.10, NEAR:
«ты смотришь на то, что сейчас, а не на то, что было до! главнее — что было и почему могли войти» → «2-3 да»).
Принцип 27.08 ([[feedback_confluence_not_moment]]): конфлюэнция = НАБОР условий одновременно, а не момент-триггер.

ЗАДАНО ДО ПРОГОНА:
  · СОБЫТИЕ 1h (причинные флаги журнала общего состояния + OHLC бара из кэша):
      SHORT — снятие ликвидности СВЕРХУ (`liq_sweep_up_1h` | `eqh_sweep_1h`) и ОТКАЗ: close в нижней половине бара;
      LONG  — снятие СНИЗУ (`liq_sweep_dn_1h` | `eql_sweep_1h`) и close в верхней половине. Одно событие в сутки на монету
      и сторону. (Флаг сам по себе = хай прошёл зону — это и свип, и пробой; отказ отделяет свип.)
  · УСЛОВИЯ С ПРАВИЛЬНОЙ СТОРОНОЙ (1h или 4h с закрытого бара):
      OB  — SHORT: bear_ob_near · LONG: bull_ob_near
      PIV — SHORT: pivot_near_R1/R2/R3 на 1D/1W/1M · LONG: pivot_near_S1/S2/S3
      WT  — SHORT: wt_ob или wt_div_bear_regular · LONG: wt_os или wt_div_bull_regular
      ATR — SHORT: atr_cross_down_1h или atr_down_4h · LONG: atr_cross_up_1h или atr_up_4h
    счёт 0–4; кандидат — ≥3; корзины 0/1/2/3/4 и вклад каждого условия отдельно.
  · ИСХОД, кост 0.35: fwd_24 по стороне; стоп/цель 4/8 ATR 72 ч (geo_wide) и 1.5/3 ATR (geo_tight).
  · Сравнение — те же события с меньшим счётом и обычный час (`ctrl`); 2023 → 2026-10-06.

Запуск: python scripts/sweep_confluence_lab.py [процессов]
"""
from __future__ import annotations

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402

JOURNAL = Path("G:/oko_lab/joint/1h")
OUT = Path("G:/oko_lab/out/sweep_confluence.pkl")
COST, COOL_H = 0.35, 24
TF4 = "__from_4h"


def _any(J, cols):
    cols = [c for c in cols if c in J.columns]
    return J[cols].fillna(0).astype(float).max(axis=1).values > 0.5 if cols else np.zeros(len(J), bool)


def conditions(J: pd.DataFrame, side: str) -> dict:
    s = side == "SHORT"
    piv = [f"pivot_near_{lv}_{tf}" for lv in (("R1", "R2", "R3") if s else ("S1", "S2", "S3")) for tf in ("1D", "1W", "1M")]
    return {
        "OB": _any(J, [f"{'bear' if s else 'bull'}_ob_near_1h", f"{'bear' if s else 'bull'}_ob_near_4h{TF4}"]),
        "PIV": _any(J, piv),
        "WT": _any(J, [f"wt_{'ob' if s else 'os'}_1h", f"wt_{'ob' if s else 'os'}_4h{TF4}",
                       f"wt_div_{'bear' if s else 'bull'}_regular_1h", f"wt_div_{'bear' if s else 'bull'}_regular_4h{TF4}"]),
        "ATR": _any(J, [f"atr_cross_{'down' if s else 'up'}_1h", f"atr_{'down' if s else 'up'}_4h{TF4}"]),
    }


def per_coin(f: Path):
    import logging
    logging.disable(logging.CRITICAL)
    from research_harness import load
    J = pd.read_parquet(f)
    J.index = J.index.tz_convert(None) if J.index.tz is not None else J.index
    sym = str(J.sym.iloc[0]) if "sym" in J.columns and len(J) else f.stem
    try:
        d = load(sym, "1h")
    except Exception:                                    # noqa: BLE001
        return []
    if d is None or d.empty:
        return []
    d.index = d.index.tz_convert(None) if d.index.tz is not None else d.index
    J = J.join(d[["open", "high", "low"]], how="inner")
    if J.empty:
        return []
    rng = (J.high - J.low).replace(0, np.nan)
    pos = ((J.close - J.low) / rng).values                # 0 — закрылся у лоя, 1 — у хая
    out = []
    for side in ("SHORT", "LONG"):
        s = side == "SHORT"
        ev = _any(J, ["liq_sweep_up_1h", "eqh_sweep_1h"] if s else ["liq_sweep_dn_1h", "eql_sweep_1h"])
        ev &= (pos <= 0.5) if s else (pos >= 0.5)
        C = conditions(J, side)
        last = None
        for i in np.flatnonzero(ev):
            t = J.index[i]
            if last is not None and t - last < pd.Timedelta(hours=COOL_H):
                continue
            last = t
            sg = -1.0 if s else 1.0
            r = J.iloc[i]
            out.append({"sym": sym, "ts": t, "side": side, "pos": round(float(pos[i]), 3),
                        **{k: bool(v[i]) for k, v in C.items()},
                        "fwd_24": sg * float(r.fwd_24) - COST if pd.notna(r.fwd_24) else np.nan,
                        "geo_wide": float(r[f"geo_wide_{side.lower()}"]) - COST if pd.notna(r.get(f"geo_wide_{side.lower()}")) else np.nan,
                        "geo_tight": float(r[f"geo_tight_{side.lower()}"]) - COST if pd.notna(r.get(f"geo_tight_{side.lower()}")) else np.nan,
                        "liq": float(r.liq) if "liq" in J.columns and pd.notna(r.liq) else np.nan,
                        "drift": float(r.mkt_drift30) if "mkt_drift30" in J.columns and pd.notna(r.mkt_drift30) else np.nan})
    return out


def conditions_4h(J: pd.DataFrame, side: str) -> dict:
    """Гипотеза №2 (после провала часового свипа — 79 531 событие, мелочь): только старшие уровни."""
    s = side == "SHORT"
    piv = [f"pivot_near_{lv}_{tf}" for lv in (("R1", "R2", "R3") if s else ("S1", "S2", "S3")) for tf in ("1W", "1M")]
    return {
        "OB": _any(J, [f"{'bear' if s else 'bull'}_ob_near_4h{TF4}"]),
        "PIV": _any(J, piv),
        "WT": _any(J, [f"wt_{'ob' if s else 'os'}_4h{TF4}", f"wt_div_{'bear' if s else 'bull'}_regular_4h{TF4}"]),
        "ATR": _any(J, [f"atr_cross_{'down' if s else 'up'}_1h", f"atr_cross_{'down' if s else 'up'}_4h{TF4}"]),
    }


def per_coin_4h(f: Path):
    """Событие — первый час после ЗАКРЫТОГО 4h-бара, который снял ликвидность на 4h и закрылся в нижней (шорт) /
    верхней (лонг) половине своего диапазона. Флаги __from_4h уже сдвинуты на закрытый бар; OHLC 4h — из 1h кэша."""
    import logging
    logging.disable(logging.CRITICAL)
    from research_harness import load
    J = pd.read_parquet(f)
    J.index = J.index.tz_convert(None) if J.index.tz is not None else J.index
    sym = str(J.sym.iloc[0]) if "sym" in J.columns and len(J) else f.stem
    try:
        d = load(sym, "1h")
    except Exception:                                    # noqa: BLE001
        return []
    if d is None or d.empty:
        return []
    d.index = d.index.tz_convert(None) if d.index.tz is not None else d.index
    d4 = d.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    # последний закрытый 4h-бар для часа h (бар h закрывается в h+1ч): открыт в floor(h+1ч, 4ч) − 4ч
    k4 = (J.index + pd.Timedelta("1h")).floor("4h") - pd.Timedelta("4h")
    B = d4.reindex(k4)
    rng = (B.high - B.low).replace(0, np.nan).values
    pos4 = (B.close.values - B.low.values) / rng
    out = []
    for side in ("SHORT", "LONG"):
        s = side == "SHORT"
        flag = _any(J, [f"liq_sweep_up_4h{TF4}", f"eqh_sweep_4h{TF4}"] if s else [f"liq_sweep_dn_4h{TF4}", f"eql_sweep_4h{TF4}"])
        ev = flag & ~np.r_[False, flag[:-1]]                # первый час, когда флаг закрытого 4h-бара загорелся
        ev &= (pos4 <= 0.5) if s else (pos4 >= 0.5)
        C = conditions_4h(J, side)
        last = None
        for i in np.flatnonzero(ev):
            t = J.index[i]
            if last is not None and t - last < pd.Timedelta(hours=COOL_H):
                continue
            last = t
            sg = -1.0 if s else 1.0
            r = J.iloc[i]
            out.append({"sym": sym, "ts": t, "side": side, "pos": round(float(pos4[i]), 3),
                        **{k: bool(v[i]) for k, v in C.items()},
                        "fwd_24": sg * float(r.fwd_24) - COST if pd.notna(r.fwd_24) else np.nan,
                        "geo_wide": float(r[f"geo_wide_{side.lower()}"]) - COST if pd.notna(r.get(f"geo_wide_{side.lower()}")) else np.nan,
                        "geo_tight": float(r[f"geo_tight_{side.lower()}"]) - COST if pd.notna(r.get(f"geo_tight_{side.lower()}")) else np.nan,
                        "liq": float(r.liq) if "liq" in J.columns and pd.notna(r.liq) else np.nan,
                        "drift": float(r.mkt_drift30) if "mkt_drift30" in J.columns and pd.notna(r.mkt_drift30) else np.nan})
    return out


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    mode = sys.argv[2] if len(sys.argv) > 2 else "1h"
    out = OUT if mode == "1h" else OUT.with_name("sweep_confluence_4h.pkl")
    if out.exists():
        E = pd.read_pickle(out)
    else:
        fn = per_coin if mode == "1h" else per_coin_4h
        with Pool(procs) as pool:
            rows = [r for rr in pool.imap_unordered(fn, sorted(JOURNAL.glob("*.parquet"))) for r in rr]
        E = pd.DataFrame(rows)
        E.to_pickle(out)
    print(f"режим события: {'свип 1h' if mode == '1h' else 'свип закрытого 4h-бара (гипотеза №2)'}")
    E["score"] = E[["OB", "PIV", "WT", "ATR"]].sum(axis=1)
    E["y"] = pd.to_datetime(E.ts).dt.year
    # §0A.3: сторона в выборке именно та, по которой считали исход
    assert set(E.side) == {"SHORT", "LONG"}
    print(f"событий свипа с отказом: {len(E)} · монет {E.sym.nunique()} · {E.ts.min()} → {E.ts.max()} · по сторонам {E.side.value_counts().to_dict()}")
    print(E.sort_values("ts").tail(3)[["sym", "ts", "side", "pos", "OB", "PIV", "WT", "ATR", "fwd_24", "geo_wide"]].round(2).to_string(index=False))
    C = pd.read_parquet(Path("G:/oko_lab/joint/events/ctrl.parquet"))
    for side, F in E.groupby("side"):
        cs = -1.0 if side == "SHORT" else 1.0
        base24 = float((cs * C.fwd_24 - COST).mean())
        basegw = float((C[f"geo_wide_{side.lower()}"] - COST).mean())
        print(f"\n{side}: событий {len(F)} · обычный час: 24ч {base24:+.2f} · 4/8 ATR {basegw:+.2f}")
        print(f"  {'счёт':<6}{'n':>6}{'дней':>6}{'24ч':>8}{'мед':>7}{'4/8 ATR':>9}{'мед':>7}{'1.5/3':>8}{'в плюсе 4/8':>13}   по годам 4/8 ATR")
        for k, g in F.groupby("score"):
            yy = " ".join(f"{y} {v:+.2f}({n})" for (y, v), n in zip(g.groupby("y").geo_wide.mean().items(), g.groupby("y").size()))
            print(f"  {k:<6}{len(g):>6}{g.ts.dt.floor('D').nunique():>6}{g.fwd_24.mean():>+8.2f}{g.fwd_24.median():>+7.2f}"
                  f"{g.geo_wide.mean():>+9.2f}{g.geo_wide.median():>+7.2f}{g.geo_tight.mean():>+8.2f}{(g.geo_wide > 0).mean() * 100:>12.0f}%   {yy}")
        print("  вклад каждого условия (4/8 ATR, есть / нет):",
              " · ".join(f"{c} {F[F[c]].geo_wide.mean():+.2f}/{F[~F[c]].geo_wide.mean():+.2f}" for c in ("OB", "PIV", "WT", "ATR")))
    for side in ("SHORT", "LONG"):
        F = E[E.side == side].reset_index(drop=True)
        for unit in ("geo_wide", "fwd_24"):
            G = F[np.isfinite(F[unit].values)].reset_index(drop=True)
            D = V.normalize(G.assign(pnl=G[unit]), pnl="pnl", ts="ts", liq="liq")
            V.card(D, (G.score >= 3).values, name=f"свип {mode} {side} × набор ≥3 из 4 ({unit})", study="sweep-confluence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
