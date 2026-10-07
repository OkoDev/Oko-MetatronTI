# -*- coding: utf-8 -*-
"""ТРИГГЕР × НАБОРЫ ДРУГИХ СФЕР на полном потоке (Егор 07.10: «при WT OS есть ли SMC-наборы интересные,
что в состояниях пивотов и где мы в волне или OTE»).

Источник — журнал общего состояния `scripts/joint_state_journal.py` (каждый закрытый час, 503 монеты).

ЗАДАНО ДО ПРОГОНА (не менять после первого взгляда на OOS):
  · ТРИГГЕР = событие (вход в состояние), не состояние: WT 1h/4h вошёл в OS → LONG, в OB → SHORT;
    на монету не чаще раза в 24 ч (сделки одной монеты не перекрываются на горизонте исхода)
  · ИСХОД = сторона × fwd_24 − 0.35 (линейка коста). fwd_4 / fwd_72 — только справочно
  · НАБОРЫ: флаги матрицы ==1; числовые — нижняя/верхняя треть ПО IS; волна (есть пятёрка, та же /
    встречная сторона, полное ядро, откат 0–0.382 / 0.382–0.618 / 0.618–0.79 OTE волны / >0.79);
    режим; позиционирование. Одиночки → пары из 30 лучших одиночек IS
  · ВРЕМЯ: IS 2023–2024 · OOS 2025 (один раз) · отложено 2026
  · ОТБОР НА IS: поддержка ≥ max(200, 1%) событий и ≥30 дней (1%, а не 5%: пятёрка ядра видна в ~9% часов), среднее > 0, ранг по z = Δ/σ·√n
    к базе триггера; в OOS идут 20 лучших одиночек + 20 лучших пар
  · ВЫЖИЛ В OOS: среднее > 0 и Δ к базе триггера > 0
  · ЯРУС 2: тот же конвейер IS→OOS на исходах, сдвинутых во времени внутри года (research_verify),
    счёт = число выживших; ЯРУС 1: карточка выживших на IS+OOS, прирост сверх режима и волатильности

Запуск:  python scripts/joint_trigger_search.py events          — выжимка событий из журнала
         python scripts/joint_trigger_search.py search [триггер] [n_null]
"""
from __future__ import annotations

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402

JOURNAL = Path("G:/oko_lab/joint/1h")
EVENTS = Path("G:/oko_lab/joint/events")
COST, H, COOLDOWN_H = 0.35, 24, 24
IS_Y, OOS_Y, HOLD_Y = (2023, 2024), (2025,), (2026,)
TRIGGERS = {                                              # имя → (колонка состояния, сторона)
    "wt_os_1h": ("wt_os_1h", "LONG"), "wt_ob_1h": ("wt_ob_1h", "SHORT"),
    "wt_os_4h": ("wt_os_4h__from_4h", "LONG"), "wt_ob_4h": ("wt_ob_4h__from_4h", "SHORT"),
}
OUTCOMES = ("fwd_4", "fwd_24", "fwd_72", "mfe_24", "mae_24")
META = {"sym", "close"}
K_SINGLE, K_PAIR_POOL, K_PAIR = 20, 30, 20
SUPPORT = 0.01                                            # доля событий IS, ниже — условие не рассматривается


# ─────────────────────────────── события ───────────────────────────────

def _events_of(f: Path) -> dict:
    J = pd.read_parquet(f)
    out = {}
    for name, (col, side) in TRIGGERS.items():
        if col not in J.columns:
            continue
        s = J[col].fillna(0).values > 0.5
        ev = np.flatnonzero(s & ~np.r_[False, s[:-1]])
        keep, last = [], None
        for i in ev:
            t = J.index[i]
            if last is None or (t - last) >= pd.Timedelta(hours=COOLDOWN_H):
                keep.append(i)
                last = t
        E = J.iloc[keep].copy()
        E["side"] = side
        out[name] = E
    return out


def events(procs: int) -> None:
    EVENTS.mkdir(parents=True, exist_ok=True)
    files = sorted(JOURNAL.glob("*.parquet"))
    print(f"файлов журнала: {len(files)}", flush=True)
    acc = {k: [] for k in TRIGGERS}
    with Pool(procs) as pool:
        for i, d in enumerate(pool.imap_unordered(_events_of, files), 1):
            for k, E in d.items():
                acc[k].append(E)
            if i % 50 == 0:
                print(f"  ... {i}/{len(files)}", flush=True)
    for k, L in acc.items():
        E = pd.concat(L)
        E.to_parquet(EVENTS / f"{k}.parquet")
        print(f"  {k}: событий {len(E):,} · монет {E.sym.nunique()} · {E.index.min()} → {E.index.max()}")


# ─────────────────────────────── условия ───────────────────────────────

def conditions(E: pd.DataFrame, is_mask: np.ndarray, trig_col: str) -> tuple[np.ndarray, list[str]]:
    """Булева матрица условий (событие × условие). Пороги числовых — только по IS."""
    cols, names = [], []
    sgn = np.where(E.side.values == "LONG", 1.0, -1.0)
    # 🔴 07.10 пробный прогон: без "pnl" здесь сам исход попадал в условия («pnl ≥ 1.89» → +6.9% в OOS)
    skip = META | set(OUTCOMES) | {trig_col, "side", "pnl", "ts"}
    for c in E.columns:
        if c in skip or not pd.api.types.is_numeric_dtype(E[c]):
            continue
        v = E[c].values.astype(float)
        fin = np.isfinite(v)
        if fin.mean() < 0.3:
            continue
        u = np.unique(v[fin])
        if len(u) <= 2 and set(u) <= {0.0, 1.0}:
            cols.append(v == 1.0)
            names.append(c)
            continue
        iv = v[is_mask & fin]
        if len(iv) < 100 or np.unique(iv).size < 4:
            continue
        lo, hi = np.quantile(iv, [1 / 3, 2 / 3])
        cols += [fin & (v <= lo), fin & (v >= hi)]
        names += [f"{c} ≤ {lo:.3g} (низ ⅓)", f"{c} ≥ {hi:.3g} (верх ⅓)"]
    # волна ядра — производные с учётом стороны сделки
    if "w_side" in E.columns:
        ws, r = E.w_side.values, E.w_retr.values
        pres = np.isfinite(ws)
        same, opp = pres & (ws == sgn), pres & (ws == -sgn)
        cf = pres & (E.w_core_full.values == 1)
        for nm, m in (("волна: пятёрка видна", pres), ("волна: сетап В СТОРОНУ сделки", same),
                      ("волна: сетап ПРОТИВ сделки", opp), ("волна: полное ядро в сторону", same & cf),
                      ("волна: откат <0.382", pres & (r < 0.382)),
                      ("волна: откат 0.382–0.618", pres & (r >= 0.382) & (r < 0.618)),
                      ("волна: откат 0.618–0.79 (OTE волны)", pres & (r >= 0.618) & (r < 0.79)),
                      ("волна: откат >0.79", pres & (r >= 0.79)),
                      ("волна: в сторону + OTE волны", same & (r >= 0.618) & (r < 0.79))):
            cols.append(m)
            names.append(nm)
    X = np.column_stack(cols) if cols else np.zeros((len(E), 0), bool)
    sup = X.mean(axis=0)
    keep = (sup >= SUPPORT) & (sup <= 1 - SUPPORT)
    return X[:, keep], [n for n, k in zip(names, keep) if k]


FAMILY_ORDER = ("SMC", "пивоты", "WT", "дивергенции", "структура/ноги", "волна ядра", "волатильность",
                "режим", "позиционирование", "свеча/объём/MA")


def family(nm: str) -> str:
    c = nm.lower()
    if c.startswith("волна") or c.startswith("w_"):
        return "волна ядра"
    if c.startswith("mkt_"):
        return "режим"
    if c.startswith("pos_"):
        return "позиционирование"
    if "div" in c:
        return "дивергенции"
    if "pivot" in c:
        return "пивоты"
    if c.startswith("wt"):
        return "WT"
    if c.startswith("atr") or "bar_range" in c:
        return "волатильность"
    if any(k in c for k in ("bos", "choch", "fvg", "ob_", "_ob", "eqh", "eql", "ote", "liq_", "premium",
                            "discount", "inducement", "breaker", "sweep", "smc")):
        return "SMC"
    if c.startswith(("st5_", "st50_", "sc_", "leg_", "hh_", "hl_", "lh_", "ll_", "elliott", "dc_")):
        return "структура/ноги"
    return "свеча/объём/MA"


# ─────────────────────────────── конвейер IS → OOS ───────────────────────────────

def _z(X: np.ndarray, p: np.ndarray, m: np.ndarray, min_n: int):
    """Среднее, Δ к базе и z для каждого условия на подмножестве m."""
    Xm, pm = X[m], p[m]
    n = Xm.sum(axis=0).astype(float)
    s = pm @ Xm
    mean = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    base, sd = pm.mean(), pm.std() + 1e-9
    d = mean - base
    z = np.where(n >= min_n, d / sd * np.sqrt(n), -np.inf)
    return mean, d, z, n


def pipeline(p: np.ndarray, X: np.ndarray, names: list[str], is_m: np.ndarray, oos_m: np.ndarray,
             days_ok: np.ndarray, verbose: bool = False):
    min_n = max(200, int(SUPPORT * is_m.sum()))
    mean, d, z, n = _z(X, p, is_m, min_n)
    z = np.where((mean > 0) & days_ok, z, -np.inf)
    order = np.argsort(-z)
    singles = [i for i in order[:K_SINGLE] if np.isfinite(z[i])]
    pool = [i for i in order[:K_PAIR_POOL] if np.isfinite(z[i])]
    # пары из лучших одиночек
    pairs, pz = [], []
    for a_ in range(len(pool)):
        for b_ in range(a_ + 1, len(pool)):
            i, j = pool[a_], pool[b_]
            m2 = X[:, i] & X[:, j]
            k = (m2 & is_m).sum()
            if k < 150:
                continue
            mu = p[m2 & is_m].mean()
            if mu <= 0:
                continue
            pairs.append((i, j))
            pz.append((mu - p[is_m].mean()) / (p[is_m].std() + 1e-9) * np.sqrt(k))
    top_pairs = [pairs[q] for q in np.argsort(-np.asarray(pz))[:K_PAIR]] if pairs else []
    # OOS один раз
    base_oos = p[oos_m].mean()
    surv, rows = [], []
    for lab, mm in ([(names[i], X[:, i]) for i in singles]
                    + [(f"{names[i]} ∧ {names[j]}", X[:, i] & X[:, j]) for i, j in top_pairs]):
        a = p[mm & oos_m]
        if len(a) < 30:
            rows.append((lab, len(a), np.nan, np.nan, False))
            continue
        ok = a.mean() > 0 and a.mean() - base_oos > 0
        rows.append((lab, len(a), a.mean(), a.mean() - base_oos, ok))
        if ok:
            surv.append(lab)
    if verbose:
        return singles, top_pairs, rows, surv
    best = max((r for r in rows if r[4]), key=lambda r: r[3], default=("—",))
    return best[0], float(len(surv))


def search(trigger: str, n_null: int) -> None:
    E = pd.read_parquet(EVENTS / f"{trigger}.parquet")
    col, side = TRIGGERS[trigger]
    E = E[np.isfinite(E["fwd_24"].values)]
    E = E.reset_index().rename(columns={"index": "ts"}) if "ts" not in E.columns else E.reset_index(drop=True)
    sg = 1.0 if side == "LONG" else -1.0
    E["pnl"] = sg * E["fwd_24"].astype(float) - COST
    y = pd.to_datetime(E.ts).dt.year.values
    is_m, oos_m, hold_m = np.isin(y, IS_Y), np.isin(y, OOS_Y), np.isin(y, HOLD_Y)
    D = V.normalize(E[~hold_m], pnl="pnl", ts="ts", liq="liq")            # 2026 в поиск не входит
    Ed = E[~hold_m].reset_index(drop=True)
    is_d, oos_d = np.isin(D.year.values, IS_Y), np.isin(D.year.values, OOS_Y)
    X, names = conditions(Ed, is_d, col)
    days = pd.Series(D.day.values)
    days_ok = np.array([days[X[:, i] & is_d].nunique() >= 30 for i in range(X.shape[1])])

    print("=" * 110)
    print(f"ТРИГГЕР {trigger} ({col} вход в зону → {side}) · исход fwd_{H} − {COST}")
    print("=" * 110)
    for nm, mm in (("IS 2023-24", is_m), ("OOS 2025", oos_m), ("ОТЛОЖЕНО 2026", hold_m)):
        print(f"  база {nm:<14} {V._fmt(V._stat(E.pnl.values[mm], E.sym.values[mm]))}")
    print(f"  условий: {X.shape[1]} · одиночек в OOS {K_SINGLE} · пар из {K_PAIR_POOL} лучших → {K_PAIR}")

    p = D.pnl.values
    singles, pairs, rows, surv = pipeline(p, X, names, is_d, oos_d, days_ok, verbose=True)
    mean, d, z, n = _z(X, p, is_d, max(200, int(SUPPORT * is_d.sum())))

    # «что в каждой сфере при этом триггере» — ТОЛЬКО IS (OOS не подсматриваем сверх отбора)
    print("\n  ПО СФЕРАМ (IS 2023-24, справочно; z>3 при ~N условий случайно ожидается ~N·0.0013):")
    fam = pd.Series([family(nm) for nm in names])
    for f_ in FAMILY_ORDER:
        ii = np.flatnonzero((fam == f_).values)
        if not len(ii):
            continue
        zz = np.where(np.isfinite(z[ii]), z[ii], -np.inf)
        b = ii[int(np.argmax(zz))]
        best = (f"лучшее: z {z[b]:+.1f} · n {int(n[b])} · средн {mean[b]:+.2f}% · {names[b]}"
                if np.isfinite(z[b]) else "поддержки не хватает")
        print(f"    {f_:<16} условий {len(ii):>4} · z>3: {int((zz > 3).sum()):>3} · {best}")
    print("\n  ЛУЧШИЕ НА IS (одиночки):")
    for i in singles[:10]:
        print(f"    z {z[i]:5.1f} · n {int(n[i]):>5} · средн {mean[i]:+.2f}% · Δ {d[i]:+.2f}  {names[i]}")
    print(f"\n  OOS 2025 — открыт ОДИН раз (база {p[oos_d].mean():+.2f}%):")
    for lab, k, mu, dd, ok in rows:
        if np.isfinite(mu):
            print(f"    {'✅' if ok else '  '} n {k:>4} · средн {mu:+.2f}% · Δ {dd:+.2f}  {lab}")
    print(f"\n  ВЫЖИЛО В OOS: {len(surv)} из {len(rows)}")

    # ярус 2: весь конвейер на сдвинутых исходах
    res = V.search_null(D, lambda pp: pipeline(pp, X, names, is_d, oos_d, days_ok),
                        name=f"{trigger}: IS→OOS, счёт = число выживших", study="joint-trigger-search",
                        n=n_null)

    # ярус 1: карточки выживших на IS+OOS
    cards = []
    lab2mask = {names[i]: X[:, i] for i in singles}
    lab2mask.update({f"{names[i]} ∧ {names[j]}": X[:, i] & X[:, j] for i, j in pairs})
    for lab in surv[:5]:
        print()
        cards.append(V.card(D, lab2mask[lab], name=f"{trigger} × {lab}", study="joint-trigger-search",
                            geo=("mkt_drift30", "atr_pct")))
    V.save_md(cards + [dict(text=res["text"])],
              ROOT / f"obsidian/Research/2026-10-07-Joint-Trigger-{trigger}.md",
              f"Триггер {trigger} × наборы сфер", f"Поиск наборов других сфер при {trigger}: IS 2023-24, OOS 2025")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "search"
    if cmd == "events":
        events(int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) - 4))
    else:
        trig = sys.argv[2] if len(sys.argv) > 2 else "wt_os_1h"
        search(trig, int(sys.argv[3]) if len(sys.argv) > 3 else 100)
