# -*- coding: utf-8 -*-
"""ПОРТФЕЛЬ «ЯДРО ВОЛН + ОТКАТ В РОСТЕ»: сглаживают ли две механики друг друга (08.10, продолжение
`leg_continuation_lab.py`).

Гипотеза: ядро волн (доказанные лонги) зарабатывает в днях капитуляции, откат в OTE дневной ноги при растущем рынке —
в днях роста. Каждая по отдельности держится на ~10% лучших дней; если эти дни у них РАЗНЫЕ, общий счёт может пережить
снятие лучших дней, которого не переживает ни одна.

Сделки:
  · ядро — `wave_portfolio_sim.prepare()` (выход пересчитан, голден 99.9%), доказанные лонги, риск 1%;
  · откат — события `legup_ote` при дрейфе30 ≥ верхней трети обычных часов IS (как в `leg_continuation_lab`),
    выход заново проходится по свечам 1h тем же правилом, что `geo_wide` журнала (стоп 4 ATR / цель 8 ATR от open
    следующего бара, стоп раньше цели на одном баре, 72 ч) — ГОЛДЕН: доход обязан совпасть с журналом.
Вклад сделки в капитал = риск% × доход% / стоп%. Учёт по закрытию (просадка занижена). Окно 2023–2025 у обеих
(2026 у отката отложен). Бюджет риска — `simulate_riskcap` (как в бою: 15/25, сверх мягкого только |WT пятой| ≥ 75
половиной; у отката WT пятой нет → сверх мягкого он не берётся).

Запуск: python scripts/leg_waves_portfolio_lab.py [процессов]
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

import wave_portfolio_sim as W                            # noqa: E402

EV = Path("G:/oko_lab/joint/events")
OUT = Path("G:/oko_lab/out/leg_rising_trades.pkl")
COST, KS, KT, GEO_H = 0.35, 4.0, 8.0, 72
T_END = pd.Timestamp("2026-01-01")


def _naive(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_convert(None) if s.dt.tz is not None else s


def _walk(args):
    """Проход одной монеты: то же правило, что `joint_state_journal._geo_block` (лонг)."""
    sym, ts_list = args
    import logging
    logging.disable(logging.CRITICAL)
    from research_harness import load
    d = load(sym, "1h")
    out = []
    if d is None or d.empty:
        return [(sym, t, np.nan, np.nan, None) for t in ts_list]
    idx = d.index.tz_convert(None) if d.index.tz is not None else d.index
    h, l, c, o = (d[k].values.astype(float) for k in ("high", "low", "close", "open"))
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values
    pos = {t: i for i, t in enumerate(idx)}
    n = len(d)
    for t in ts_list:
        i = pos.get(t)
        if i is None or i + 1 >= n or not np.isfinite(atr[i]):
            out.append((sym, t, np.nan, np.nan, None))
            continue
        e = o[i + 1]
        stop, tgt = e - KS * atr[i], e + KT * atr[i]
        res, xt = np.nan, None
        for k in range(1, GEO_H + 1):
            j = i + k
            if j >= n:
                break
            if l[j] <= stop:
                res, xt = (stop - e) / e * 100, idx[j]
                break
            if h[j] >= tgt:
                res, xt = (tgt - e) / e * 100, idx[j]
                break
            if k == GEO_H:
                res, xt = (c[j] - e) / e * 100, idx[j]
        out.append((sym, t, res, KS * atr[i] / e * 100, xt))
    return out


def leg_trades(procs: int) -> pd.DataFrame:
    if OUT.exists():
        return pd.read_pickle(OUT)
    E = pd.read_parquet(EV / "legup_ote.parquet")
    E = E.reset_index().rename(columns={"index": "ts"}) if "ts" not in E.columns else E.reset_index(drop=True)
    C = pd.read_parquet(EV / "ctrl.parquet")
    C = C.reset_index().rename(columns={"index": "ts"}) if "ts" not in C.columns else C.reset_index(drop=True)
    E["ts"], C["ts"] = _naive(E.ts), _naive(C.ts)
    hi = np.nanquantile(C.mkt_drift30.values[C.ts.dt.year.isin((2023, 2024)).values], 2 / 3)
    E = E[(E.mkt_drift30 >= hi) & (E.ts < T_END) & np.isfinite(E.geo_wide_long)].reset_index(drop=True)
    print(f"откат в росте: событий {len(E)} (дрейф30 ≥ {hi:+.2f}), монет {E.sym.nunique()}", flush=True)
    jobs = [(s, list(g.ts)) for s, g in E.groupby("sym")]
    rows = []
    with Pool(procs) as pool:
        for r in pool.imap_unordered(_walk, jobs):
            rows += r
    R = pd.DataFrame(rows, columns=["sym", "ts", "pnl_walk", "stop_pct", "X"])
    n0 = len(E)
    E = E.merge(R, on=["sym", "ts"], how="left", validate="one_to_one")
    assert len(E) == n0                                                       # §0A.3
    E.to_pickle(OUT)
    return E


def daily(T: pd.DataFrame) -> pd.Series:
    return T.groupby(T.X.dt.floor("D")).c.sum()


def no_best_days(s: pd.Series, q: float = 0.10) -> float:
    k = int(len(s) * q)
    return float(s.sort_values().iloc[: len(s) - k].sum())


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    L = leg_trades(procs)
    # ГОЛДЕН §0A.2: пересчёт выхода воспроизводит исход журнала (валовый)
    ok = L.pnl_walk.notna()
    match = (np.abs(L.pnl_walk[ok] - L.geo_wide_long[ok]) < 0.01).mean()
    print(f"откат: пересчёт выхода у {ok.mean() * 100:.1f}% · совпал с журналом в {match * 100:.1f}%")
    assert match > 0.97, "пересчёт выхода не воспроизводит журнал"
    L = L[ok & (np.abs(L.pnl_walk - L.geo_wide_long) < 0.01)].copy()
    L["E"], L["X"] = L.ts, pd.to_datetime(L.X)
    L["pnl_re"] = L.pnl_walk - COST
    L["wt_abs"], L["wt_neg"], L["src"] = np.nan, 0.0, "откат"
    print(L[["sym", "ts", "X", "stop_pct", "geo_wide_long", "pnl_re"]].head(3).round(3).to_string(index=False))

    D, proven = W.prepare(procs)
    P = D[proven & (D.E < T_END)].copy()
    P["src"] = "ядро"
    print(f"ядро: доказанных лонгов {len(P)} · {P.E.min():%Y-%m-%d} → {P.E.max():%Y-%m-%d} · "
          f"откат: {len(L)} · {L.E.min():%Y-%m-%d} → {L.E.max():%Y-%m-%d}")

    # ── дни: совпадают ли лучшие дни двух механик (без лимита, риск 1%) ──
    for T in (P, L):
        T["c"] = 1.0 * T.pnl_re / T.stop_pct
    dp, dl = daily(P), daily(L)
    days = dp.index.union(dl.index)
    a, b = dp.reindex(days, fill_value=0.0), dl.reindex(days, fill_value=0.0)
    both = (dp.reindex(days).notna() & dl.reindex(days).notna())
    tp = set(dp.sort_values().index[-max(1, int(len(dp) * 0.1)):])
    tl = set(dl.sort_values().index[-max(1, int(len(dl) * 0.1)):])
    print("\n" + "=" * 110)
    print("ДНИ (без лимита, риск 1% на сделку, % капитала по дню закрытия)")
    print("=" * 110)
    print(f"  дней с закрытиями: ядро {len(dp)} · откат {len(dl)} · общих {int(both.sum())}")
    print(f"  корреляция дневных итогов (на общих днях): {np.corrcoef(a[both], b[both])[0, 1]:+.2f} · "
          f"на всех днях (0 где нет сделок): {np.corrcoef(a, b)[0, 1]:+.2f}")
    print(f"  лучшие 10% дней: ядро {len(tp)} · откат {len(tl)} · совпало {len(tp & tl)}")
    print(f"  в лучшие дни ЯДРА откат дал {b[list(tp)].sum():+.1f}% · в лучшие дни ОТКАТА ядро дало {a[list(tl)].sum():+.1f}%")
    print(f"  в худшие 10% дней ядра откат дал {b[list(dp.sort_values().index[:len(tp)])].sum():+.1f}% · "
          f"в худшие дни отката ядро {a[list(dl.sort_values().index[:len(tl)])].sum():+.1f}%")
    for nm, s in (("ядро", a), ("откат", b), ("вместе", a + b)):
        s = s[s != 0]
        print(f"  {nm:<7} итог {s.sum():+8.1f} · без 10% лучших дней {no_best_days(s):+8.1f} · "
              f"худший день {s.min():+6.1f} · по годам " +
              " ".join(f"{y} {v:+.1f}" for y, v in s.groupby(s.index.year).sum().items()))

    # ── портфель с бюджетом риска как в бою ──
    print("\n" + "=" * 110)
    print("ПОРТФЕЛЬ С БЮДЖЕТОМ РИСКА 15/25 (как в бою; учёт по закрытию)")
    print("=" * 110)
    cols = ["E", "X", "pnl_re", "stop_pct", "wt_abs", "wt_neg", "risk", "src"]
    for nm, T in (("ядро", P.assign(risk=1.0)), ("откат, риск 1%", L.assign(risk=1.0)),
                  ("откат, риск 0.5%", L.assign(risk=0.5)),
                  ("вместе, откат 1%", pd.concat([P.assign(risk=1.0)[cols], L.assign(risk=1.0)[cols]])),
                  ("вместе, откат 0.5%", pd.concat([P.assign(risk=1.0)[cols], L.assign(risk=0.5)[cols]]))):
        r = W.simulate_riskcap(T.reset_index(drop=True), 15, 25)
        print(f"  {nm:<20} сделок {r['n']:>5} · итог {r['total']:+7.1f} · просадка {r['dd']:+6.1f} · худший день "
              f"{r['worst_day']:+6.1f} · макс риск {r['max_risk']:5.1f}% · годы {r['years']}")
    print("\n⚠️ учёт по закрытию → просадка занижена; откат — без коста VST и без проскальзывания рыночного входа; "
          "у отката нет WT пятой, поэтому сверх мягкого бюджета он не берётся.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
