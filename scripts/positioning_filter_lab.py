# -*- coding: utf-8 -*-
"""СЛОЙ ПОЗИЦИОНИРОВАНИЯ КАК ФИЛЬТР МЕХАНИКИ (Егор 07.10: «начинай»).

Повод. Все 435 наших признаков — производные ЦЕНЫ, и потолок информации на них
измерен ([[hypercube_information_ceiling]]: 55.6% против 62.9%). Слой, который по
[[gap_positioning_layer_missing]] назван главным пробелом, оказался уже скачанным:
`C:/oko_data/history/metrics/` — 474 монеты × 2022-01-01→2026-09-28 × шаг 5 мин,
5 ГБ, и его не читает НИКТО, кроме скрипта загрузки.

Что меряем. НЕ самостоятельный сигнал — в этом качестве слой уже мерен и дал
≈0.001 бит сверх цены ([[positioning_layer_info_ceiling]], окно 23 дня OI).
Мы меряем его КАК ФИЛЬТР:改 меняет ли позиционирование результат уже существующей
механики. База — `wave_a_retrace` (23 357 сетапов, 222 монеты, 2020-26), у неё
есть готовый КОНТРОЛЬ той же геометрии (`ctl`), то есть сравнение честное.

🔴 ПРИЧИННОСТЬ. Метрика берётся на последний бар, ЗАКРЫТЫЙ СТРОГО ДО входа
(`time < entry_t`). Никаких «ближайших» и «текущих» — это тот же класс, что
look-ahead вида 6 ([[lookahead_htf_open_vs_close_time]]).

⚠️ Данные Binance, торгуем BingX: состав участников может отличаться, «топ-трейдеры» =
верхние 20% счетов по марже, не тождественно «умным деньгам».

Запуск:  python scripts/positioning_filter_lab.py [--coins 120]
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

SRC = "G:/oko_lab/out/wave_a_retrace"
MET = Path("C:/oko_data/history/metrics")

# окна накопления ΔOI: побарный знак — ШУМ (74% смен трактовки даже на 4h),
# работает только НАКОПЛЕНИЕ за окно ([[gap_positioning_layer_missing]])
WINDOWS = {"1h": 12, "4h": 48, "24h": 288}               # баров по 5 минут


def load_setups() -> pd.DataFrame:
    rows = []
    for f in glob.glob(f"{SRC}/*.pkl"):
        try:
            rows += pd.read_pickle(f)
        except Exception:                                # noqa: BLE001
            continue
    R = pd.DataFrame(rows)
    R["entry_t"] = pd.to_datetime(R["entry_t"])
    return R


def attach_metrics(R: pd.DataFrame, coins: int) -> pd.DataFrame:
    """К каждому сетапу — позиционирование на ПОСЛЕДНЕМ закрытом баре до входа."""
    syms = (R.sym.value_counts().head(coins).index.tolist())
    out = []
    miss = 0
    for i, s in enumerate(syms, 1):
        p = MET / f"{s}.parquet"
        if not p.exists():
            miss += 1
            continue
        try:
            m = pd.read_parquet(p)
        except Exception:                                # noqa: BLE001
            miss += 1
            continue
        m = m.sort_values("time").reset_index(drop=True)
        m["ts"] = pd.to_datetime(m.time, unit="ms", utc=True)
        oi = m.sum_open_interest.astype(float)
        # накопленный ΔOI за окно — в процентах к началу окна
        for nm, n in WINDOWS.items():
            m[f"doi_{nm}"] = (oi / oi.shift(n) - 1.0) * 100.0
        g = R[R.sym == s].copy()
        if g.empty:
            continue
        g["entry_utc"] = g.entry_t.dt.tz_localize("UTC") if g.entry_t.dt.tz is None else g.entry_t
        # 🔴 СТРОГО ДО входа: merge_asof с allow_exact_matches=False
        cols = ["ts", "doi_1h", "doi_4h", "doi_24h", "count_long_short_ratio",
                "count_toptrader_long_short_ratio", "sum_taker_long_short_vol_ratio"]
        cols = [c for c in cols if c in m.columns]
        g = pd.merge_asof(g.sort_values("entry_utc"), m[cols].sort_values("ts"),
                          left_on="entry_utc", right_on="ts",
                          direction="backward", allow_exact_matches=False,
                          tolerance=pd.Timedelta("30min"))
        out.append(g)
        if i % 25 == 0:
            print(f"  ... {i}/{len(syms)} монет", flush=True)
    print(f"  монет без файла метрик: {miss}", flush=True)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def st(v: pd.DataFrame):
    p = v["pnl"].dropna().values
    if len(p) < 40:
        return None
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    ctl = v["ctl"].dropna().values
    return dict(n=len(p), wr=(p > 0).mean() * 100,
                pf=pos / neg if neg > 0 else 9.99, mean=p.mean(),
                med=float(np.median(p)), total=p.sum(),
                frail=float(np.sort(p)[:max(1, int(len(p) * 0.9))].sum()),
                cov=(v.groupby("sym")["pnl"].sum() > 0).mean() * 100,
                ctl=ctl.mean() if len(ctl) else np.nan)


HEAD = (f"  {'клетка':<30}{'поток':>7}{'n':>6}{'WR':>7}{'PF':>7}{'средн':>8}"
        f"{'медиана':>8}{'безтоп10%':>10}{'монет+':>7}{'Δконтр':>8}")


def line(nm, s, base=None):
    if s is None:
        print(f"  {nm:<30} — мало")
        return
    fl = f"{s['n'] / base['n'] * 100:>6.0f}%" if base else "  база"
    d = s["mean"] - s["ctl"] if s["ctl"] == s["ctl"] else np.nan
    print(f"  {nm:<30}{fl}{s['n']:>6}{s['wr']:>6.1f}%{s['pf']:>7.2f}"
          f"{s['mean']:>+8.3f}{s['med']:>+8.3f}{s['frail']:>+10.0f}"
          f"{s['cov']:>6.0f}%{d:>+8.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=120)
    ap.add_argument("--target", default="2R")
    a = ap.parse_args()

    print("СЛОЙ ПОЗИЦИОНИРОВАНИЯ КАК ФИЛЬТР · база wave_a_retrace · контроль в данных\n")
    R = load_setups()
    print(f"сетапов: {len(R)} · монет: {R.sym.nunique()} · цели: {sorted(R.target.unique())}")
    print(f"присоединяю метрики (топ-{a.coins} монет по числу сетапов)…", flush=True)
    D = attach_metrics(R, a.coins)
    if D.empty:
        print("🔴 НЕТ ДАННЫХ после сопоставления — отказ, а не вывод")
        return 1

    cov = D.doi_4h.notna().mean() * 100
    print(f"\nсопоставлено: {len(D)} строк · покрытие ΔOI 4h = {cov:.1f}%")
    if cov < 50:
        print("🔴 покрытие ниже половины — дальше считать нельзя, сначала чинить сопоставление")
        return 1

    D = D[D.target == a.target]
    print(f"цель {a.target}: {len(D)} строк\n")

    for side in ("SHORT", "LONG"):
        S = D[D.side == side]
        b = st(S)
        if b is None:
            continue
        print("=" * 112)
        print(f"{side} · ПОЛНАЯ БАЗА (фильтра нет)")
        print("=" * 112)
        print(HEAD)
        line("вся база", b)

        print(f"  {'— НАКОПЛЕННЫЙ ΔOI за 4 ч —':<30}")
        q = S.doi_4h.quantile([.25, .5, .75]).round(2).tolist()
        for lo, hi, nm in ((-1e9, q[0], f"ΔOI < {q[0]}% (деливеридж)"),
                           (q[0], q[1], f"ΔOI {q[0]}…{q[1]}%"),
                           (q[1], q[2], f"ΔOI {q[1]}…{q[2]}%"),
                           (q[2], 1e9, f"ΔOI > {q[2]}% (приток)")):
            line(nm, st(S[(S.doi_4h >= lo) & (S.doi_4h < hi)]), b)

        print(f"  {'— ПРАВИЛО ИЗ ПАМЯТИ: вход при РОСТЕ OI —':<30}")
        for nm, m in ((" ΔOI 4h > 0 (новые деньги)", S.doi_4h > 0),
                      (" ΔOI 4h < 0 (закрытие)", S.doi_4h < 0),
                      (" ΔOI 1h>0 И 4h>0", (S.doi_1h > 0) & (S.doi_4h > 0)),
                      (" ΔOI 1h<0 И 4h<0", (S.doi_1h < 0) & (S.doi_4h < 0))):
            line(nm, st(S[m]), b)

        if "count_long_short_ratio" in S.columns and S.count_long_short_ratio.notna().any():
            print(f"  {'— РОЗНИЦА long/short —':<30}")
            r = S.count_long_short_ratio.quantile([.33, .67]).round(2).tolist()
            for lo, hi, nm in ((-1e9, r[0], f"розница < {r[0]} (шортят)"),
                               (r[0], r[1], f"розница {r[0]}…{r[1]}"),
                               (r[1], 1e9, f"розница > {r[1]} (лонгуют)")):
                line(nm, st(S[(S.count_long_short_ratio >= lo)
                              & (S.count_long_short_ratio < hi)]), b)

        if "sum_taker_long_short_vol_ratio" in S.columns and S.sum_taker_long_short_vol_ratio.notna().any():
            print(f"  {'— АГРЕССОР (taker buy/sell) —':<30}")
            t = S.sum_taker_long_short_vol_ratio.quantile([.33, .67]).round(2).tolist()
            for lo, hi, nm in ((-1e9, t[0], f"агрессор ПРОДАЁТ (<{t[0]})"),
                               (t[0], t[1], f"агрессор нейтрален"),
                               (t[1], 1e9, f"агрессор ПОКУПАЕТ (>{t[1]})")):
                line(nm, st(S[(S.sum_taker_long_short_vol_ratio >= lo)
                              & (S.sum_taker_long_short_vol_ratio < hi)]), b)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
