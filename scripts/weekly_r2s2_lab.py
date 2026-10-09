# -*- coding: utf-8 -*-
"""РАЗВОРОТ ОТ НЕДЕЛЬНЫХ R2/S2: касание + подтверждение (09.10.2026, Егор: «за разворотные я привык считать r2 и s2»).

Логика Егора по пивотам (22.09): R1–P–S1 — боковик, R2/S2 — цели и поддержка/сопротивление, R3+ — рост/пампы.
Правила weekly-hypo строили «отбой» на R1/S1 — внутри боковика. Здесь разворот там, где его ждёт Егор.
Карта 01.07 (память pivot_behavior_map): R2 отбой 62%, S2 69%, но без подтверждения ни один стоп не монетизировал.

Постановка зафиксирована ДО прогона (стенд — scripts/weekly_hypo_touch_lab.py, те же функции):
  r2_fade  SHORT  касание R2 (неделя открылась ниже R2)  цель R1 | P   стоп R3
  s2_hold  LONG   касание S2 (неделя открылась выше S2)  цель S1 | P   стоп S3
  подтверждение за 24 ч до стопа: T0 нет · T1 кросс WT 15m · T2 кросс WT 1h · T3 внутренний CHoCH 1h;
  совпадение на баре входа: структура 4h · нога OTE · режим недели в сторону сделки (BEAR для шорта, BULL для лонга);
  выход: стоп/цель (в одном баре — стоп), иначе конец недели; кост 0.35; контроль — случайный час из распределения задержек.
R3 = 2·R1 − S1, S3 = 2·S1 − R1 (classic: R3 = H + 2(P − L), S3 = L − 2(H − P); проверяется assert на данных).
Запуск: python scripts/weekly_r2s2_lab.py [--workers 8] [--reuse]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from weekly_hypo_touch_lab import (COST, FLAGS, JOINT, TF1H, TRIG, WAIT, WEEKS, summary, trade)  # noqa: E402

OUT = Path("G:/oko_lab/out/weekly_r2s2_lab.parquet")
SETUPS = [  # (правило, сторона, уровень касания, цели, стоп)
    ("r2_fade", -1, "R2", ("R1", "P"), "R3"),
    ("s2_hold", 1, "S2", ("S1", "P"), "S3"),
]


def one(sym: str):
    W = pd.read_parquet(WEEKS, filters=[("sym", "==", sym)])
    f1, fj = TF1H / f"{sym}.parquet", JOINT / f"{sym}.parquet"
    if W.empty or not f1.exists() or not fj.exists():
        return []
    W["R3"] = 2 * W.R1 - W.S1
    W["S3"] = 2 * W.S1 - W.R1
    b = pd.read_parquet(f1)[["high", "low", "close"]]
    d = b.join(pd.read_parquet(fj, columns=FLAGS), how="inner")
    if len(d) < 24 * 60:
        return []
    ev = np.where((d.bull_bos_4h__from_4h > 0) | (d.bull_choch_4h__from_4h > 0), 1.0,
                  np.where((d.bear_bos_4h__from_4h > 0) | (d.bear_choch_4h__from_4h > 0), -1.0, np.nan))
    d["struct4h"] = pd.Series(ev, index=d.index).ffill()
    H, L, C = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
    t = d.index.to_numpy()
    out = []
    for _, w in W.iterrows():
        i0 = int(np.searchsorted(t, np.datetime64(w.week)))
        i1 = int(np.searchsorted(t, np.datetime64(w.week + pd.Timedelta(days=7)))) - 1
        if i1 - i0 < 150 or w.S3 <= 0:
            continue
        for code, side, tl, targets, st in SETUPS:
            lvl, stop = w[tl], w[st]
            if (side < 0 and not w.open < lvl) or (side > 0 and not w.open > lvl):
                continue                         # неделя открылась уже за уровнем — касания «изнутри» нет
            k = None
            for i in range(i0, i1 + 1):
                if (side < 0 and H[i] >= lvl) or (side > 0 and L[i] <= lvl):
                    hit_stop = (side < 0 and H[i] >= stop) or (side > 0 and L[i] <= stop)
                    k = None if hit_stop else i  # касание и стоп в одном баре — сетапа нет
                    break
            if k is None:
                continue
            for tgt in targets:
                target = w[tgt]
                flags = {"T0": None, **{n: d[c].to_numpy() for n, c in TRIG[side].items()}}
                for trig, F in flags.items():
                    m = None
                    for i in range(k, min(k + WAIT, i1)):
                        if i > k and ((side > 0 and L[i] <= stop) or (side < 0 and H[i] >= stop)):
                            break
                        if F is None or F[i] > 0:
                            m = i
                            break
                    if m is None or m >= i1:
                        continue
                    e = C[m]
                    if not ((side > 0 and stop < e < target) or (side < 0 and target < e < stop)):
                        continue
                    out.append({"sym": sym, "week": w.week, "rule": f"{code}→{tgt}", "side": "LONG" if side > 0 else "SHORT",
                                "trig": trig, "delay": m - k, "ts": d.index[m],
                                "pnl": trade(H, L, C, m, i1, side, stop, target) - COST,
                                "stop_pct": abs(e - stop) / e * 100,
                                "struct": float(d.struct4h.iat[m] == side),
                                "leg": float((d.legup_in_ote.iat[m] if side > 0 else d.legdn_in_ote.iat[m]) == 1),
                                "regime_ok": float((w.regime == "BULL") == (side > 0)), "liq": d.liq.iat[m]})
                vec, alive = [], True
                for dd in range(WAIT):
                    mc = k + dd
                    if mc >= i1:
                        vec.append(np.nan); continue
                    if dd > 0 and ((side > 0 and L[mc] <= stop) or (side < 0 and H[mc] >= stop)):
                        alive = False
                    ec = C[mc]
                    ok = alive and ((side > 0 and stop < ec < target) or (side < 0 and target < ec < stop))
                    vec.append(trade(H, L, C, mc, i1, side, stop, target) - COST if ok else np.nan)
                for r in out:
                    if r["week"] == w.week and r["rule"] == f"{code}→{tgt}" and "ctrl_vec" not in r:
                        r["ctrl_vec"] = vec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    W0 = pd.read_parquet(WEEKS, columns=["P", "R1", "S1", "R2", "S2"]).dropna().head(1000)
    # тождество: из R1/S1 восстанавливаются H и L прошлой недели, R2 = P + (H − L) обязан совпасть
    Hh, Ll = 2 * W0.P - W0.S1, 2 * W0.P - W0.R1
    assert np.allclose(W0.P + (Hh - Ll), W0.R2, rtol=1e-9) and np.allclose(W0.P - (Hh - Ll), W0.S2, rtol=1e-9)
    if a.reuse and OUT.exists():
        T = pd.read_parquet(OUT)
    else:
        syms = sorted(pd.read_parquet(WEEKS, columns=["sym"]).sym.unique())
        with ProcessPoolExecutor(a.workers) as ex:
            res = list(ex.map(one, syms, chunksize=4))
        T = pd.DataFrame([r for part in res for r in part])
        T.to_parquet(OUT)
    T["year"] = pd.to_datetime(T.ts).dt.year
    rng = np.random.default_rng(0)
    ctrl = np.full(len(T), np.nan)
    for (rule, trig), idx in T.groupby(["rule", "trig"]).groups.items():
        if trig == "T0":
            continue
        delays = T.loc[idx, "delay"].to_numpy()
        for i in idx:
            v = np.asarray(T.at[i, "ctrl_vec"], float)
            for _ in range(10):
                x = v[rng.choice(delays)]
                if not np.isnan(x):
                    ctrl[T.index.get_loc(i)] = x
                    break
    T["ctrl"] = ctrl
    T = T.drop(columns=["ctrl_vec"])
    assert (T.loc[T.trig == "T0", "delay"] == 0).all()
    print("═" * 118)
    print(f"СДЕЛОК {len(T)} · монет {T.sym.nunique()} · недель {T.week.nunique()} · {T.ts.min():%Y-%m-%d} → {T.ts.max():%Y-%m-%d}")
    print(T.groupby(["rule", "trig"]).size().unstack().to_string())
    CONF = (("—", lambda X: np.ones(len(X), bool)), ("структура", lambda X: X.struct.values > 0),
            ("нога OTE", lambda X: X.leg.values > 0), ("режим", lambda X: X.regime_ok.values > 0))
    rows = []
    for (rule, trig), X in T.groupby(["rule", "trig"]):
        for conf, f in CONF:
            Y = X[f(X)]
            if len(Y) >= 30:
                rows.append({"rule": rule, "trig": trig, "conf": conf, **summary(Y),
                             **{f"y{y % 100}": Y[Y.year == y].pnl.mean() if (Y.year == y).sum() >= 15 else np.nan
                                for y in (2023, 2024, 2025, 2026)}})
    S = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print("\nВСЕ КОНФИГУРАЦИИ (net % на сделку; frail = среднее без верхних 10%; ctrl = случайный час той же задержки)")
    print(S.round(2).sort_values(["rule", "trig", "conf"]).to_string(index=False))

    from research_verify import card, normalize, save_md, search_null
    N = normalize(T, pnl="pnl")
    masks = {}
    for (rule, trig), idx in N.groupby(["rule", "trig"]).groups.items():
        base = np.zeros(len(N), bool); base[idx] = True
        for conf, f in CONF:
            m = base & f(N)
            if m.sum() >= 50:
                masks[f"{rule}|{trig}|{conf}"] = m

    def search(p):
        best, lab = -1e9, ""
        for k_, m in masks.items():
            v = p[m].mean()
            if v > best:
                best, lab = v, k_
        return lab, best

    print()
    sn = search_null(N, search, name=f"R2/S2 разворот ({len(masks)} конфигураций)", study="weekly_r2s2_09_10", n=200)
    regimes = {2023: "бык", 2024: "нейтраль", 2025: "медведь", 2026: "медведь"}
    cards = []
    for lab in [k_ for k_ in S.assign(k=S.rule + "|" + S.trig + "|" + S.conf).sort_values("mean", ascending=False).k
                if k_ in masks][:3]:
        rule = lab.split("|")[0]
        P = N[N.rule == rule].reset_index(drop=True)
        cards.append(card(P, masks[lab][N.rule.values == rule], name=lab, study="weekly_r2s2_09_10",
                          geo=("stop_pct",), regimes=regimes))
    save_md(cards, ROOT / "obsidian" / "Research" / "2026-10-09-Weekly-R2S2-Cards.md",
            "Разворот от недельных R2/S2 — карточки", f"Три лучшие из {len(masks)} + ярус 2: {sn['text'][:160]}")


if __name__ == "__main__":
    main()
