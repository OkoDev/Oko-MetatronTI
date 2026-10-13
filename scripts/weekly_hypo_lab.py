# -*- coding: utf-8 -*-
"""НЕДЕЛЬНЫЕ ГИПОТЕЗЫ НА ИСТОРИИ (09.10.2026, Егор «1-3», п.3).

Вопрос. Боевой weekly-hypo с 13.07 пишет ~340 гипотез в неделю, их никто не скорил. Вероятности в правилах
(62/56/57/57 %) взяты из карты пивотов 01.07 — это доля пробоя/отбоя ПРИ КАСАНИИ уровня. Гипотеза же
скорится иначе: что коснётся РАНЬШЕ — цель или отмена. Это на истории не мерил никто.

Всё 1:1 с боем: classic-пивоты недели из прошлой недели, режим = наклон P (P недели > P прошлой → BULL),
зона открытия = `_zone` вотчера по первой цене недели, правила = `RULES` из scripts/weekly_hypothesis.py.
  · касание двумя способами: «как в бою» — закрытия 15m (вотчер смотрит цену раз в 15 мин) и «хай/лой» 15m
    (стоп и цель в одном баре → отмена, консервативно);
  · контроли: зеркальный режим (та же зона открытия, противоположный наклон P) и геометрический
    (блуждание без сноса: P(цель раньше) = d_отмены / (d_цели + d_отмены); на конечном окне занижает
    базу, когда цель ближе — то есть ПОДЫГРЫВАЕТ правилу, главный контроль — зеркальный);
  · выборка — НЕДЕЛИ (монеты одной недели ходят вместе): доля по неделе → среднее и бутстрап по неделям;
  · калибровка: досягаемость R1/S1/R2/S2 против карты 01.07 (R1 39 · S1 43 · R2 19 · S2 17 %);
  · сверка с форвардом weekly_hypothesis.db на общих неделях, построчно по (монета, неделя).
Данные: G:/oko_lab/tf/15m (Binance 1m → 15m, 477 монет); бой — BingX, уровни расходятся на доли процента.

Запуск: python scripts/weekly_hypo_lab.py [--workers 8]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
    pass

TF = Path("G:/oko_lab/tf/15m")
OUT = Path("G:/oko_lab/out/weekly_hypo_lab.parquet")
FWD_DB = Path(__file__).resolve().parent.parent / "oko_feed" / "weekly_hypothesis.db"
LEVELS = ("R1", "R2", "S1", "S2")
FULL = 672                     # 15m-баров в неделе
MIN_BARS = 640
COST = 0.35


def _zone(px, pp, r1, s1):      # копия weekly_pivot_watch._zone (там модуль с побочными импортами)
    if px >= r1:
        return "above_R1"
    if px >= pp:
        return "P..R1"
    if px >= s1:
        return "S1..P"
    return "below_S1"


def one(path: str) -> pd.DataFrame | None:
    d = pd.read_parquet(path)
    if len(d) < FULL * 4:
        return None
    sym = Path(path).stem
    per = d.index.to_period("W-SUN")
    g = d.groupby(per).agg(H=("high", "max"), L=("low", "min"), C=("close", "last"),
                           O1=("close", "first"), n=("close", "size"))
    g["turn"] = (d["volume"] * d["close"]).groupby(per).sum() / 7.0
    g = g.reindex(pd.period_range(g.index.min(), g.index.max(), freq="W-SUN"))
    P = (g.H + g.L + g.C) / 3.0
    rng = g.H - g.L
    lv = pd.DataFrame({"P": P, "R1": 2 * P - g.L, "S1": 2 * P - g.H, "R2": P + rng, "S2": P - rng}).shift(1)
    lv["P_prev"] = lv["P"].shift(1)
    lv["liq"] = g["turn"].shift(1)                         # оборот ПРОШЛОЙ недели — известен в пн 00:00
    ok = (g.n >= MIN_BARS) & (g.n.shift(1) >= MIN_BARS) & (g.n.shift(2) >= MIN_BARS) & lv.P_prev.notna()
    ok &= lv.S2 > 0                     # недельный размах больше P (памп мемкоина) → S2 ≤ 0, геометрия бессмысленна
    wk = g[ok].join(lv[ok])
    if wk.empty:
        return None
    # бары недель с уровнями
    bar_w = per.isin(wk.index)
    b = d[bar_w]
    bper = per[bar_w]
    mins = ((b.index - bper.start_time).total_seconds() // 60).astype(int)
    # первая цена недели = закрытие первого 15m-бара (вотчер снимает её в первом проходе после пн 00:00)
    first_min = pd.Series(mins, index=bper).groupby(level=0).min()
    rows = []
    lvb = wk.loc[bper, list(LEVELS)].to_numpy()            # уровни, протянутые на бары
    cl, hi, lo = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
    first = {}
    for j, L in enumerate(LEVELS):
        up = L.startswith("R")
        hit_snap = cl >= lvb[:, j] if up else cl <= lvb[:, j]
        hit_hl = hi >= lvb[:, j] if up else lo <= lvb[:, j]
        for mode, hit in (("snap", hit_snap), ("hl", hit_hl)):
            m = np.where(hit, mins, np.inf)
            # «не коснулся» = NaN, НЕ inf: inf проходит notna() → первая версия дала досягаемость 100% (калибровка поймала)
            first[f"t_{L}_{mode}"] = pd.Series(m, index=bper).groupby(level=0).min().replace(np.inf, np.nan)
    T = pd.DataFrame(first)
    wk = wk.join(T)
    wk["first_min"] = first_min
    for w, r in wk.iterrows():
        if r.first_min != 0:
            continue
        zone = _zone(r.O1, r.P, r.R1, r.S1)
        rows.append({"sym": sym, "week": w.start_time, "zone": zone,
                     "regime": "BULL" if r.P > r.P_prev else "BEAR",
                     "open": r.O1, "close": r.C, "liq": r.liq,
                     **{L: r[L] for L in ("P",) + LEVELS},
                     **{c: r[c] for c in T.columns}})
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────── правила и исходы ───────────────────────────
RULES = {   # 1:1 с scripts/weekly_hypothesis.RULES (assert ниже сверяет)
    ("BEAR", "S1..P"): ("bear_break_s1", "SHORT", "S1", "S2", "R1"),
    ("BEAR", "P..R1"): ("bear_fade_r1", "SHORT", "S1", "S2", "R2"),
    ("BULL", "P..R1"): ("bull_break_r1", "LONG", "R1", "R2", "S1"),
    ("BULL", "S1..P"): ("bull_hold_s1", "LONG", "R1", "R2", "S2"),
}


def outcome(W: pd.DataFrame, target: str, inval: str, mode: str) -> pd.Series:
    t, i = W[f"t_{target}_{mode}"], W[f"t_{inval}_{mode}"]
    res = np.where(t.isna() & i.isna(), "NONE",
          np.where(i.isna() | (t < i), "TARGET", np.where(t == i, "AMBIG", "INVALID")))
    res = np.where(t.isna() & i.notna(), "INVALID", res)
    return pd.Series(res, index=W.index)


def week_mean(W: pd.DataFrame, col: str, n_boot: int = 2000, seed: int = 0):
    """Доля по неделям → среднее и 90%-интервал бутстрапа по неделям."""
    per = W.groupby("week")[col].mean()
    if len(per) < 3:
        return per.mean(), np.nan, np.nan, len(per)
    rng = np.random.default_rng(seed)
    bs = [rng.choice(per.values, len(per)).mean() for _ in range(n_boot)]
    return per.mean(), np.quantile(bs, 0.05), np.quantile(bs, 0.95), len(per)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", action="store_true", help="взять готовый OUT, не пересчитывать")
    a = ap.parse_args()

    from scripts.weekly_hypothesis import RULES as LIVE
    for k, (code, side, tg, st, inv) in RULES.items():
        lr = LIVE[k]
        assert (lr["code"], lr["side"], lr["target"], lr["stretch"], lr["inval"]) == (code, side, tg, st, inv), k

    if a.reuse and OUT.exists():
        D = pd.read_parquet(OUT)
    else:
        files = sorted(str(p) for p in TF.glob("*.parquet"))
        with ProcessPoolExecutor(a.workers) as ex:
            parts = [x for x in ex.map(one, files, chunksize=4) if x is not None]
        D = pd.concat(parts, ignore_index=True)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        D.to_parquet(OUT)
    D["year"] = D.week.dt.year

    # ── golden-case: исход и зона на руках
    g = pd.DataFrame({"t_S1_hl": [60, 60, np.nan, 60, np.nan], "t_R1_hl": [120, 30, 30, 60, np.nan]})
    assert outcome(g, "S1", "R1", "hl").tolist() == ["TARGET", "INVALID", "INVALID", "AMBIG", "NONE"]
    assert _zone(100, 99, 102, 97) == "P..R1" and _zone(98, 99, 102, 97) == "S1..P"

    # ── 1. инвентаризация
    print("═" * 100)
    print(f"ИНВЕНТАРИЗАЦИЯ: монет {D.sym.nunique()} · монето-недель {len(D)} · недель {D.week.nunique()} · "
          f"{D.week.min():%Y-%m-%d} → {D.week.max():%Y-%m-%d}")
    D["wret"] = np.log(D.close / D.open)
    yr = D.groupby("year").agg(coins=("sym", "nunique"), cw=("sym", "size"), weeks=("week", "nunique"),
                               med_wret=("wret", "median"), bull=("regime", lambda s: (s == "BULL").mean()))
    yr["med_wret"] = (yr.med_wret * 100).round(2)
    yr["bull"] = (yr.bull * 100).round(0)
    yr["режим года"] = np.where(yr.med_wret > 0.3, "бык", np.where(yr.med_wret < -0.3, "медведь", "нейтраль"))
    print(yr.rename(columns={"coins": "монет", "cw": "мон-нед", "weeks": "недель",
                             "med_wret": "медиана нед. %", "bull": "BULL-недель %"}).to_string())

    # ── 2. калибровка с картой 01.07 (хай/лой, все полные недели, 2022–2026)
    cal = D[(D.year >= 2022)]
    reach = {L: cal[f"t_{L}_hl"].notna().mean() * 100 for L in LEVELS}
    print("\nКАЛИБРОВКА досягаемости (хай/лой) против карты 01.07 (R1 39 · R2 19 · S1 43 · S2 17):  "
          + " · ".join(f"{L} {v:.0f}" for L, v in reach.items()))
    assert all(5 < v < 80 for v in reach.values()), "досягаемость вне разумного — ошибка в касаниях"
    for L in LEVELS:                     # касание не раньше первого бара недели и не позже последнего
        t = D[f"t_{L}_hl"].dropna()
        assert t.between(0, FULL * 15).all(), L

    # ── 3. правила: доля «цель раньше» против двух контролей
    for mode in ("snap", "hl"):
        print("\n" + "═" * 100)
        print(f"ПРАВИЛА · касание «{'как в бою: закрытия 15m' if mode == 'snap' else 'хай/лой 15m'}» · "
              f"доля по НЕДЕЛЯМ, [90% бутстрап по неделям]")
        print(f"{'правило':15}{'n мон-нед':>10}{'недель':>8}  {'цель раньше':>22}  {'зеркальный режим':>22}"
              f"  {'геом. база':>10}  {'нет касаний':>11}  {'сбылось из всех':>15}")
        for (reg, zone), (code, side, tg, st, inv) in RULES.items():
            W = D[(D.regime == reg) & (D.zone == zone)].copy()
            M = D[(D.regime != reg) & (D.zone == zone)].copy()      # зеркало: та же зона, режим противоположный
            for X in (W, M):
                X["res"] = outcome(X, tg, inv, mode)
                X["dec"] = X.res.isin(["TARGET", "INVALID", "AMBIG"])
                X["win"] = (X.res == "TARGET").astype(float)
                X["geo"] = np.abs(np.log(X[inv] / X.open)) / (np.abs(np.log(X[tg] / X.open)) + np.abs(np.log(X[inv] / X.open)))
            wd, md = W[W.dec], M[M.dec]
            m1, lo1, hi1, nw = week_mean(wd, "win")
            m2, lo2, hi2, _ = week_mean(md, "win")
            gm = week_mean(wd, "geo")[0]
            none = (W.res == "NONE").mean()
            allw = week_mean(W, "win")[0]
            print(f"{code:15}{len(W):>10}{nw:>8}  {m1*100:5.1f} [{lo1*100:4.1f}–{hi1*100:4.1f}]      "
                  f"{m2*100:5.1f} [{lo2*100:4.1f}–{hi2*100:4.1f}]      {gm*100:5.1f}      {none*100:6.1f}%      {allw*100:6.1f}%")
            if mode == "hl":
                print(f"{'':15}баланс геометрии: d_цели/d_отмены правило {np.nanmedian(np.abs(np.log(wd[tg]/wd.open))/np.abs(np.log(wd[inv]/wd.open))):.2f}"
                      f" · зеркало {np.nanmedian(np.abs(np.log(md[tg]/md.open))/np.abs(np.log(md[inv]/md.open))):.2f} · AMBIG {(W.res=='AMBIG').mean()*100:.1f}%")

    # ── 4. срезы (хай/лой): год · ликвидность
    print("\n" + "═" * 100)
    print("СРЕЗЫ (хай/лой): доля «цель раньше» среди решённых недель, правило − зеркало (п.п.); в скобках недель")
    D["liq_half"] = np.where(D.liq >= D.groupby("week").liq.transform("median"), "ликв", "неликв")
    hdr = sorted(D.year.unique())
    print(f"{'правило':15}" + "".join(f"{y:>12}" for y in hdr) + f"{'ликв':>12}{'неликв':>12}")
    for (reg, zone), (code, side, tg, st, inv) in RULES.items():
        cells = []
        for key, val in [("year", y) for y in hdr] + [("liq_half", "ликв"), ("liq_half", "неликв")]:
            out = []
            for X in (D[(D.regime == reg) & (D.zone == zone) & (D[key] == val)],
                      D[(D.regime != reg) & (D.zone == zone) & (D[key] == val)]):
                X = X.assign(res=outcome(X, tg, inv, "hl"))
                X = X[X.res.isin(["TARGET", "INVALID", "AMBIG"])].assign(win=lambda z: (z.res == "TARGET").astype(float))
                out.append((week_mean(X, "win")[0], X.week.nunique()) if len(X) else (np.nan, 0))
            (a1, n1), (a2, _) = out
            cells.append(f"{(a1-a2)*100:+6.1f} ({n1:>3})" if n1 >= 5 else f"{'—':>12}")
        print(f"{code:15}" + "".join(f"{c:>12}" for c in cells))

    # ── 5. деньги наивной сделки (вход по открытию недели, стоп = отмена, цель = цель, иначе выход по закрытию недели)
    print("\n" + "═" * 100)
    print(f"ДЕНЬГИ наивной сделки, хай/лой, кост {COST}% (карта 01.07: «direction-pivot в лоб не монетизируется»)")
    for (reg, zone), (code, side, tg, st, inv) in RULES.items():
        W = D[(D.regime == reg) & (D.zone == zone)].copy()
        W["res"] = outcome(W, tg, inv, "hl")
        s = 1 if side == "LONG" else -1
        ex = np.where(W.res == "TARGET", W[tg], np.where(W.res.isin(["INVALID", "AMBIG"]), W[inv], W.close))
        W["pnl"] = s * (ex - W.open) / W.open * 100 - COST
        p = W.pnl.sort_values()
        top = p.iloc[int(len(p) * 0.9):].sum()
        pf = p[p > 0].sum() / -p[p < 0].sum()
        by_y = W.groupby("year").pnl.mean().round(2).to_dict()
        print(f"{code:15} n {len(W):>6} · медиана {p.median():+.2f}% · среднее {p.mean():+.3f}% · PF {pf:.2f} · "
              f"доля>0 {(p > 0).mean()*100:.0f}% · без верхних 10% {p.sum()-top:+.0f}% · по годам {by_y}")

    # ── 6. сверка с форвардом: общие (монета, неделя)
    print("\n" + "═" * 100)
    if FWD_DB.exists():
        c = sqlite3.connect(f"file:{FWD_DB.as_posix()}?mode=ro", uri=True)
        F = pd.read_sql("SELECT symbol, week_start, regime, open_zone, hypo_code, status FROM weekly_hypothesis", c)
        c.close()
        cur = pd.Timestamp.utcnow().tz_localize(None).normalize()
        cur = cur - pd.Timedelta(days=cur.weekday())
        F["week"] = pd.to_datetime(F.week_start)
        F = F[F.week < cur].copy()                              # только закрытые недели
        F["status"] = F.status.replace({"OPEN": "NONE", "STRETCH": "TARGET"})
        F["sym"] = F.symbol.str.split("/").str[0] + "USDT"
        print(f"ФОРВАРД (закрытые недели {F.week.min():%d.%m} → {F.week.max():%d.%m}, OPEN прошлых недель = NONE):")
        for code, X in F.groupby("hypo_code"):
            dec = X[X.status.isin(["TARGET", "INVALID"])]
            print(f"  {code:15} n {len(X):>5} · цель раньше {(dec.status == 'TARGET').mean()*100:5.1f}% из решённых · "
                  f"NONE {(X.status == 'NONE').mean()*100:4.1f}% · недель {X.week.nunique()}")
        J = F.merge(D, on=["sym", "week"], how="inner", suffixes=("", "_bt"))
        if len(J):
            agree_rule = (J.open_zone == J.zone) & (J.regime == J.regime_bt)
            print(f"  общих (монета, неделя) с бэктестом: {len(J)} · совпали режим и зона: {agree_rule.mean()*100:.0f}%")
            JJ = J[agree_rule].copy()
            st = []
            for (reg, zone), (code, side, tg, stt, inv) in RULES.items():
                X = JJ[JJ.hypo_code == code]
                if len(X):
                    st.append(pd.DataFrame({"fwd": X.status, "bt": outcome(X, tg, inv, "snap").replace({"AMBIG": "INVALID"})}))
            S = pd.concat(st) if st else pd.DataFrame(columns=["fwd", "bt"])
            print(f"  статус форварда = статус бэктеста «как в бою»: {(S.fwd == S.bt).mean()*100:.0f}% из {len(S)}")
            print(pd.crosstab(S.fwd, S.bt, margins=True).to_string())


if __name__ == "__main__":
    main()
