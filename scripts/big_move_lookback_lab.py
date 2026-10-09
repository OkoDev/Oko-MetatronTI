# -*- coding: utf-8 -*-
"""ЧТО БЫЛО ДО БОЛЬШИХ ХОДОВ — обратный замер (Егор 09.10: «замер!» · «я до сих пор не верю, что самый простой набор
WT/пивот/ATR, с которого начинался проект, не даёт денег» · «все гипотезы пора ставить под большие сомнения»).

Раньше мы всегда шли ВПЕРЁД от сигнала. Здесь — НАЗАД от исхода: берём все начала больших ходов и смотрим, что горело
в момент начала и за 6 часов до него. Потом обратная сторона: как часто это же горит без хода и сколько денег даёт.

ЗАДАНО ДО ПРОГОНА:
  · ДАННЫЕ: журнал общего состояния 1h (G:/oko_lab/joint/1h, 469 монет, 2023-01 → 2026-10-06), причинные флаги (старший
    ТФ — с закрытого бара). Исход fwd_H: вход по open СЛЕДУЮЩЕГО бара, выход по close через H ч, % для лонга, без коста.
  · БОЛЬШОЙ ХОД: fwd_24 ≥ +15% (вверх) / ≤ −15% (вниз). Часы одного хода (разрыв ≤ 24 ч) — один эпизод; его начало
    t* — час с наибольшим |fwd_24| (лучший вход). Чувствительность — порог 10%.
  · ЧТО СМОТРИМ: все булевы признаки журнала + заранее заданный ПРОСТОЙ НАБОР (как сканер конфлюэнции, с которого
    начинался проект): WT — кросс вверх при перепроданности за 6 ч · ПИВОТ — close в 0.5% НАД уровнем 1D/1W/1M (любой
    из PP/S1-3/R1-3) · ATR — флип ATR-тренда вверх; каждый в окне [t−6, t]; пары и тройка. Зеркально для шорта.
  · «ДО»: признак горит в t* (момент) и хоть раз в [t*−6, t*] (окно).
  · КОНТРОЛЬ: ожидаемая частота признака в тех же СТРАТАХ (год × квинтиль ATR% × половина ликвидности): большие ходы
    живут в волатильных монетах, без страт любой «волатильный» признак выглядел бы предвестником. Подъём = набл./ожид.
  · ОБРАТНАЯ СТОРОНА (по всем часам): доля часов с признаком, после которых пришёл большой ход, и деньги (средний fwd
    по стороне − 0.35) — против ожидаемого в тех же стратах, т.е. прирост сверх волатильности, года и ликвидности.
  · Гипотезы: 14 заранее (простой набор: 7 × 2 стороны); остальные признаки — разведка, вердикта по ним нет.

Запуск: python scripts/big_move_lookback_lab.py [процессов]
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

JOURNAL = Path("G:/oko_lab/joint/1h")
OUT = Path("G:/oko_lab/out/big_move_lookback.pkl")
COST, WIN, GAP = 0.35, 7, 24                 # окно [t−6, t] = 7 баров
THRS = (15.0, 10.0)
YEARS = (2023, 2024, 2025, 2026)
NS = len(YEARS) * 10                          # страты: год × 5 квинтилей ATR% × 2 половины ликвидности
LV, PTF = ("PP", "S1", "S2", "S3", "R1", "R2", "R3"), ("1D", "1W", "1M")
SET_KEYS = ("wt", "piv", "atr", "wt_piv", "wt_atr", "piv_atr", "all3")


def bool_columns() -> list[str]:
    J = pd.read_parquet(JOURNAL / "BTCUSDT.parquet")
    skip = ("fwd_", "mfe_", "mae_", "geo_")
    return [c for c in J.columns if not c.startswith(skip) and c != "sym"
            and set(pd.unique(J[c].dropna())) <= {0, 1, True, False} and J[c].notna().any()]


def episodes(f24: np.ndarray, up: bool, thr: float, gap: int = GAP) -> np.ndarray:
    """Начала эпизодов большого хода: группы часов с |fwd_24| ≥ thr, разрыв ≤ gap; t* — лучший час группы."""
    hit = np.flatnonzero(f24 >= thr) if up else np.flatnonzero(f24 <= -thr)
    out, i = [], 0
    while i < len(hit):
        j = i
        while j + 1 < len(hit) and hit[j + 1] - hit[j] <= gap:
            j += 1
        seg = hit[i:j + 1]
        out.append(seg[np.argmax(f24[seg])] if up else seg[np.argmin(f24[seg])])
        i = j + 1
    return np.asarray(out, int)


def _anyw(x: pd.Series) -> pd.Series:
    return x.astype(float).rolling(WIN, min_periods=1).max().fillna(0) > 0.5


def simple_set(J: pd.DataFrame) -> pd.DataFrame:
    def col(c):
        return (J[c].fillna(0) > 0.5) if c in J.columns else pd.Series(False, index=J.index)
    sup = pd.Series(False, index=J.index)
    res = pd.Series(False, index=J.index)
    for lv in LV:
        for tf in PTF:
            near = col(f"pivot_near_{lv}_{tf}")
            sup |= near & col(f"pivot_above_{lv}_{tf}")      # close в 0.5% НАД уровнем — поддержка для лонга
            res |= near & col(f"pivot_below_{lv}_{tf}")      # close в 0.5% ПОД уровнем — сопротивление для шорта
    parts = {"L": (col("wt_cross_up_1h") & _anyw(col("wt_os_1h")), sup, col("atr_cross_up_1h")),
             "S": (col("wt_cross_down_1h") & _anyw(col("wt_ob_1h")), res, col("atr_cross_down_1h"))}
    out = {}
    for s, (w, p, a) in parts.items():
        W, P, A = _anyw(w), _anyw(p), _anyw(a)
        out.update({f"set_{s}_wt": W, f"set_{s}_piv": P, f"set_{s}_atr": A, f"set_{s}_wt_piv": W & P,
                    f"set_{s}_wt_atr": W & A, f"set_{s}_piv_atr": P & A, f"set_{s}_all3": W & P & A})
    return pd.DataFrame(out).astype(np.float32)


def per_coin(args):
    f, cols, vq, lq = args
    import logging
    logging.disable(logging.CRITICAL)
    J = pd.read_parquet(f)
    if len(J) < 500:
        return None
    J.index = J.index.tz_convert(None) if J.index.tz is not None else J.index
    S = simple_set(J)
    X0 = pd.concat([J.reindex(columns=cols).astype(np.float32), S], axis=1).fillna(0)
    feats = list(X0.columns)
    X = (X0.values > 0.5)
    Xw = (X0.rolling(WIN, min_periods=1).max().values > 0.5)
    f4, f24, f72 = (J[c].values.astype(float) for c in ("fwd_4", "fwd_24", "fwd_72"))
    atr, liq = J["atr_pct"].values.astype(float), J["liq"].values.astype(float)
    yr = J.index.year.values
    valid = np.isfinite(f4) & np.isfinite(f24) & np.isfinite(f72) & np.isfinite(atr) & np.isfinite(liq) & np.isin(yr, YEARS)
    st = np.full(len(J), -1)
    vb, lb = np.searchsorted(vq, atr), (liq > lq).astype(int)
    st[valid] = (yr[valid] - YEARS[0]) * 10 + vb[valid] * 2 + lb[valid]
    F = len(feats)
    R = {"feats": feats, "sym": str(J["sym"].iloc[0]) if "sym" in J.columns else f.stem,
         "base_n": np.zeros(NS), "base_hits": np.zeros((2, NS, F)), "up15": np.zeros((NS, F)), "dn15": np.zeros((NS, F)),
         "pos": np.zeros((NS, F)), "sum": np.zeros((3, NS, F)), "b_up15": np.zeros(NS), "b_dn15": np.zeros(NS),
         "b_pos": np.zeros(NS), "b_sum": np.zeros((3, NS)),
         "ev_n": np.zeros((2, 2, NS)), "ev_hits": np.zeros((2, 2, 2, NS, F)), "ev_rows": []}
    fw = (f4, f24, f72)
    for s in np.unique(st[st >= 0]):
        m = st == s
        Xm = X[m]
        R["base_n"][s] = m.sum()
        R["base_hits"][0, s] = Xm.sum(0)
        R["base_hits"][1, s] = Xw[m].sum(0)
        R["up15"][s] = Xm[f24[m] >= 15].sum(0)
        R["dn15"][s] = Xm[f24[m] <= -15].sum(0)
        R["pos"][s] = Xm[f24[m] > 0].sum(0)
        R["b_up15"][s], R["b_dn15"][s], R["b_pos"][s] = (f24[m] >= 15).sum(), (f24[m] <= -15).sum(), (f24[m] > 0).sum()
        for h, v in enumerate(fw):
            R["sum"][h, s] = (Xm * v[m][:, None]).sum(0)
            R["b_sum"][h, s] = v[m].sum()
    f24v = np.where(valid, f24, 0.0)
    for ti, thr in enumerate(THRS):
        for si, up in enumerate((True, False)):
            for k in episodes(f24v, up, thr):
                if st[k] < 0:
                    continue
                R["ev_n"][ti, si, st[k]] += 1
                R["ev_hits"][ti, si, 0, st[k]] += X[k]
                R["ev_hits"][ti, si, 1, st[k]] += Xw[k]
                if ti == 0:
                    R["ev_rows"].append((R["sym"], J.index[k], "UP" if up else "DOWN", round(float(f24[k]), 1),
                                         round(float(atr[k]), 2), {c: bool(Xw[k, feats.index(c)]) for c in S.columns}))
    # строки для карточки денег простого набора: все часы с компонентом набора + систематическая выборка (каждый 6-й час)
    keep = valid & ((S.values > 0.5).any(1) | (np.arange(len(J)) % 6 == 0))
    R["rows"] = pd.DataFrame({"sym": R["sym"], "ts": J.index[keep], "liq": liq[keep], "f4": f4[keep], "f24": f24[keep],
                              "f72": f72[keep], "drift": J["mkt_drift30"].values[keep] if "mkt_drift30" in J else np.nan,
                              "base": (np.arange(len(J)) % 6 == 0)[keep],
                              **{c: S[c].values[keep] > 0.5 for c in S.columns}})
    return R


def _golden():
    f = np.zeros(80)
    f[[1, 2, 3]] = [16, 20, 17]
    f[40] = 15
    assert list(episodes(f, True, 15)) == [2, 40]
    f2 = -f
    assert list(episodes(f2, False, 15)) == [2, 40]
    J = pd.DataFrame({"wt_cross_up_1h": [0, 0, 1, 0.], "wt_os_1h": [1, 0, 0, 0.], "pivot_near_S1_1D": [0, 0, 1, 0.],
                      "pivot_above_S1_1D": [0, 0, 1, 0.], "atr_cross_up_1h": [0, 1, 0, 0.]},
                     index=pd.date_range("2025-01-01", periods=4, freq="h"))
    S = simple_set(J)
    assert S["set_L_all3"].tolist() == [0, 0, 1, 1] and S["set_S_all3"].sum() == 0
    J.loc[J.index[2], "pivot_above_S1_1D"] = 0                 # уровень НАД ценой — не поддержка
    assert simple_set(J)["set_L_piv"].sum() == 0


def agg(parts):
    P = [p for p in parts if p]
    feats = P[0]["feats"]
    assert all(p["feats"] == feats for p in P)
    A = {k: sum(p[k] for p in P) for k in P[0] if isinstance(P[0][k], np.ndarray)}
    A["feats"], A["n_coins"] = feats, len(P)
    A["ev_rows"] = [r for p in P for r in p["ev_rows"]]
    A["coin"] = [(p["sym"], p["ev_n"][0], p["ev_hits"][0]) for p in P]
    A["rows"] = pd.concat([p["rows"] for p in P], ignore_index=True)
    return A


def lift_table(A, ti, si, wi, base_rate=None):
    br = A["base_hits"][wi] / np.maximum(A["base_n"], 1)[:, None]          # частота признака в страте
    obs = A["ev_hits"][ti, si, wi].sum(0)
    exp = (A["ev_n"][ti, si][:, None] * br).sum(0)
    by_year = []
    for y in range(len(YEARS)):
        sl = slice(y * 10, y * 10 + 10)
        o = A["ev_hits"][ti, si, wi, sl].sum(0)
        e = (A["ev_n"][ti, si, sl][:, None] * br[sl]).sum(0)
        by_year.append(np.where(e > 0, o / np.maximum(e, 1e-9), np.nan))
    return obs, exp, np.array(by_year)


def forward_table(A, side_sign):
    """Обратная сторона по всем часам: доля больших ходов и деньги при признаке против ожидаемого в стратах."""
    n_f = A["base_hits"][0].sum(0)
    bn = np.maximum(A["base_n"], 1)
    ev = A["up15"] if side_sign > 0 else A["dn15"]
    bev = A["b_up15"] if side_sign > 0 else A["b_dn15"]
    p_obs = ev.sum(0) / np.maximum(n_f, 1)
    p_exp = (A["base_hits"][0] * (bev / bn)[:, None]).sum(0) / np.maximum(n_f, 1)
    money = {}
    for h, nm in enumerate(("4ч", "24ч", "72ч")):
        m_obs = side_sign * A["sum"][h].sum(0) / np.maximum(n_f, 1) - COST
        m_exp = side_sign * (A["base_hits"][0] * (A["b_sum"][h] / bn)[:, None]).sum(0) / np.maximum(n_f, 1) - COST
        money[nm] = (m_obs, m_exp)
    return n_f, p_obs, p_exp, money


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    _golden()
    if OUT.exists():
        A = pd.read_pickle(OUT)
    else:
        cols = bool_columns()
        files = sorted(JOURNAL.glob("*.parquet"))
        with Pool(procs) as pool:
            sm = pool.map(_sample_q, files)
        atr_all = np.concatenate([s[0] for s in sm])
        liq_all = np.concatenate([s[1] for s in sm])
        vq = np.quantile(atr_all, [0.2, 0.4, 0.6, 0.8])
        lq = float(np.median(liq_all))
        print(f"квинтили ATR% {np.round(vq, 3)} · медиана ликвидности {lq:,.0f}")
        with Pool(procs) as pool:
            parts = pool.map(per_coin, [(f, cols, vq, lq) for f in files])
        A = agg(parts)
        A["vq"], A["lq"] = vq, lq
        pd.to_pickle(A, OUT)
    report(A)
    return 0


def _sample_q(f):
    J = pd.read_parquet(f, columns=["atr_pct", "liq"])
    J = J.iloc[::24]
    return J["atr_pct"].dropna().values, J["liq"].dropna().values


def report(A):
    feats = np.array(A["feats"])
    fi = {c: i for i, c in enumerate(feats)}
    R = A["rows"]
    print(f"\nИНВЕНТАРИЗАЦИЯ: монет {A['n_coins']} · часов в замере {int(A['base_n'].sum()):,} · признаков {len(feats)}")
    for ti, thr in enumerate(THRS):
        print(f"  эпизодов хода ≥{thr:g}% за 24 ч: вверх {int(A['ev_n'][ti, 0].sum()):,} · вниз {int(A['ev_n'][ti, 1].sum()):,}"
              f" · по годам вверх {[int(A['ev_n'][ti, 0, y*10:y*10+10].sum()) for y in range(4)]}"
              f" вниз {[int(A['ev_n'][ti, 1, y*10:y*10+10].sum()) for y in range(4)]}")
    b = R[R.base]
    print("  режим лет (медиана дрейфа рынка 30д, выборка часов):",
          " · ".join(f"{y} {v:+.1f}" for y, v in b.groupby(b.ts.dt.year).drift.median().items()))
    print("  база: доля часов, после которых ход ≥15% вверх / вниз:",
          f"{A['b_up15'].sum() / A['base_n'].sum() * 100:.2f}% / {A['b_dn15'].sum() / A['base_n'].sum() * 100:.2f}%")
    print("  сырые строки (начала ходов):")
    ev = A["ev_rows"]
    for r in [ev[i] for i in np.linspace(0, len(ev) - 1, 6).astype(int)]:
        on = [k.replace("set_", "") for k, v in r[5].items() if v]
        print(f"    {r[0]:<16} {r[1]:%Y-%m-%d %H:%M} {r[2]:<4} fwd24 {r[3]:+6.1f}% ATR {r[4]:.2f}% · горело: {on or '—'}")

    # ── ПРОСТОЙ НАБОР — заранее заданные 14 гипотез ─────────────────────────────────────
    print("\n" + "=" * 110 + "\nПРОСТОЙ НАБОР WT / ПИВОТ / ATR — что было в окне 6 ч до начала хода ≥15% (подъём = набл./ожид. в стратах)")
    for s, si, sg in (("L", 0, 1), ("S", 1, -1)):
        side = "ЛОНГ: ходы ВВЕРХ" if s == "L" else "ШОРТ: ходы ВНИЗ"
        obs, exp, yrs = lift_table(A, 0, si, 1)
        n_ev = A["ev_n"][0, si].sum()
        n_f, p_obs, p_exp, money = forward_table(A, sg)
        print(f"\n {side} ({int(n_ev):,} эпизодов)")
        print(f"  {'набор':<9}{'в окне до хода':>16}{'ожид.':>8}{'подъём':>8}{'  по годам':<26}"
              f"{'часов с набором':>16}{'ход≥15% после':>15}{'ожид.':>7}{'24ч − кост':>12}{'ожид.':>8}{'Δ':>7}{'72ч Δ':>8}")
        for k in SET_KEYS:
            c = fi[f"set_{s}_{k}"]
            yy = " ".join(f"{v:.2f}" for v in yrs[:, c])
            m24o, m24e = money["24ч"][0][c], money["24ч"][1][c]
            m72o, m72e = money["72ч"][0][c], money["72ч"][1][c]
            print(f"  {k:<9}{obs[c] / n_ev * 100:>15.1f}%{exp[c] / n_ev * 100:>7.1f}%{obs[c] / max(exp[c], 1e-9):>8.2f}  {yy:<24}"
                  f"{int(n_f[c]):>16,}{p_obs[c] * 100:>14.2f}%{p_exp[c] * 100:>6.2f}%{m24o:>+12.2f}{m24e:>+8.2f}{m24o - m24e:>+7.2f}"
                  f"{m72o - m72e:>+8.2f}")
    # ── РАЗВЕДКА: все признаки ───────────────────────────────────────────────────────────
    print("\n" + "=" * 110 + "\nРАЗВЕДКА (без вердикта): признаки с наибольшим подъёмом в окне 6 ч до хода ≥15%, ≥200 попаданий, ≥3 из 4 лет > 1")
    for si, sg, side in ((0, 1, "ВВЕРХ"), (1, -1, "ВНИЗ")):
        obs, exp, yrs = lift_table(A, 0, si, 1)
        n_ev = A["ev_n"][0, si].sum()
        lift = obs / np.maximum(exp, 1e-9)
        n_f, p_obs, p_exp, money = forward_table(A, sg)
        ok = (obs >= 200) & ((yrs > 1).sum(0) >= 3) & ~np.char.startswith(feats.astype(str), "set_")
        order = np.argsort(-np.where(ok, lift, -1))[:25]
        print(f"\n ходы {side}: {int(n_ev):,} эпизодов")
        print(f"  {'признак':<36}{'в окне':>8}{'ожид.':>8}{'подъём':>8}{'  годы':<26}{'ход≥15% после':>15}{'ожид.':>7}{'24ч Δ':>8}{'72ч Δ':>8}")
        for c in order:
            if not ok[c]:
                break
            yy = " ".join(f"{v:.2f}" for v in yrs[:, c])
            print(f"  {feats[c][:35]:<36}{obs[c] / n_ev * 100:>7.1f}%{exp[c] / n_ev * 100:>7.1f}%{lift[c]:>8.2f}  {yy:<24}"
                  f"{p_obs[c] * 100:>14.2f}%{p_exp[c] * 100:>6.2f}%{money['24ч'][0][c] - money['24ч'][1][c]:>+8.2f}"
                  f"{money['72ч'][0][c] - money['72ч'][1][c]:>+8.2f}")
    # ── чувствительность: порог 10% для простого набора ──────────────────────────────────
    print("\nчувствительность — порог хода 10%, подъём простого набора в окне 6 ч:")
    for s, si in (("L", 0), ("S", 1)):
        obs, exp, _ = lift_table(A, 1, si, 1)
        print(f"  {s}: " + " · ".join(f"{k} {obs[fi[f'set_{s}_{k}']] / max(exp[fi[f'set_{s}_{k}']], 1e-9):.2f}" for k in SET_KEYS))


if __name__ == "__main__":
    raise SystemExit(main())
