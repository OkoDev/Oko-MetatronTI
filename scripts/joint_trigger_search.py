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
    # 08.10 Егор: «если рынок рос — искать механику входа в рост и продолжение». Откат в ТЕКУЩЕЙ дневной ноге
    # дошёл до канона OTE 0.62–0.79 (`_leg_block`) → по направлению ноги. Обе стороны (закон).
    "legup_ote": ("legup_in_ote", "LONG"), "legdn_ote": ("legdn_in_ote", "SHORT"),
}
# 08.10: у триггеров ноги — исход по стопу и цели (широкая геометрия: тихий рост даёт широкий стоп, туда
# impulse_fib не дотягивается), кулдаун = горизонт исхода (сделки одной монеты не перекрываются)
TRIG_OPTS = {"legup_ote": dict(cooldown=72, outcome="geo_wide"), "legdn_ote": dict(cooldown=72, outcome="geo_wide")}
CTRL_STEP_H = 72                                          # контроль: обычный час по сетке каждые 72 ч на монету
OUTCOMES = ("fwd_4", "fwd_24", "fwd_72", "mfe_24", "mae_24", "geo_tight_long", "geo_tight_short",
            "geo_wide_long", "geo_wide_short")
META = {"sym", "close"}
K_SINGLE, K_PAIR_POOL, K_PAIR = 20, 30, 20
SUPPORT = 0.01                                            # доля событий IS, ниже — условие не рассматривается


# ─────────────────────────────── события ───────────────────────────────

def _events_of(args) -> dict:
    f, names = args
    J = pd.read_parquet(f)
    out = {}
    for name in names:
        if name == "ctrl":                               # обычный час: сетка CTRL_STEP_H, обе стороны в исходах
            out[name] = J.iloc[::CTRL_STEP_H].copy()
            continue
        col, side = TRIGGERS[name]
        if col not in J.columns:
            continue
        cool = TRIG_OPTS.get(name, {}).get("cooldown", COOLDOWN_H)
        s = J[col].fillna(0).values > 0.5
        ev = np.flatnonzero(s & ~np.r_[False, s[:-1]])
        keep, last = [], None
        for i in ev:
            t = J.index[i]
            if last is None or (t - last) >= pd.Timedelta(hours=cool):
                keep.append(i)
                last = t
        E = J.iloc[keep].copy()
        E["side"] = side
        out[name] = E
    return out


def events(procs: int, names: list[str] | None = None) -> None:
    EVENTS.mkdir(parents=True, exist_ok=True)
    names = names or list(TRIGGERS)
    files = sorted(JOURNAL.glob("*.parquet"))
    print(f"файлов журнала: {len(files)} · триггеры {names}", flush=True)
    acc = {k: [] for k in names}
    with Pool(procs) as pool:
        for i, d in enumerate(pool.imap_unordered(_events_of, [(f, names) for f in files]), 1):
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


def _outcome(E: pd.DataFrame, trigger: str, side: str) -> tuple[np.ndarray, str]:
    """Исход сделки −кост: fwd_24 по стороне (по умолчанию) или стоп/цель geo_* стороны (уже со знаком стороны)."""
    oc = TRIG_OPTS.get(trigger, {}).get("outcome", "fwd_24")
    if oc.startswith("geo_"):
        col = f"{oc}_{side.lower()}"
        return E[col].astype(float).values - COST, f"{col} − {COST}"
    sg = 1.0 if side == "LONG" else -1.0
    return sg * E[oc].astype(float).values - COST, f"{'+' if sg > 0 else '−'}{oc} − {COST}"


def control_table(trigger: str, side: str, E: pd.DataFrame) -> None:
    """Триггер против ОБЫЧНОГО ЧАСА той же геометрии (сетка ctrl) по году × трети дрейфа рынка.
    Трети — по дрейфу всех часов IS (контроль), одни и те же для обоих."""
    f = EVENTS / "ctrl.parquet"
    if not f.exists():
        print("  ⚠️ контроль не собран (events N ctrl) — сравнения с обычным часом НЕТ")
        return
    C = pd.read_parquet(f)
    C = C.reset_index().rename(columns={"index": "ts"}) if "ts" not in C.columns else C.reset_index(drop=True)
    C["pnl"], _ = _outcome(C, trigger, side)
    C = C[np.isfinite(C.pnl.values)]
    cy = pd.to_datetime(C.ts).dt.year.values
    lo, hi = np.nanquantile(C.mkt_drift30.values[np.isin(cy, IS_Y)], [1 / 3, 2 / 3])

    def _ter(v):
        return np.where(~np.isfinite(v), "—", np.where(v <= lo, "падает", np.where(v >= hi, "РАСТЁТ", "середина")))
    E2 = E.assign(y=pd.to_datetime(E.ts).dt.year.values, ter=_ter(E.mkt_drift30.values))
    C2 = C.assign(y=cy, ter=_ter(C.mkt_drift30.values))
    print(f"\n  ТРИГГЕР ПРОТИВ ОБЫЧНОГО ЧАСА (та же геометрия; трети дрейфа30 по IS: ≤{lo:+.1f} / ≥{hi:+.1f}):")
    print(f"    {'год':<6}{'рынок':<11}{'триггер n':>10}{'средн':>8}{'медиана':>9}{'обычный n':>11}{'средн':>8}"
          f"{'Δ':>7}")
    for (yy, tt), g in E2.groupby(["y", "ter"]):
        c = C2[(C2.y == yy) & (C2.ter == tt)]
        if len(g) < 20:
            continue
        print(f"    {yy:<6}{tt:<11}{len(g):>10}{g.pnl.mean():>+8.2f}{g.pnl.median():>+9.2f}{len(c):>11}"
              f"{c.pnl.mean():>+8.2f}{g.pnl.mean() - c.pnl.mean():>+7.2f}")


def search(trigger: str, n_null: int) -> None:
    E = pd.read_parquet(EVENTS / f"{trigger}.parquet")
    col, side = TRIGGERS[trigger]
    E = E.reset_index().rename(columns={"index": "ts"}) if "ts" not in E.columns else E.reset_index(drop=True)
    E["pnl"], oc_txt = _outcome(E, trigger, side)
    E = E[np.isfinite(E.pnl.values)].reset_index(drop=True)
    # §0A.2/§0A.3: сторона одна, исход — ровно своя колонка стороны
    assert set(E.side) == {side}
    if oc_txt.startswith("geo_wide"):
        assert np.allclose(E.pnl.values, E[f"geo_wide_{side.lower()}"].values - COST)
    y = pd.to_datetime(E.ts).dt.year.values
    is_m, oos_m, hold_m = np.isin(y, IS_Y), np.isin(y, OOS_Y), np.isin(y, HOLD_Y)
    D = V.normalize(E[~hold_m], pnl="pnl", ts="ts", liq="liq")            # 2026 в поиск не входит
    Ed = E[~hold_m].reset_index(drop=True)
    is_d, oos_d = np.isin(D.year.values, IS_Y), np.isin(D.year.values, OOS_Y)
    X, names = conditions(Ed, is_d, col)
    days = pd.Series(D.day.values)
    days_ok = np.array([days[X[:, i] & is_d].nunique() >= 30 for i in range(X.shape[1])])

    print("=" * 110)
    print(f"ТРИГГЕР {trigger} ({col} вход в зону → {side}) · исход {oc_txt}")
    print("=" * 110)
    # инвентаризация (§1): годы × монеты × режим года
    inv = E.assign(y=y).groupby("y").agg(n=("pnl", "size"), coins=("sym", "nunique"),
                                         drift30=("mkt_drift30", "median"))
    print("  инвентаризация: " + " · ".join(f"{k}: {r.n} соб., {r.coins} мон., дрейф30 мед {r.drift30:+.1f}"
                                         for k, r in inv.iterrows()))
    for nm, mm in (("IS 2023-24", is_m), ("OOS 2025", oos_m), ("ОТЛОЖЕНО 2026", hold_m)):
        print(f"  база {nm:<14} {V._fmt(V._stat(E.pnl.values[mm], E.sym.values[mm]))}")
    # 2026 в таблицу контроля не входит: отложенный год не смотрим до карточки
    control_table(trigger, side, E[~hold_m])
    print(E[["sym", "ts", "side", "close", "legup_depth" if side == "LONG" else "legdn_depth", "mkt_drift30",
             "pnl"]].head(4).round(3).to_string(index=False))
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
              ROOT / f"obsidian/Research/{pd.Timestamp.now():%Y-%m-%d}-Joint-Trigger-{trigger}.md",
              f"Триггер {trigger} × наборы сфер", f"Поиск наборов других сфер при {trigger}: IS 2023-24, OOS 2025")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "search"
    if cmd == "events":                                  # events [процессов] [триггер,…|ctrl]
        events(int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) - 4),
               sys.argv[3].split(",") if len(sys.argv) > 3 else None)
    else:
        trig = sys.argv[2] if len(sys.argv) > 2 else "wt_os_1h"
        search(trig, int(sys.argv[3]) if len(sys.argv) > 3 else 100)
