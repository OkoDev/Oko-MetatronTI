# -*- coding: utf-8 -*-
"""НОГИ ДВУХ СТЕПЕНЕЙ НА СДЕЛКАХ ЯДРА ВОЛН (Егор 08.10: «измерить! я пока не понимаю плюсов для поиска боевых»).

Вопрос. Разделяют ли деньги боевой механики (ядро волн) два контекста, которые теперь есть в журнале:
  · СТАРШАЯ нога — где закончилась пятая в дневной ноге, которую корректирует импульс (канон OTE, 5 корзин);
  · МЛАДШАЯ (текущая) нога на входе — пробита (цена за её началом, глубина > 1) или цела.
Если разделяют — это уточнение доказанной клетки (фильтр / размер / момент входа). Если нет — ноги остаются экраном.

Объект замера (протокол §0.1): контекстный фильтр на потоке L0 механики. Зафиксировано конфигурацией
`wave_entry_delay_lab` (rows_v2): вход по триггеру 15m на open, стоп за пятой, цель — конец волны 4, удержание
240 ч (L2/L3), кост 0.35 (L4). НЕ представлено: портфель (L5), исполнение VST. Вторично: чистый форвард 24/72 ч
из журнала на баре входа (L1).

Паспорт полей (§0A.1):
  pnl_0     — rows_v2, `wave_entry_delay_lab._walk`: % со знаком сделки (LONG: рост = плюс) МИНУС 0.35
  side      — rows_v2 «side»: сторона СДЕЛКИ (`wave5_core`: "SHORT" if up else "LONG" → после пятёрки вниз — LONG)
  w_leg_depth5 / w_leg_band — журнал `_degree_legs`: |p5 − ext| / |origin − ext| дневной ноги, которую корректирует
              импульс, один раз в момент первой видимости пятёрки; 0 — пятая у конца ноги, 1 — у её начала
  legup_depth / legdn_depth — журнал `_leg_block`: текущая нога (как шина), глубина цены часа; > 1 — нога пробита.
              Для LONG своя нога — вверх (откат вниз), для SHORT — вниз.
Гипотезы (до прогона), 7 на популяцию × 3 популяции = 21: OTE · глубокая · за пределами · мелкая(<0.62) ·
младшая пробита · OTE∧младшая цела · OTE∧младшая пробита.

Запуск: python scripts/wave_degree_legs_lab.py
"""
from __future__ import annotations

import pickle
import sys
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
JOURNAL = Path("G:/oko_lab/joint/1h")
COLS = ["w_side", "w_age_h", "w_leg_depth5", "w_leg_band", "legup_depth", "legdn_depth", "fwd_24", "fwd_72",
        "liq", "mkt_drift30", "atr_pct"]
REG = {2023: "БЫК", 2024: "нейтраль", 2025: "МЕДВЕДЬ", 2026: "МЕДВЕДЬ"}
STUDY = "wave-degree-legs-2026-10-08"


def attach() -> pd.DataFrame:
    R = pd.DataFrame(pickle.load(open(SRC, "rb")))
    n0 = len(R)
    R["E"] = pd.to_datetime(R.entry_time)
    R["ts"] = (R.E - pd.Timedelta("1h")).dt.floor("h")          # последний ЗАКРЫТЫЙ час к входу
    parts = []
    for sym, g in R.groupby("sym"):
        f = JOURNAL / f"{sym.replace('/', '')}.parquet"
        if not f.exists():
            parts.append(g.assign(**{c: np.nan for c in COLS}))
            continue
        J = pd.read_parquet(f, columns=COLS)
        J.index = pd.to_datetime(J.index)
        parts.append(g.join(J, on="ts"))
    D = pd.concat(parts).sort_index()
    assert len(D) == n0, f"после склейки {len(D)} строк против {n0} — ключ неполный"          # §0A.3
    # та же ли пятёрка в журнале, что у сделки: сторона и время вершины (журнал хранит возраст от вершины)
    top_j = D.ts + pd.Timedelta("1h") - pd.to_timedelta(D.w_age_h, unit="h")
    top_r = pd.to_datetime(D.top_time)
    D["same_five"] = ((D.w_side == np.where(D.side == "LONG", 1.0, -1.0))
                      & ((top_j - top_r).abs() <= pd.Timedelta("1min")))
    return D


def golden() -> None:
    """§0A.2: глубина и метки — вручную. SKR 08.10 (разбор): нога 0.006217→0.034797, пятая 0.016041 → 0.656, OTE."""
    from core.smc.fibonacci import ote_band_code
    o, e, p5 = 0.006217, 0.034797, 0.016041
    d = abs(p5 - e) / abs(o - e)
    assert abs(d - 0.6563) < 1e-3 and ote_band_code(d) == 2
    assert ote_band_code(0.3) == 0 and ote_band_code(0.9) == 3 and ote_band_code(1.2) == 4
    # младшая пробита: цена за началом ноги → глубина > 1
    assert abs(0.016152 - 0.026583) / abs(0.017006 - 0.026583) > 1


def main() -> int:
    golden()
    D = attach()
    D["year"] = D.E.dt.year
    print("=" * 104)
    print(f"ИНВЕНТАРИЗАЦИЯ: сделок {len(D)} · монет {D.sym.nunique()} · {D.E.min():%Y-%m-%d} → {D.E.max():%Y-%m-%d}")
    print(pd.crosstab(D.year, D.side).to_string())
    print(f"режим (монеты выборки, 4h, посчитан 07.10 в wt_context_for_waves): {REG}")
    m_ok = D.same_five
    print(f"журнал видит ТУ ЖЕ пятёрку на баре входа: {m_ok.mean() * 100:.1f}% · нога старшей степени найдена: "
          f"{D.w_leg_band.notna().mean() * 100:.1f}% · текущая нога: {D.legup_depth.notna().mean() * 100:.1f}%")
    print(D[["sym", "side", "entry_time", "top_time", "w_side", "w_leg_depth5", "legup_depth", "legdn_depth",
             "stop_pct", "pnl_0"]].head(4).to_string(index=False))

    # калибровка §0A.4: клетка лонга (полное ядро ∧ стоп ≥6%) — 170 сд., PF 2.79, +4.56%
    cell_all = (D.side == "LONG") & D.core_full & (D.stop_pct >= 6.0)
    v = D.pnl_0[cell_all]
    pf = v[v > 0].sum() / -v[v < 0].sum()
    print(f"\nКАЛИБРОВКА клетки лонга: n={len(v)} PF {pf:.2f} средн {v.mean():+.2f}% (память: 170 · 2.79 · +4.56)")
    assert len(v) == 170 and abs(pf - 2.79) < 0.02

    # только сделки, где журнал видит ту же пятёрку и обе ноги посчитаны
    U = D[m_ok & D.w_leg_band.notna()].copy()
    U["own_leg"] = np.where(U.side == "LONG", U.legup_depth, U.legdn_depth)
    U["low_broken"] = U.own_leg > 1.0
    print(f"\nв замер: {len(U)} из {len(D)} (та же пятёрка + нога найдена)")
    pops = [("ВСЕ ЛОНГИ", U[U.side == "LONG"]), ("КЛЕТКА ЛОНГА", U[(U.side == "LONG") & U.core_full & (U.stop_pct >= 6)]),
            ("ВСЕ ШОРТЫ", U[U.side == "SHORT"])]
    cards, nulls = [], []
    for pn, P in pops:
        P = P.reset_index(drop=True)
        side = set(P.side)
        assert side <= {"LONG"} or side <= {"SHORT"}, f"{pn}: смешаны стороны {side}"                  # §0A.3
        print("\n" + "=" * 104)
        print(f"{pn}: n={len(P)}")
        print("=" * 104)
        band = P.w_leg_band.values
        print("  корзина старшей ноги (где закончилась пятая) — деньги механики · чистый форвард 24 ч / 72 ч:")
        for b, nm in ((0, "мелкая <0.5"), (1, "0.5–0.62"), (2, "OTE 0.62–0.79"), (3, "глубокая 0.79–1.0"),
                      (4, "за пределами >1")):
            g = P[band == b]
            if len(g) == 0:
                continue
            sg = np.where(g.side == "LONG", 1.0, -1.0)
            print(f"    {nm:<18} n={len(g):>5} · средн {g.pnl_0.mean():+6.2f}% · медиана {g.pnl_0.median():+6.2f}% · "
                  f"в плюс {(g.pnl_0 > 0).mean() * 100:4.0f}% · ф24 {np.nanmean(sg * g.fwd_24) - 0.35:+5.2f}% · "
                  f"ф72 {np.nanmean(sg * g.fwd_72) - 0.35:+5.2f}%")
            if len(g) < 10:
                print(g[["sym", "entry_time", "w_leg_depth5", "own_leg", "stop_pct", "pnl_0"]].to_string(index=False))
        lb = P.low_broken.values
        print(f"  младшая нога пробита: {lb.mean() * 100:.0f}% сделок · пробита {P.pnl_0[lb].mean():+.2f}% (n={lb.sum()}) · "
              f"цела {P.pnl_0[~lb].mean():+.2f}% (n={(~lb).sum()})")

        D2 = V.normalize(P, pnl="pnl_0", ts="E", liq="liq")
        masks = [("OTE старшей", band == 2), ("глубокая старшей", band == 3), ("за пределами старшей", band == 4),
                 ("мелкая старшей (<0.62)", band <= 1), ("младшая пробита", lb),
                 ("OTE ∧ младшая цела", (band == 2) & ~lb), ("OTE ∧ младшая пробита", (band == 2) & lb)]
        masks = [(k, m) for k, m in masks if m.sum() >= 10 and (~m).sum() >= 10]

        def search(p, masks=masks):
            return max(((k, p[m].mean() - p[~m].mean()) for k, m in masks), key=lambda x: x[1])

        nulls.append(V.search_null(D2, search, name=f"{pn}: {len(masks)} гипотез ног", study=STUDY))
        for k, m in masks:
            c = V.card(D2, m, name=f"{pn} × {k}", study=STUDY, geo=("stop_pct",), regimes=REG, quiet=True)
            cards.append(c)
            flag = "✅" if c["passed"] else "❌"
            print(f"  {flag} {k:<26} n={c['n']:>5} · средн {c['mean']:+6.2f}% · Δ к остальным {c['delta']:+6.2f} · "
                  f"P {c['p']:.3f} · не прошло: {', '.join(c.get('failed', [])) or '—'}")
    V.save_md(cards + [dict(text=n["text"]) for n in nulls],
              ROOT / "obsidian/Research/2026-10-08-Wave-Degree-Legs.md",
              "Ноги двух степеней на сделках ядра волн",
              "Старшая нога (где закончилась пятая) и младшая (пробита/цела) против денег ядра волн, 2023-26")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
