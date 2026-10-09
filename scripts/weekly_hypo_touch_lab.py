# -*- coding: utf-8 -*-
"""НЕДЕЛЬНЫЕ ГИПОТЕЗЫ: ВХОД ПО КАСАНИЮ + ПОДТВЕРЖДЕНИЕ + ВОЛНЫ/СТРУКТУРА (09.10.2026, «НЕ проверено» → проверить).

weekly_hypo_lab показал: вход на открытии недели не зарабатывает, «цель раньше отмены» — в основном геометрия.
Непроверенным остался «метод Егора»: ждать касания уровня, войти по подтверждению младшего ТФ, учесть волны
и структуру. Постановка зафиксирована ДО прогона (64 конфигурации → ярус 2 обязателен):

  правило          сторона  касание  цель  стоп     (стоп у break-правил — P: отмена S1/R1 даёт R:R < 1)
  bull_hold_s1     LONG     S1       R1    S2
  bear_fade_r1     SHORT    R1       S1    R2
  bull_break_r1    LONG     R1       R2    P
  bear_break_s1    SHORT    S1       S2    P

  · касание — первый 1h-бар недели, достигший уровня (хай/лой); отмена гипотезы до касания → сделки нет;
  · подтверждение в окне 24 ч от касания, стоп за это время не тронут: T0 нет (вход на закрытии бара касания),
    T1 кросс WT 15m в этом часе, T2 кросс WT 1h, T3 внутренний CHoCH 1h — по стороне сделки;
  · совпадение на баре входа: волна (w_side = сторона и w_core = 1), структура 4h (последний BOS/CHoCH 4h в сторону),
    нога OTE (дневная нога волнового аналитика wave_analyst.daily_leg в OTE 0.5–0.79: legup для лонга, legdn для шорта) — добавлено, т.к. ядро волн совпало с касанием в 0.3%;
  · выход: стоп или цель (в одном баре — стоп), иначе закрытие недели; кост 0.35%;
  · контроль задержки: вход через те же часы после касания БЕЗ флага (колонка ctrl карточки).
Данные: уровни/зоны — G:/oko_lab/out/weekly_hypo_lab.parquet (Binance, сверено с BingX 98%), бары — G:/oko_lab/tf/1h,
флаги — журнал общего состояния G:/oko_lab/joint/1h (причинный, строка = закрытый бар). Окно 2023-01 → 2026-09.
Запуск: python scripts/weekly_hypo_touch_lab.py [--workers 8] [--reuse]
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

WEEKS = Path("G:/oko_lab/out/weekly_hypo_lab.parquet")
TF1H = Path("G:/oko_lab/tf/1h")
JOINT = Path("G:/oko_lab/joint/1h")
OUT = Path("G:/oko_lab/out/weekly_hypo_touch_lab.parquet")
COST = 0.35
WAIT = 24
SETUP = {   # (режим, зона) → (правило, сторона, уровень касания, цель, стоп, отмена гипотезы)
    ("BULL", "S1..P"): ("bull_hold_s1", 1, "S1", "R1", "S2", "S2"),
    ("BEAR", "P..R1"): ("bear_fade_r1", -1, "R1", "S1", "R2", "R2"),
    ("BULL", "P..R1"): ("bull_break_r1", 1, "R1", "R2", "P", "S1"),
    ("BEAR", "S1..P"): ("bear_break_s1", -1, "S1", "S2", "P", "R1"),
}
TRIG = {1: {"T1": "wt_cross_up_15m_in_h", "T2": "wt_cross_up_1h", "T3": "bull_choch_i_1h"},
        -1: {"T1": "wt_cross_dn_15m_in_h", "T2": "wt_cross_down_1h", "T3": "bear_choch_i_1h"}}
FLAGS = ["wt_cross_up_15m_in_h", "wt_cross_dn_15m_in_h", "wt_cross_up_1h", "wt_cross_down_1h",
         "bull_choch_i_1h", "bear_choch_i_1h", "bull_bos_4h__from_4h", "bull_choch_4h__from_4h",
         "bear_bos_4h__from_4h", "bear_choch_4h__from_4h", "w_side", "w_core", "liq",
         "legup_in_ote", "legdn_in_ote"]


def hit(side_up: bool, hi, lo, lvl):
    return hi >= lvl if side_up else lo <= lvl


def trade(H, L, C, m, end, side, stop, target):
    """Вход на закрытии бара m, выход: стоп/цель (в одном баре — стоп), иначе закрытие бара end."""
    e = C[m]
    for j in range(m + 1, end + 1):
        if (side > 0 and L[j] <= stop) or (side < 0 and H[j] >= stop):
            return side * (stop - e) / e * 100
        if (side > 0 and H[j] >= target) or (side < 0 and L[j] <= target):
            return side * (target - e) / e * 100
    return side * (C[end] - e) / e * 100


def one(sym: str):
    W = pd.read_parquet(WEEKS, filters=[("sym", "==", sym)])
    f1, fj = TF1H / f"{sym}.parquet", JOINT / f"{sym}.parquet"
    if W.empty or not f1.exists() or not fj.exists():
        return []
    b = pd.read_parquet(f1)[["high", "low", "close"]]
    j = pd.read_parquet(fj, columns=FLAGS)
    d = b.join(j, how="inner")
    if len(d) < 24 * 60:
        return []
    ev = np.where((d.bull_bos_4h__from_4h > 0) | (d.bull_choch_4h__from_4h > 0), 1.0,
                  np.where((d.bear_bos_4h__from_4h > 0) | (d.bear_choch_4h__from_4h > 0), -1.0, np.nan))
    d["struct4h"] = pd.Series(ev, index=d.index).ffill()
    H, L, C = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
    t = d.index.to_numpy()
    out = []
    for _, w in W.iterrows():
        key = (w.regime, w.zone)
        if key not in SETUP:
            continue
        code, side, tl, tg, st, inv = SETUP[key]
        lv = {k: w[k] for k in ("P", "R1", "R2", "S1", "S2")}
        i0 = int(np.searchsorted(t, np.datetime64(w.week)))
        i1 = int(np.searchsorted(t, np.datetime64(w.week + pd.Timedelta(days=7)))) - 1
        if i1 - i0 < 150:
            continue
        up_t = tl.startswith("R"); up_inv = inv.startswith("R")
        k = None
        for i in range(i0, i1 + 1):
            inv_hit = hit(up_inv, H[i], L[i], lv[inv])
            if hit(up_t, H[i], L[i], lv[tl]):
                k = None if inv_hit else i      # касание и отмена в одном баре → гипотеза сломана
                break
            if inv_hit:
                break
        if k is None:
            continue
        stop, target = lv[st], lv[tg]
        flags = {"T0": None, **{n: d[c].to_numpy() for n, c in TRIG[side].items()}}
        for trig, F in flags.items():
            m = None
            for i in range(k, min(k + WAIT, i1)):
                if i > k and ((side > 0 and L[i] <= stop) or (side < 0 and H[i] >= stop)):
                    break                        # стоп тронут до подтверждения → сделки нет
                if F is None or F[i] > 0:
                    m = i
                    break
            if m is None or m >= i1:
                continue
            e = C[m]
            if not ((side > 0 and stop < e < target) or (side < 0 and target < e < stop)):
                continue
            pnl = trade(H, L, C, m, i1, side, stop, target)
            ws, wc = d.w_side.iat[m], d.w_core.iat[m]
            out.append({"sym": sym, "week": w.week, "rule": code, "side": "LONG" if side > 0 else "SHORT",
                        "trig": trig, "delay": m - k, "ts": d.index[m], "pnl": pnl - COST,
                        "stop_pct": abs(e - stop) / e * 100,
                        "wave": float(ws == side and wc == 1), "wave_side": float(ws == side),
                        "struct": float(d.struct4h.iat[m] == side), "liq": d.liq.iat[m],
                        # волна шире ядра: откат последней ноги в OTE (нога вверх для лонга, вниз для шорта)
                        "leg": float((d.legup_in_ote.iat[m] if side > 0 else d.legdn_in_ote.iat[m]) == 1)})
        # контроль: исход входа на КАЖДОМ часе 0..WAIT−1 после касания без всякого флага (NaN — стоп уже тронут,
        # неделя кончилась или цена за целью). main берёт час из распределения задержек того же триггера.
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
            if r["week"] == w.week and "ctrl_vec" not in r:
                r["ctrl_vec"] = vec
    return out


def summary(X: pd.DataFrame) -> dict:
    p = X.pnl.to_numpy()
    s = np.sort(p); cut = max(1, len(s) // 10); gl = -s[s < 0].sum()
    return dict(n=len(p), weeks=X.week.nunique(), mean=p.mean(), med=np.median(p),
                pf=(s[s > 0].sum() / gl) if gl else np.nan, frail=s[:-cut].sum() / max(len(s) - cut, 1),
                ctrl=X.ctrl.mean(), win=(p > 0).mean() * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    if a.reuse and OUT.exists():
        T = pd.read_parquet(OUT)
    else:
        syms = sorted(pd.read_parquet(WEEKS, columns=["sym"]).sym.unique())
        with ProcessPoolExecutor(a.workers) as ex:
            res = list(ex.map(one, syms, chunksize=4))
        T = pd.DataFrame([r for part in res for r in part])
        T.to_parquet(OUT)
    T["year"] = pd.to_datetime(T.ts).dt.year
    # контроль задержки: час входа — случайный из распределения задержек ТОГО ЖЕ (правило, триггер), без флага
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
    # инварианты
    assert T.delay.ge(0).all() and (T.loc[T.trig == "T0", "delay"] == 0).all()
    assert set(T.side) <= {"LONG", "SHORT"}
    print("═" * 118)
    print(f"СДЕЛОК {len(T)} · монет {T.sym.nunique()} · недель {T.week.nunique()} · {T.ts.min():%Y-%m-%d} → {T.ts.max():%Y-%m-%d}")
    print(T.groupby(["rule", "trig"]).size().unstack().to_string())

    rows = []
    for (rule, trig), X in T.groupby(["rule", "trig"]):
        for conf, mask in (("—", np.ones(len(X), bool)), ("волна", X.wave.values > 0),
                           ("структура", X.struct.values > 0), ("волна+структура", (X.wave.values > 0) & (X.struct.values > 0)),
                           ("нога OTE", X.leg.values > 0), ("нога OTE+структура", (X.leg.values > 0) & (X.struct.values > 0))):
            Y = X[mask]
            if len(Y) >= 30:
                rows.append({"rule": rule, "trig": trig, "conf": conf, **summary(Y),
                             **{f"y{y % 100}": Y[Y.year == y].pnl.mean() if (Y.year == y).sum() >= 15 else np.nan
                                for y in (2023, 2024, 2025, 2026)}})
    S = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print("\n" + "═" * 118)
    print("ВСЕ КОНФИГУРАЦИИ (net % на сделку; frail = среднее без верхних 10%; ctrl = вход с той же задержкой без флага)")
    print(S.round(2).sort_values(["rule", "trig", "conf"]).to_string(index=False))

    # ── ярус 2: нулевая модель всего перебора (лучшая конфигурация по среднему, n ≥ 50)
    from research_verify import card, normalize, search_null
    T["cfg"] = T.rule + "|" + T.trig
    N = normalize(T.assign(sym=T.sym), pnl="pnl")
    masks = {}
    for (rule, trig), idx in N.groupby(["rule", "trig"]).groups.items():
        base = np.zeros(len(N), bool); base[idx] = True
        for conf, m in (("—", base), ("волна", base & (N.wave.values > 0)), ("структура", base & (N.struct.values > 0)),
                        ("волна+структура", base & (N.wave.values > 0) & (N.struct.values > 0)),
                        ("нога OTE", base & (N.leg.values > 0)), ("нога OTE+структура", base & (N.leg.values > 0) & (N.struct.values > 0))):
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
    sn = search_null(N, search, name=f"касание×триггер×совпадение ({len(masks)} конфигураций)",
                     study="weekly_hypo_touch_09_10", n=200)

    # ── карточки трёх лучших по среднему: кандидат против остальных сделок ТОГО ЖЕ правила
    regimes = {2023: "бык", 2024: "нейтраль", 2025: "медведь", 2026: "медведь"}
    cards = []
    for lab in [k_ for k_ in S.assign(k=S.rule + "|" + S.trig + "|" + S.conf).sort_values("mean", ascending=False).k if k_ in masks][:3]:
        rule = lab.split("|")[0]
        P = N[N.rule == rule].reset_index(drop=True)
        cm = masks[lab][N.rule.values == rule]
        cards.append(card(P.rename(columns={}), cm, name=lab, study="weekly_hypo_touch_09_10",
                          geo=("stop_pct",), regimes=regimes))
    from research_verify import save_md
    save_md(cards, ROOT / "obsidian" / "Research" / "2026-10-09-Weekly-Hypo-Touch-Cards.md",
            "Недельные гипотезы: вход по касанию — карточки",
            f"Три лучшие из {len(masks)} конфигураций + ярус 2: {sn['text'][:160]}")


if __name__ == "__main__":
    main()
