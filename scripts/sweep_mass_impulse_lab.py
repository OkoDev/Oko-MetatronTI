# -*- coding: utf-8 -*-
"""НАБОР НА СВИПЕ, этаж 2: массовость и импульс ПЕРЕД свипом (Егор 08.10: «вариант для карточки — (б)»).
События — из `sweep_confluence_lab.py` (кэш G:/oko_lab/out/sweep_confluence*.pkl, кост 0.35 уже вычтен).

ЗАДАНО ДО ПРОГОНА:
  · МАССОВОСТЬ m6 — сколько ДРУГИХ монет дали свип ТОЙ ЖЕ стороны в окне (t−6ч, t] (тот же закрытый бар включён — он
    известен всем одновременно; сама монета исключена). Вселенная U — монет с любым событием за 30 дней до дня события
    (причинно). Доля share = m6 / U · 100.
  · ИМПУЛЬС imp24/imp72 — ход цены В СТОРОНУ свипа за 24/72 ч до бара события: SHORT = рост к хаю, LONG = падение к лою;
    плюс = был импульс. Цена — close бара события и close 24/72 ч раньше (оба известны на входе).
  · КАНДИДАТЫ (верхняя треть внутри стороны и ТФ): H1 массовый свип · H2 сильный импульс · H3 лонг × бычий OB × массовый.
    Деньги — geo_wide (стоп/цель 4/8 ATR, 72ч); fwd_24 — проверка устойчивости. Ярус 2 — сетка терций m×imp.
  · Противоположный хвост (нижняя треть) печатается в таблице, но гипотезой не считается.

Запуск: python scripts/sweep_mass_impulse_lab.py [процессов]
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

SRC = {"1h": Path("G:/oko_lab/out/sweep_confluence.pkl"), "4h": Path("G:/oko_lab/out/sweep_confluence_4h.pkl")}
OUT = Path("G:/oko_lab/out/sweep_mass_impulse.pkl")
MASS_H, UNIV_D = 6, 30


def mass_counts(E: pd.DataFrame) -> np.ndarray:
    """m6: другие монеты, та же сторона, окно (t−6ч, t]. Внутри монеты события одной стороны разнесены ≥24ч,
    поэтому в окне из своей монеты только само событие."""
    out = np.zeros(len(E), int)
    for _, g in E.groupby("side"):
        t = g.ts.values.astype("datetime64[ns]")
        o = np.argsort(t, kind="stable")
        ts = t[o]
        r = np.searchsorted(ts, ts, side="right")
        l = np.searchsorted(ts, ts - np.timedelta64(MASS_H, "h"), side="right")
        out[g.index.values[o]] = r - l - 1
    return out


def universe(E: pd.DataFrame) -> np.ndarray:
    """Монет с любым событием за 30 дней ДО дня события (день события не включён)."""
    d = E.assign(day=E.ts.dt.floor("D"))
    P = d.groupby(["day", "sym"]).size().unstack(fill_value=0).gt(0)
    P = P.reindex(pd.date_range(P.index.min(), P.index.max(), freq="D"), fill_value=False)
    U = P.astype(int).rolling(UNIV_D, min_periods=1).max().sum(axis=1).shift(1)
    return U.reindex(d.day).values


def impulse_one(args):
    import logging
    logging.disable(logging.CRITICAL)
    from research_harness import load
    sym, rows = args
    try:
        d = load(sym, "1h")
    except Exception:                                    # noqa: BLE001
        return []
    if d is None or d.empty:
        return []
    d.index = d.index.tz_convert(None) if d.index.tz is not None else d.index
    c = d.close
    out = []
    for idx, ts, side in rows:
        sg = 1.0 if side == "SHORT" else -1.0
        rec = {"i": idx}
        c0 = c.get(ts)
        for h in (24, 72):
            cp = c.get(ts - pd.Timedelta(hours=h))
            rec[f"imp{h}"] = sg * (c0 / cp - 1) * 100 if c0 and cp else np.nan
        out.append(rec)
    return out


def _golden():
    # массовость: A 10:00, B 11:00, C 20:00 (одна сторона) → 0, 1, 0; D 11:00 SHORT другой стороны не считается
    t = pd.to_datetime(["2025-01-01 10:00", "2025-01-01 11:00", "2025-01-01 20:00", "2025-01-01 11:00"])
    G = pd.DataFrame({"sym": list("ABCD"), "ts": t, "side": ["LONG", "LONG", "LONG", "SHORT"]})
    assert list(mass_counts(G)) == [0, 1, 0, 0], mass_counts(G)
    # импульс: SHORT при росте 100→110 = +10; LONG при падении 100→90 = +10
    sg = lambda side: 1.0 if side == "SHORT" else -1.0  # noqa: E731
    assert round(sg("SHORT") * (110 / 100 - 1) * 100, 6) == 10.0
    assert round(sg("LONG") * (90 / 100 - 1) * 100, 6) == 10.0


def build(procs: int) -> pd.DataFrame:
    if OUT.exists():
        return pd.read_pickle(OUT)
    parts = []
    for mode, f in SRC.items():
        E = pd.read_pickle(f).reset_index(drop=True)
        E["ts"] = pd.to_datetime(E.ts)
        n0 = len(E)
        E["m6"] = mass_counts(E)
        E["U"] = universe(E)
        jobs = [(s, list(zip(g.index, g.ts, g.side))) for s, g in E.groupby("sym")]
        with Pool(procs) as pool:
            rows = [r for rr in pool.imap_unordered(impulse_one, jobs) for r in rr]
        I = pd.DataFrame(rows).set_index("i")
        E = E.join(I)
        assert len(E) == n0                              # §0A.3: join не размножил строки
        E["mode"] = mode
        parts.append(E)
    A = pd.concat(parts, ignore_index=True)
    A.to_pickle(OUT)
    return A


def terc(x: pd.Series) -> pd.Series:
    q1, q2 = x.quantile([1 / 3, 2 / 3])
    return pd.Series(np.where(x.isna(), -1, np.where(x <= q1, 0, np.where(x <= q2, 1, 2))), index=x.index)


def table(F: pd.DataFrame, col: str, label: str) -> None:
    print(f"  {label:<10}{'n':>6}{'дней':>6}{'4/8 ATR':>9}{'мед':>7}{'безтоп10':>10}{'24ч':>8}{'мед':>7}   границы / по годам 4/8 ATR")
    for k, g in F.groupby(col):
        if k < 0:
            continue
        s = np.sort(g.geo_wide.dropna().values)
        fr = s[:max(1, int(len(s) * 0.9))].mean() if len(s) else np.nan
        src = col.replace("_t", "")
        yy = " ".join(f"{y} {v:+.2f}" for y, v in g.groupby("y").geo_wide.mean().items())
        print(f"  {['низ', 'середина', 'верх'][k]:<10}{len(g):>6}{g.ts.dt.floor('D').nunique():>6}{g.geo_wide.mean():>+9.2f}"
              f"{g.geo_wide.median():>+7.2f}{fr:>+10.2f}{g.fwd_24.mean():>+8.2f}{g.fwd_24.median():>+7.2f}   "
              f"[{g[src].min():.2f}…{g[src].max():.2f}] {yy}")


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    _golden()
    A = build(procs)
    A["share"] = A.m6 / A.U * 100
    A["y"] = A.ts.dt.year
    A["score"] = A[["OB", "PIV", "WT", "ATR"]].sum(axis=1)
    print(f"событий {len(A)} · {A.groupby(['mode', 'side']).size().to_dict()}")
    print(f"импульс найден: {A.imp24.notna().mean() * 100:.1f}% · вселенная U: {A.U.min():.0f}…{A.U.max():.0f}")
    print("сырые строки:")
    print(A.sample(5, random_state=1)[["mode", "sym", "ts", "side", "m6", "U", "share", "imp24", "imp72", "OB", "geo_wide", "fwd_24"]]
          .round(2).to_string(index=False))
    print("\nрежим лет (медиана дрейфа рынка 30д в событиях):",
          " · ".join(f"{y} {v:+.1f}" for y, v in A.groupby("y").drift.median().items()))

    cards = []
    for (mode, side), F in A.groupby(["mode", "side"]):
        F = F.copy()
        F["share_t"], F["imp24_t"], F["imp72_t"] = terc(F.share), terc(F.imp24), terc(F.imp72)
        assert set(F.side) == {side}
        print(f"\n{'=' * 30} {mode} {side}: {len(F)} событий · база 4/8 ATR {F.geo_wide.mean():+.2f} · 24ч {F.fwd_24.mean():+.2f}")
        for col, lab in (("share_t", "массовость"), ("imp24_t", "импульс 24ч"), ("imp72_t", "импульс 72ч")):
            print(f" {lab}:")
            table(F, col, "терция")
        G = F[np.isfinite(F.geo_wide.values)].reset_index(drop=True)
        D = V.normalize(G.assign(pnl=G.geo_wide), pnl="pnl", ts="ts", liq="liq")
        cards.append(V.card(D, (G.share_t == 2).values, name=f"свип {mode} {side} × массовый (верх терции доли)",
                            study="sweep-mass-impulse"))
        cards.append(V.card(D, (G.imp24_t == 2).values, name=f"свип {mode} {side} × импульс 24ч верх терции",
                            study="sweep-mass-impulse"))
        if side == "LONG":
            cards.append(V.card(D, (G.OB & (G.share_t == 2)).values, name=f"свип {mode} LONG × бычий OB × массовый",
                                study="sweep-mass-impulse"))

        def search(p, G=G):
            best = ("", -1e9)
            for a in range(3):
                for b in range(3):
                    m = ((G.share_t == a) & (G.imp24_t == b)).values
                    if m.sum() >= 30:
                        v = p[m].mean() - p[~m].mean()
                        if v > best[1]:
                            best = (f"масс {a} × имп {b}", v)
            return best
        V.search_null(D, search, name=f"сетка терций масс×имп24 {mode} {side}", study="sweep-mass-impulse")

    V.save_md(cards, ROOT / "obsidian/Research/2026-10-09-Sweep-Mass-Impulse.md", "Свип: массовость и импульс",
              "Набор на свипе, этаж 2 — массовость дня и импульс перед свипом (sweep_mass_impulse_lab.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
