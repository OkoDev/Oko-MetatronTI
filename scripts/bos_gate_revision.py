# -*- coding: utf-8 -*-
"""РЕВИЗИЯ СТРУКТУРНОГО ГЕЙТА «ТОЛЬКО ПОСЛЕ BOS» (13.08.2026, Даат).

Повод: [[bos_gate_bigflush_structural]] заявляет PF 1.53→1.79 и хрупкость −277→+634,
и этот гейт **УЖЕ В БОЮ** на bigflush15. При этом он мерился на окне 2024–26
(без бычьего 2023 и без медвежьего 2022) — а ревизия 13.08 показала, что 4 из 4
записанных находок разваливались именно при расширении базы/окна
([[law_recorded_pf_needs_remeasure]]).

Гейт торгует в бою → цена ошибки максимальная, перемер обязателен.

Реализация: реальный движок проекта `core/smc/oko_sm_engine.run_structure`
(один калькулятор на историю и бой — [[principle_reuse_not_duplication]]).
Признак: был ли МЕДВЕЖИЙ BOS шкалы len5 (internal) в последних N барах ДО сигнала.
Событие берётся по индексу подтверждения → причинно, будущее не используется.

Запуск:  python scripts/bos_gate_revision.py [--tf 4h] [--lookback 10]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.smc.oko_sm_engine import run_structure  # noqa: E402

DB = "ohlcv_cache.db"
DUMPS = {"4h": "scripts/_fade_signals_4h_enriched.csv",
         "15m": "scripts/_fade_signals_15m_enriched.csv"}
REGIME = {2022: "медведь", 2023: "БЫК", 2024: "нейтраль", 2025: "медведь", 2026: "медведь"}


def stat(s: pd.Series):
    if len(s) == 0:
        return None
    v = s.values
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    srt = np.sort(v)
    cut = max(1, int(len(srt) * 0.10))
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), float(srt[:-cut].sum())


def add_bos(d: pd.DataFrame, tf: str, lookback: int) -> pd.DataFrame:
    """Для каждого сигнала: был ли медвежий BOS (len5 и len50) в окне [i-lookback, i]."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    n_bos5 = np.full(len(d), np.nan)
    n_bos50 = np.full(len(d), np.nan)
    syms = d.symbol.unique()
    for k, sym in enumerate(syms):
        px = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                         "AND timeframe=? ORDER BY time", con, params=(sym, tf))
        if len(px) < 200:
            continue
        try:
            st = run_structure(px[["open", "high", "low", "close"]].reset_index(drop=True))
        except Exception:
            continue
        ev5, ev50 = [], []
        for e in st.events:
            if e.kind != "BOS" or e.bull:      # нужен МЕДВЕЖИЙ BOS (слом вниз перед проливом)
                continue
            (ev5 if e.internal else ev50).append(e.i)
        ev5, ev50 = np.array(sorted(ev5)), np.array(sorted(ev50))
        t = px.time.values
        grp = d[d.symbol == sym]
        for idx, ts in zip(grp.index, grp.ts.values):
            j = int(np.searchsorted(t, ts))
            if j < 60:
                continue
            pos = d.index.get_loc(idx)
            n_bos5[pos] = int(((ev5 >= j - lookback) & (ev5 <= j)).sum()) if len(ev5) else 0
            n_bos50[pos] = int(((ev50 >= j - lookback) & (ev50 <= j)).sum()) if len(ev50) else 0
        if (k + 1) % 25 == 0:
            print(f"  ...{k + 1}/{len(syms)} монет", flush=True)
    con.close()
    d["n_bos5"] = n_bos5
    d["n_bos50"] = n_bos50
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h", choices=list(DUMPS))
    ap.add_argument("--lookback", type=int, default=10)
    a = ap.parse_args()

    d = pd.read_csv(DUMPS[a.tf]).reset_index(drop=True)
    print("═" * 100)
    print(f"РЕВИЗИЯ BOS-ГЕЙТА · {a.tf} · lookback {a.lookback} баров · движок проекта run_structure")
    print("ЗАЯВЛЕНО: bigflush15 PF 1.53→1.79, хрупкость −277→+634 (окно 2024–26). ГЕЙТ В БОЮ.")
    print("ЗДЕСЬ: полная база фейда, окно всей истории дампа, причинно")
    print("═" * 100)
    print(f"\nсчитаю структуру для {d.symbol.nunique()} монет...")
    d = add_bos(d, a.tf, a.lookback)
    ok = int(d.n_bos5.notna().sum())
    print(f"посчитано для {ok} сигналов из {len(d)}")

    L = d[(d.side == "LONG") & d.n_bos5.notna()]
    print(f"\n{'срез (LONG)':<30} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'безтоп10%':>11}")
    base = stat(L.net)
    print(f"{'БАЗА (без гейта)':<30} {base[0]:>6} {base[1]:>+9.3f}% {base[2]:>6.1f}% "
          f"{base[3]:>7.2f} {base[4]:>+10.1f}")
    for nm, cond in (("len5: ≥1 BOS", L.n_bos5 >= 1), ("len5: ≥2 BOS", L.n_bos5 >= 2),
                     ("len5: НЕТ BOS", L.n_bos5 == 0),
                     ("len50: ≥1 BOS", L.n_bos50 >= 1), ("len50: НЕТ BOS", L.n_bos50 == 0)):
        r = stat(L[cond].net)
        if r and r[0] >= 30:
            print(f"{nm:<30} {r[0]:>6} {r[1]:>+9.3f}% {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.1f}")

    a1, b1 = L[L.n_bos5 == 0].net, L[L.n_bos5 >= 1].net
    if len(a1) >= 30 and len(b1) >= 30:
        p = stats.mannwhitneyu(a1, b1, alternative="less").pvalue
        print(f"\nзначимость len5 (есть BOS лучше, чем нет): p={p:.5f} "
              f"{'✅' if p < 0.05 else '❌ НЕ значимо'}")

    print(f"\n{'год (режим) · len5≥1':<30} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7}")
    G = L[L.n_bos5 >= 1]
    for y in sorted(G.t.pipe(lambda s: pd.to_datetime(s)).dt.year.unique()) if "t" in G else []:
        pass
    G = G.assign(year=pd.to_datetime(G.ts, unit="ms").dt.year)
    Lb = L.assign(year=pd.to_datetime(L.ts, unit="ms").dt.year)
    for y in sorted(Lb.year.unique()):
        rg, rb = stat(G[G.year == y].net), stat(Lb[Lb.year == y].net)
        if rg and rg[0] >= 25:
            print(f"{str(y) + ' (' + REGIME.get(y, '?') + ')':<30} {rg[0]:>6} {rg[1]:>+9.3f}% "
                  f"{rg[2]:>6.1f}% {rg[3]:>7.2f}   (база года PF {rb[3]:.2f})")

    print(f"\n{'BOS × размер стопа (len5≥1)':<30} {'n':>6} {'медиана':>10} {'PF':>7}")
    for nm, lo, hi in (("стоп 4-8%", 4, 8), ("стоп 8-12%", 8, 12)):
        r = stat(G[(G.stop_pct > lo) & (G.stop_pct <= hi)].net)
        if r and r[0] >= 25:
            print(f"{nm:<30} {r[0]:>6} {r[1]:>+9.3f}% {r[3]:>7.2f}")

    d.to_csv(f"scripts/_fade_signals_{a.tf}_bos.csv", index=False)
    print(f"\n[dump] → scripts/_fade_signals_{a.tf}_bos.csv")
    print("═" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
