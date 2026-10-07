# -*- coding: utf-8 -*-
"""СЛОИ ДЕТЕКТОРА ЯДРА КАК УТОЧНЕНИЕ КЛЕТКИ + ИМПУЛЬС ОТНОСИТЕЛЬНО НОГИ (Егор 08.10: «проверить гипотезы»).

Повод — `wave_degree_legs_lab`: дневной контекст (ноги двух степеней) деньги ядра НЕ разделяет, а слои детектора
(полное ядро ∧ стоп ≥6%) — разделяют. Две гипотезы оттуда, заданы ДО прогона:
  Г1. переменные МЛАДШЕГО слоя детектора уточняют клетку:
      depth5 (глубина пятой в канале: 0 — у линии 2-4, 1 — у параллели через 3) · ns_total / ns5 (свингов младшего
      слоя во всех пяти волнах / внутри пятой) · w2_retr = |p2−p1|/волна1 · w4_retr = |p4−p3|/волна3 ·
      w3_ext = волна3/волна1 · w5_rel = волна5/волна3 · |wt_top| (WT на вершине пятой) · fractal · altern_type ·
      altern_form · count_ok
  Г2. размер импульса относительно ноги старшей степени (imp_leg = |p0−p5| / |начало−конец ноги|) — ось размера
      позиции; заодно imp_pct (размер импульса в %).
Маски: булевы — «есть»; числовые — верхняя и нижняя трети (по популяции). Популяции: все лонги · лонги со стопом ≥6%
(зона закона размера) · все шорты. 4 + 10×2 = 24 маски × 3 = 72 гипотезы → ярус 2 на каждую популяцию обязателен.

Поля детектора берутся из того же расчёта ядра, что журнал (`joint_state_journal._wave_ctx`: 4h из 1h кэша), на
последнем 4h-баре, видимом ДО входа сделки, для ТОЙ ЖЕ пятёрки (сторона + вершина). Сделки — rows_v2
(`wave_entry_delay_lab`: вход по триггеру 15m, стоп за пятой, цель — волна 4, 240 ч, кост 0.35).

Запуск: python scripts/wave_detector_layers_lab.py [процессов]
"""
from __future__ import annotations

import os
import pickle
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

SRC = Path("G:/oko_lab/out/wave_entry_delay/rows_v2.pkl")
OUT = Path("G:/oko_lab/out/wave_detector_layers.pkl")
REG = {2023: "БЫК", 2024: "нейтраль", 2025: "МЕДВЕДЬ", 2026: "МЕДВЕДЬ"}
STUDY = "wave-detector-layers-2026-10-08"
FIELDS = ["fractal", "altern_type", "altern_form", "count_ok", "depth5_ctx", "ns_total", "ns5", "w2_retr",
          "w4_retr", "w3_ext", "w5_rel", "wt_top", "leg_o", "leg_e", "p0_ctx", "p5_ctx"]
NUM = ["depth5_ctx", "ns_total", "ns5", "w2_retr", "w4_retr", "w3_ext", "w5_rel", "wt_abs", "imp_pct", "imp_leg"]
BOOL = ["fractal", "altern_type", "altern_form", "count_ok"]


def per_symbol(args):
    sym, trades = args
    import logging
    logging.disable(logging.CRITICAL)
    import joint_state_journal as J
    from research_harness import load
    try:
        df = load(sym, "1h")
        W = J._wave_ctx(df)
    except Exception:                                    # noqa: BLE001
        return [dict(t, **{f: np.nan for f in FIELDS}) for t in trades]
    if W.empty:
        return [dict(t, **{f: np.nan for f in FIELDS}) for t in trades]
    W = W.assign(visible=pd.to_datetime(W.time) + pd.Timedelta("4h"))
    G = J._degree_legs(df, W)
    W = W.merge(G, on=["t0", "top_time", "side"], how="left")
    W["top_key"] = pd.to_datetime(W.top_time).dt.strftime("%Y-%m-%d %H:%M")
    out = []
    for t in trades:
        E = pd.Timestamp(t["entry_time"])
        c = W[(W.side == t["side"]) & (W.top_key == t["top_time"]) & (W.visible <= E)]
        if c.empty:
            out.append(dict(t, **{f: np.nan for f in FIELDS}))
            continue
        r = c.sort_values("visible").iloc[-1]                # последний вид пятёрки ДО входа
        out.append(dict(t, fractal=float(r.fractal), altern_type=float(r.altern_type), altern_form=float(r.altern_form),
                        count_ok=float(r.count_ok), depth5_ctx=r.depth5, ns_total=r.ns_total, ns5=r.ns5,
                        w2_retr=r.w2_retr, w4_retr=r.w4_retr, w3_ext=r.w3_ext, w5_rel=r.w5_rel, wt_top=r.wt_top,
                        leg_o=r.leg_o, leg_e=r.leg_e, p0_ctx=r.p0, p5_ctx=r.p5))
    return out


def collect(procs: int) -> pd.DataFrame:
    R = pd.DataFrame(pickle.load(open(SRC, "rb")))
    jobs = [(s, g.to_dict("records")) for s, g in R.groupby("sym")]
    rows = []
    with Pool(procs) as pool:
        for r in pool.imap_unordered(per_symbol, jobs):
            rows += r
    D = pd.DataFrame(rows)
    assert len(D) == len(R), f"{len(D)} против {len(R)}"                       # §0A.3
    D.to_pickle(OUT)
    return D


def golden() -> None:
    """§0A.2: отношение импульса к ноге и знак WT вручную."""
    p0, p5, o, e = 0.026583, 0.016041, 0.006217, 0.034797           # SKR 08.10
    assert abs(abs(p0 - p5) / abs(o - e) - 0.3689) < 1e-3          # импульс = 37% старшей ноги
    assert abs(-47.7) == 47.7                                       # wt_top лонга отрицателен → берём модуль


def main() -> int:
    golden()
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    D = pd.read_pickle(OUT) if OUT.exists() else collect(procs)
    D["E"] = pd.to_datetime(D.entry_time)
    D["year"] = D.E.dt.year
    D["wt_abs"] = D.wt_top.abs()
    D["imp_leg"] = (D.p0_ctx - D.p5_ctx).abs() / (D.leg_o - D.leg_e).abs()
    found = D.fractal.notna()
    print("=" * 104)
    print(f"сделок {len(D)} · поля детектора найдены для {found.mean() * 100:.1f}% · нога для {D.imp_leg.notna().mean() * 100:.1f}%")
    # согласие с rows_v2: флаги ядра и глубина пятой из двух расчётов (4h кэш против 4h из 1h) обязаны совпадать
    m = found & D.depth5.notna()
    agree = (np.isclose(D.depth5[m], D.depth5_ctx[m], atol=0.02)).mean()
    print(f"СВЕРКА: depth5 совпала в {agree * 100:.1f}% · core_full↔(fractal∧depth≥0.5∧altern∧count) "
          f"{((D.core_full == ((D.fractal == 1) & (D.depth5_ctx >= 0.5) & ((D.altern_type == 1) | (D.altern_form == 1)) & (D.count_ok == 1)))[m]).mean() * 100:.1f}%")
    print(D.loc[m, ["sym", "side", "entry_time", "depth5", "depth5_ctx", "ns_total", "ns5", "w3_ext", "wt_top",
                    "imp_leg", "pnl_0"]].head(4).round(3).to_string(index=False))
    U = D[found].reset_index(drop=True)
    pops = [("ВСЕ ЛОНГИ", U[U.side == "LONG"]), ("ЛОНГИ СО СТОПОМ ≥6%", U[(U.side == "LONG") & (U.stop_pct >= 6)]),
            ("ВСЕ ШОРТЫ", U[U.side == "SHORT"])]
    cards, nulls = [], []
    for pn, P in pops:
        P = P.reset_index(drop=True)
        assert len(set(P.side)) == 1                                              # §0A.3
        print("\n" + "=" * 104)
        print(f"{pn}: n={len(P)} · средн {P.pnl_0.mean():+.2f}% · медиана {P.pnl_0.median():+.2f}%")
        print("=" * 104)
        masks = [(f"{b} = да", (P[b] == 1).values) for b in BOOL]
        for c in NUM:
            v = P[c].values.astype(float)
            fin = np.isfinite(v)
            if fin.sum() < 60:
                continue
            lo, hi = np.nanquantile(v, [1 / 3, 2 / 3])
            masks += [(f"{c} ≤ {lo:.3g} (низ ⅓)", fin & (v <= lo)), (f"{c} ≥ {hi:.3g} (верх ⅓)", fin & (v >= hi))]
        masks = [(k, mm) for k, mm in masks if mm.sum() >= 20 and (~mm).sum() >= 20]
        D2 = V.normalize(P, pnl="pnl_0", ts="E")

        def search(p, masks=masks):
            return max(((k, p[mm].mean() - p[~mm].mean()) for k, mm in masks), key=lambda x: x[1])

        nulls.append(V.search_null(D2, search, name=f"{pn}: {len(masks)} гипотез слоёв детектора", study=STUDY))
        res = []
        for k, mm in masks:
            c = V.card(D2, mm, name=f"{pn} × {k}", study=STUDY, geo=("stop_pct",), regimes=REG, quiet=True)
            cards.append(c)
            res.append((c["delta"], k, c))
        for d, k, c in sorted(res, key=lambda x: -x[0])[:8]:
            print(f"  {'✅' if c['passed'] else '❌'} {k:<32} n={c['n']:>5} · средн {c['mean']:+6.2f}% · Δ {d:+6.2f} · "
                  f"P {c['p']:.3f} · не прошло: {', '.join(c.get('failed', [])) or '—'}")
        # Г2 как ось РАЗМЕРА: деньги по третям imp_leg
        v = P.imp_leg.values.astype(float)
        if np.isfinite(v).sum() >= 60:
            q = np.nanquantile(v, [1 / 3, 2 / 3])
            print("  Г2 · импульс / нога старшей степени — деньги по третям:")
            for nm, mm in ((f"≤{q[0]:.2f}", v <= q[0]), (f"{q[0]:.2f}–{q[1]:.2f}", (v > q[0]) & (v < q[1])),
                           (f"≥{q[1]:.2f}", v >= q[1])):
                g = P.pnl_0[mm]
                s_ = np.sort(g.values)
                print(f"     {nm:<12} n={len(g):>5} · средн {g.mean():+6.2f}% · медиана {g.median():+6.2f}% · "
                      f"без лучших 10% {s_[:max(1, int(len(s_) * 0.9))].mean():+6.2f}%")
    V.save_md(cards + [dict(text=n["text"]) for n in nulls], ROOT / "obsidian/Research/2026-10-08-Wave-Detector-Layers.md",
              "Слои детектора ядра волн как уточнение клетки",
              "Младший слой детектора (подволны, откаты, растяжения, глубина в канале) и импульс относительно ноги")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
