# -*- coding: utf-8 -*-
"""ДАЁТ ЛИ СФЕРА WT ЧТО-ТО БОЕВОЙ МЕХАНИКЕ — ядру волн (Егор 07.10: «проверяй! сфера в тени до сих пор»).

Повод. `scripts/wt_specialist_auc_diag.py` показал: на СМЕСИ всех источников БД снимок WT об исходе
сделки не говорит ничего (прошлое→будущее AUC 0.503). Не проверено одно — WT как контекст для ОДНОЙ
механики, которая в бою. Берём ядро волн: 5 274 сетапа 2023-2026 из `wave_entry_delay_lab`
(`rows_v2.pkl`, доход уже за вычетом коста 0.35%, вход по open бара `entry_time`).

Снимок — тот же, что пишет сфера (`core/intelligence/wt_service.build_wt_snap_entry`):
wt1, wt2, зона ±60, кросс wt1×wt2 на последнем баре, ATR-тренд (atr 43, factor 1.25 — боевой конфиг).
🔴 Отличие от боя ОСОЗНАННОЕ: в бою берётся df.iloc[-1] — ФОРМИРУЮЩИЙСЯ бар; здесь только ЗАКРЫТЫЙ
к моменту входа (иначе заглядывание вперёд). ТФ: 15m · 1h · 4h · 1d (1d собран из 4h — дневок в кэше
19 монет). 3m/5m/45m в истории нет — у сферы на них 20 из 35 признаков, здесь их нет.

Две проверки, обе заданы ДО прогона:
  A. Модель сферы (RF ровно боевых параметров) — учится на годах < Y, проверяется на Y (2024, 2025, 2026).
     Отдельно лонг и шорт; деньги по пятым частям прогноза; внутри боевой клетки — верхняя/нижняя
     половина прогноза.
  B. Простые срезы «за сторону / против» — 4 ТФ × (зона за · зона против · ATR-тренд по ходу) = 12
     гипотез на популяцию, популяций 3 (все лонги, все шорты, клетка лонга) → N = 36.
     Перестановочный P на разницу средних «срез против остальных».

Запуск:  python scripts/wt_context_for_waves.py run [процессов]
         python scripts/wt_context_for_waves.py report
"""
from __future__ import annotations

import os
import pickle
import sys
import time
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

SRC = Path("G:/oko_lab/out/wave_entry_delay/rows_v2.pkl")
OUT = Path("G:/oko_lab/out/wt_context_waves")
TFS = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"),
       "4h": pd.Timedelta("4h"), "1d": pd.Timedelta("1D")}
ATR_P, FACTOR = 43, 1.25                 # config.yaml → analysis.indicators.trend
WT_OB, WT_OS = 60.0, -60.0
FEATS = [f"{tf}_{k}" for tf in TFS for k in ("wt1", "wt2", "zone", "cross", "atr")]


def _wt_trend(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    from core.indicators.indicators import calculate_wt, calculate_trend
    ot = df.index.tz_convert(None).values.astype("datetime64[ns]")
    d = calculate_trend(calculate_wt(df.reset_index(drop=True)), atr_period=ATR_P, factor=FACTOR)
    return ot, d["wt1"].values.astype(float), d["wt2"].values.astype(float), d["trend"].values.astype(float)


def run_symbol(args) -> list[dict]:
    sym, trades = args
    from research_harness import load
    try:
        d15, d1h, d4h = load(sym, "15m"), load(sym, "1h"), load(sym, "4h")
    except Exception:                                    # noqa: BLE001
        return []
    if any(x is None or x.empty for x in (d15, d1h, d4h)):
        return []
    d1d = d4h.resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    series = {tf: _wt_trend(df) for tf, df in (("15m", d15), ("1h", d1h), ("4h", d4h), ("1d", d1d))}
    # ликвидность: медиана оборота 4h за 30 дней ДО входа (180 баров)
    t4 = d4h.index.tz_convert(None).values.astype("datetime64[ns]")
    turn = (d4h["close"] * d4h["volume"]).values.astype(float)
    out = []
    for tr in trades:
        E = np.datetime64(pd.Timestamp(tr["entry_time"]).to_datetime64())
        rec = dict(tr)
        ok = True
        for tf, dur in TFS.items():
            ot, w1, w2, trd = series[tf]
            i = int(np.searchsorted(ot, E - np.timedelta64(dur), side="right")) - 1   # последний ЗАКРЫТЫЙ
            if i < 60 or np.isnan(w1[i]) or np.isnan(w2[i]):
                ok = False
                break
            c = 0
            if w1[i - 1] <= w2[i - 1] and w1[i] > w2[i]:
                c = 1
            elif w1[i - 1] >= w2[i - 1] and w1[i] < w2[i]:
                c = -1
            rec[f"{tf}_wt1"] = w1[i] / 100.0
            rec[f"{tf}_wt2"] = w2[i] / 100.0
            rec[f"{tf}_zone"] = 1.0 if w1[i] > WT_OB else (-1.0 if w1[i] < WT_OS else 0.0)
            rec[f"{tf}_cross"] = float(c)
            rec[f"{tf}_atr"] = 1.0 if trd[i] == 1 else -1.0
        if not ok:
            continue
        j = int(np.searchsorted(t4, E - np.timedelta64(4, "h"), side="right")) - 1
        rec["turnover"] = float(np.nanmedian(turn[max(0, j - 180):j + 1])) if j > 0 else np.nan
        out.append(rec)
    return out


def run(procs: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    R = pd.DataFrame(pickle.load(open(SRC, "rb")))
    jobs = [(s, g.to_dict("records")) for s, g in R.groupby("sym")]
    print(f"сетапов {len(R)} · монет {len(jobs)} · процессов {procs}", flush=True)
    t0, rows = time.time(), []
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(run_symbol, jobs), 1):
            rows += r
            if i % 20 == 0:
                print(f"  ... {i}/{len(jobs)} монет · снимков {len(rows)} · {time.time() - t0:.0f} с", flush=True)
    pickle.dump(rows, open(OUT / "rows.pkl", "wb"))
    print(f"готово: {len(rows)} снимков · {time.time() - t0:.0f} с", flush=True)


# ─────────────────────────────── отчёт ───────────────────────────────

def _line(v: pd.Series) -> str:
    if len(v) == 0:
        return "n=0"
    pos, neg = v[v > 0].sum(), -v[v < 0].sum()
    frail = float(np.sort(v.values)[:max(1, int(len(v) * 0.9))].mean())
    return (f"n={len(v):>5} · WR {(v > 0).mean() * 100:>4.0f}% · PF {pos / neg if neg > 0 else 9.99:>5.2f} · "
            f"средн {v.mean():>+6.2f}% · медиана {v.median():>+6.2f}% · безтоп10% средн {frail:>+6.2f}%")


def _perm_p(v: np.ndarray, m: np.ndarray, n_perm: int = 2000, seed: int = 0) -> float:
    """Двусторонний P на разницу средних «в срезе − вне среза» при случайной метке среза."""
    rng = np.random.default_rng(seed)
    obs = v[m].mean() - v[~m].mean()
    k, cnt = m.sum(), 0
    for _ in range(n_perm):
        idx = rng.permutation(len(v))[:k]
        mm = np.zeros(len(v), bool)
        mm[idx] = True
        if abs(v[mm].mean() - v[~mm].mean()) >= abs(obs):
            cnt += 1
    return (cnt + 1) / (n_perm + 1)


def _model():
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=5,
                                  random_state=42, n_jobs=-1)


def report() -> None:
    from sklearn.metrics import roc_auc_score
    R = pd.DataFrame(pickle.load(open(OUT / "rows.pkl", "rb")))
    R["year"] = pd.to_datetime(R.entry_time).dt.year
    R["sgn"] = np.where(R.side == "LONG", 1.0, -1.0)
    R["win"] = (R.pnl_0 > 0).astype(int)
    cell = (R.side == "LONG") & R.core_full & (R.stop_pct >= 6.0)

    # ── инвентаризация ──
    print("=" * 100)
    print(f"ИНВЕНТАРИЗАЦИЯ: снимков {len(R)} из 5274 · монет {R.sym.nunique()} · "
          f"окно {R.entry_time.min()} → {R.entry_time.max()}")
    print(pd.crosstab(R.year, R.side).to_string())
    print(f"клетка лонга (полное ядро ∧ стоп ≥6%): {int(cell.sum())}")
    from research_harness import load
    yr = []
    for s in R.sym.unique():
        try:
            c = load(s, "4h")["close"]
        except Exception:                                # noqa: BLE001
            continue
        for y, g in c.groupby(c.index.year):
            if len(g) > 300:
                yr.append((y, g.iloc[-1] / g.iloc[0] - 1))
    Y = pd.DataFrame(yr, columns=["y", "r"])
    print("\nрежим годов (монеты выборки, 4h):")
    for y, g in Y.groupby("y"):
        med, up = g.r.median() * 100, (g.r > 0).mean() * 100
        reg = "БЫК" if up > 60 else ("МЕДВЕДЬ" if up < 30 else "нейтраль")
        print(f"  {y}: монет {len(g):>3} · медиана года {med:+6.1f}% · растущих {up:4.0f}% · {reg}")

    # ── A. модель сферы, проход по годам ──
    print("\n" + "=" * 100)
    print("A. МОДЕЛЬ СФЕРЫ (RF боевых параметров, 20 признаков 4 ТФ) · учится на годах < Y, проверка на Y")
    print("=" * 100)
    for side in ("LONG", "SHORT"):
        S = R[R.side == side]
        for nm, X in (("как в бою", S[FEATS].values),
                      ("выровнено по стороне", S[FEATS].values * S[["sgn"]].values)):
            aucs, tops, bots, alls = [], [], [], []
            for y in (2024, 2025, 2026):
                tr, te = (S.year < y).values, (S.year == y).values
                if te.sum() < 60 or tr.sum() < 200 or S.win[tr].nunique() < 2 or S.win[te].nunique() < 2:
                    continue
                m = _model().fit(X[tr], S.win.values[tr])
                p = m.predict_proba(X[te])[:, 1]
                aucs.append(f"{y}: {roc_auc_score(S.win.values[te], p):.3f}")
                q = pd.qcut(p, 5, labels=False, duplicates="drop")
                v = S.pnl_0.values[te]
                tops.append(v[q == q.max()])
                bots.append(v[q == q.min()])
                alls.append(v)
            if not aucs:
                continue
            t, b, a = np.concatenate(tops), np.concatenate(bots), np.concatenate(alls)
            print(f"  {side:<5} {nm:<22} AUC {' · '.join(aucs)}")
            print(f"        верхняя пятая прогноза {t.mean():+.2f}% (n={len(t)}) · нижняя {b.mean():+.2f}% "
                  f"(n={len(b)}) · все {a.mean():+.2f}%")

    # внутри боевой клетки: модель, обученная на ВСЕХ лонгах прошлых лет
    S = R[R.side == "LONG"]
    X = S[FEATS].values
    hi, lo = [], []
    for y in (2024, 2025, 2026):
        tr, te = (S.year < y).values, ((S.year == y) & cell[S.index]).values
        if te.sum() < 10:
            continue
        m = _model().fit(X[tr], S.win.values[tr])
        p = m.predict_proba(X[te])[:, 1]
        v = S.pnl_0.values[te]
        med = np.median(p)
        hi.append(v[p >= med])
        lo.append(v[p < med])
    if hi:
        h, l_ = np.concatenate(hi), np.concatenate(lo)
        print(f"\n  🔑 внутри клетки лонга (2024-26): верхняя половина прогноза {_line(pd.Series(h))}")
        print(f"                                     нижняя половина          {_line(pd.Series(l_))}")

    # ── B. заранее заданные срезы ──
    print("\n" + "=" * 100)
    print("B. СРЕЗЫ «ЗА СТОРОНУ / ПРОТИВ» · 12 гипотез × 3 популяции = N 36 · P — перестановка 2000")
    print("   зона ЗА: лонг при wt1<−60 / шорт при wt1>+60 · ПРОТИВ: наоборот · тренд ПО ХОДУ: ATR-тренд = сторона")
    print("=" * 100)
    pops = (("ВСЕ ЛОНГИ", R[R.side == "LONG"]), ("ВСЕ ШОРТЫ", R[R.side == "SHORT"]),
            ("🔑 КЛЕТКА ЛОНГА", R[cell]))
    hits = []
    for pn, P in pops:
        v = P.pnl_0.values
        print(f"\n{pn}: база {_line(P.pnl_0)}")
        for tf in TFS:
            za = (P[f"{tf}_zone"] * P.sgn).values
            ta = (P[f"{tf}_atr"] * P.sgn).values
            for nm, m in (("зона ЗА", za < 0), ("зона ПРОТИВ", za > 0), ("тренд ПО ХОДУ", ta > 0)):
                if m.sum() < 10 or (~m).sum() < 10:
                    print(f"  {tf:>3} {nm:<14} мало ({int(m.sum())})")
                    continue
                pv = _perm_p(v, m)
                d = v[m].mean() - v[~m].mean()
                flag = " ◀" if pv < 0.05 else ""
                print(f"  {tf:>3} {nm:<14} {_line(P.pnl_0[m])} · Δ к остальным {d:+6.2f} п.п. · P={pv:.3f}{flag}")
                if pv < 0.05:
                    hits.append((pn, tf, nm, P, m))

    # ── обязательные срезы для того, что прошло P<0.05 ──
    print("\n" + "=" * 100)
    print(f"СРЕЗЫ ДЛЯ ПРОШЕДШИХ P<0.05: {len(hits)} из 36 (случайно ожидается ~1.8)")
    print("=" * 100)
    for pn, tf, nm, P, m in hits:
        P = P.assign(_m=m)
        print(f"\n▶ {pn} · {tf} {nm}")
        for y, g in P.groupby("year"):
            a, b = g.pnl_0[g._m], g.pnl_0[~g._m]
            print(f"   {y}: в срезе {a.mean() if len(a) else np.nan:+6.2f}% (n={len(a):>4}) · "
                  f"остальные {b.mean() if len(b) else np.nan:+6.2f}% (n={len(b):>4})")
        q = P.stop_pct.quantile([0.33, 0.66]).values
        for nm2, mm in (("стоп мал", P.stop_pct < q[0]), ("стоп сред", (P.stop_pct >= q[0]) & (P.stop_pct < q[1])),
                        ("стоп велик", P.stop_pct >= q[1])):
            g = P[mm]
            a, b = g.pnl_0[g._m], g.pnl_0[~g._m]
            print(f"   {nm2:<10}: в срезе {a.mean() if len(a) else np.nan:+6.2f}% (n={len(a):>4}) · "
                  f"остальные {b.mean() if len(b) else np.nan:+6.2f}% (n={len(b):>4})")
        lq = P.turnover >= P.turnover.median()
        for nm2, mm in (("ликвидная ½", lq), ("неликвидная ½", ~lq)):
            g = P[mm]
            a, b = g.pnl_0[g._m], g.pnl_0[~g._m]
            print(f"   {nm2:<13}: в срезе {a.mean() if len(a) else np.nan:+6.2f}% (n={len(a):>4}) · "
                  f"остальные {b.mean() if len(b) else np.nan:+6.2f}% (n={len(b):>4})")
        sub = P[P._m]
        cs = sub.groupby("sym").pnl_0.sum()
        print(f"   охват: монет в срезе {len(cs)} · в плюсе {(cs > 0).sum()}")


GEO = ["stop_pct", "stop_rel", "imp_pct", "depth5", "core_full", "core", "fractal",
       "altern_type", "altern_form", "count_ok", "trig_cross"]


def report_increment() -> None:
    """C. ПРИРОСТ сверх геометрии. Подозрение после A/B: WT может лишь повторять размер стопа
    (главный известный фактор ядра, [[stop_zone_survived_blind_test]]) — «1h тренд по ходу» внутри
    корзины больших стопов уже не помогает. Сравниваем модель на ГЕОМЕТРИИ сетапа (всё известно
    к входу) с моделью «геометрия + WT» на тех же сделках, тот же проход по годам."""
    from sklearn.metrics import roc_auc_score
    R = pd.DataFrame(pickle.load(open(OUT / "rows.pkl", "rb")))
    R["year"] = pd.to_datetime(R.entry_time).dt.year
    R["win"] = (R.pnl_0 > 0).astype(int)
    R["trig_cross"] = (R.trigger == "cross").astype(float)
    for c in ("core_full", "core", "fractal", "altern_type", "altern_form", "count_ok"):
        R[c] = R[c].astype(float)
    R[GEO] = R[GEO].fillna(-1.0)
    cell = (R.side == "LONG") & (R.core_full > 0) & (R.stop_pct >= 6.0)

    print("\n" + "=" * 100)
    print("C. ПРИРОСТ СВЕРХ ГЕОМЕТРИИ (стоп, импульс, глубина, флаги ядра, триггер) · учится на годах < Y")
    print("=" * 100)
    for side in ("LONG", "SHORT"):
        S = R[R.side == side]
        scores = {}
        for nm, cols in (("геометрия", GEO), ("геометрия + WT", GEO + FEATS), ("только WT", FEATS)):
            X = S[cols].values
            aucs, ps, idx = [], [], []
            for y in (2024, 2025, 2026):
                tr, te = (S.year < y).values, (S.year == y).values
                if te.sum() < 60 or S.win[te].nunique() < 2:
                    continue
                p = _model().fit(X[tr], S.win.values[tr]).predict_proba(X[te])[:, 1]
                aucs.append(f"{y}: {roc_auc_score(S.win.values[te], p):.3f}")
                # пятые части — ВНУТРИ года, чтобы сдвиг уровня прогноза между годами не смешивал
                ps.append(pd.Series(pd.qcut(p, 5, labels=False, duplicates="drop"), index=S.index[te]))
                idx.append(S.index[te])
            q = pd.concat(ps)
            v = S.pnl_0[q.index]
            scores[nm] = q
            print(f"  {side:<5} {nm:<16} AUC {' · '.join(aucs)}")
            print(f"        пятые части прогноза (снизу вверх), средн %: "
                  + "  ".join(f"{v[q == k].mean():+5.2f}" for k in range(5)))
        if side == "LONG":
            # внутри боевой клетки: геометрия против геометрии+WT, верх/низ половины, P перестановкой
            print("\n  🔑 ВНУТРИ КЛЕТКИ ЛОНГА (2024-26) — модели учились на ВСЕХ лонгах прошлых лет:")
            S2 = S.copy()
            for nm, cols in (("геометрия", GEO), ("геометрия + WT", GEO + FEATS), ("только WT", FEATS)):
                X = S2[cols].values
                vals, prs = [], []
                for y in (2024, 2025, 2026):
                    tr = (S2.year < y).values
                    te = ((S2.year == y) & cell[S2.index]).values
                    if te.sum() < 10:
                        continue
                    p = _model().fit(X[tr], S2.win.values[tr]).predict_proba(X[te])[:, 1]
                    vals.append(S2.pnl_0.values[te])
                    prs.append(p >= np.median(p))         # половины внутри года
                v, hi = np.concatenate(vals), np.concatenate(prs)
                d = v[hi].mean() - v[~hi].mean()
                pv = _perm_p(v, hi)
                print(f"     {nm:<16} верх {v[hi].mean():+5.2f}% (n={hi.sum()}) · низ {v[~hi].mean():+5.2f}% "
                      f"(n={(~hi).sum()}) · Δ {d:+5.2f} п.п. · P={pv:.3f}")
            C = R[cell]
            print("\n  клетка лонга × 1d зона ЗА (wt1 дневки < −60) по годам:")
            m = C["1d_zone"] < 0
            for y, g in C.groupby("year"):
                mm = m[g.index]
                print(f"     {y}: зона ЗА {g.pnl_0[mm].mean() if mm.any() else np.nan:+6.2f}% (n={mm.sum():>3}) · "
                      f"остальные {g.pnl_0[~mm].mean() if (~mm).any() else np.nan:+6.2f}% (n={(~mm).sum():>3})")
            print("  клетка лонга × 1h ATR-тренд уже вверх по годам:")
            m = C["1h_atr"] > 0
            for y, g in C.groupby("year"):
                mm = m[g.index]
                print(f"     {y}: тренд вверх {g.pnl_0[mm].mean() if mm.any() else np.nan:+6.2f}% (n={mm.sum():>3}) · "
                      f"ещё вниз {g.pnl_0[~mm].mean() if (~mm).any() else np.nan:+6.2f}% (n={(~mm).sum():>3})")

            # D. два артефакта для осей клетки: опоздание входа и скученность по датам
            # (капитуляция рынка = много монет в один день → перестановка по сделкам завышает значимость)
            C = C.assign(day=pd.to_datetime(C.entry_time).dt.floor("D"),
                         lag_h=(pd.to_datetime(C.entry_time) - pd.to_datetime(C.top_time)).dt.total_seconds() / 3600)
            up = C["1h_atr"] > 0
            print(f"\n  D. опоздание от дна пятой, медиана ч: тренд вверх {C.lag_h[up].median():.1f} · "
                  f"ещё вниз {C.lag_h[~up].median():.1f} · стоп медиана {C.stop_pct[up].median():.1f}% / "
                  f"{C.stop_pct[~up].median():.1f}%")
            q = C.lag_h.median()
            for nm, mm in (("опоздание ≤ медианы", C.lag_h <= q), ("опоздание > медианы", C.lag_h > q)):
                g = C[mm]
                u = g["1h_atr"] > 0
                print(f"     {nm}: тренд вверх {g.pnl_0[u].mean():+.2f}% (n={u.sum()}) · "
                      f"ещё вниз {g.pnl_0[~u].mean():+.2f}% (n={(~u).sum()})")
            rng = np.random.default_rng(0)
            for nm, m in (("1h тренд ещё вниз", C["1h_atr"] < 0), ("1d зона ЗА", C["1d_zone"] < 0)):
                U = C.assign(g=m.values).groupby(["day", "g"]).pnl_0.mean().reset_index()
                v, g = U.pnl_0.values, U.g.values
                obs = v[g].mean() - v[~g].mean()
                cnt = sum(abs(v[p].mean() - v[~p].mean()) >= abs(obs)
                          for p in (rng.permutation(g) for _ in range(5000)))
                print(f"     {nm}: сделок {int(m.sum())} на {C[m].day.nunique()} днях · Δ по дням {obs:+.2f} п.п. · "
                      f"P перестановкой ПО ДНЯМ {(cnt + 1) / 5001:.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "run":
        p = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) - 2)
        run(p)
    if cmd == "inc":
        report_increment()
    else:
        report()
        report_increment()
