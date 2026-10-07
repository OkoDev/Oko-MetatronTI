# -*- coding: utf-8 -*-
"""ПОРТФЕЛЬНАЯ СИМУЛЯЦИЯ ЯДРА ВОЛН: сколько стоит лимит слотов (Егор 08.10: «Лимит 6 слотов срежет большую часть
такого кластера» — «именно поэтому лимиты и не ограничивал изначально! делай портфельную симуляцию»).

Повод. Деньги клетки лонга живут в КЛАСТЕРАХ дней капитуляции ([[wave_fifth_wt_depth_cell]]: 205 сделок с |WT пятой|≥75
на 28 днях; одиночка хуже кластера). Риск-каркас `waves_long` (07.10) держит максимум 6 позиций и дневной лимит −25%.
Вопрос: сколько денег режет лимит и сколько риска он снимает.

Сделки — rows_v2 (`wave_entry_delay_lab`: вход по триггеру 15m на open, стоп за пятой, цель — конец волны 4, удержание
240 ч, кост 0.35). Время ВЫХОДА в rows_v2 нет → каждая сделка пересчитывается тем же правилом (`_walk`), стоп из
stop_pct, цель p4 из расчёта ядра (та же пятёрка) — ГОЛДЕН: пересчитанный доход обязан совпасть с записанным pnl_0.

Риск как в бою (config.yaml trading.waves_long + source_policies.waves_long): доказанный лонг (стоп ≥6% или коридор
30–50% импульса) 1.0% · лонг вне зоны 0.5% · шорт 0.25%. Вес монеты (до ×1.5) не моделируется. Доход сделки на
капитал = риск% × pnl% / стоп%. Учёт по закрытию (без переоценки открытых) → просадка занижена, сказано в выводе.

Сценарии: без лимита · лимит N слотов (3/6/10/15) очередью «кто первый» · лимит 6 с приоритетом по |WT пятой| среди
пришедших одновременно (один бар 15m) · без лимита, но риск по глубине WT · + дневной лимит −25% как в бою.

Запуск: python scripts/wave_portfolio_sim.py [процессов]
"""
from __future__ import annotations

import os
import pickle
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

SRC = Path("G:/oko_lab/out/wave_entry_delay/rows_v2.pkl")
LAYERS = Path("G:/oko_lab/out/wave_detector_layers.pkl")
OUT = Path("G:/oko_lab/out/wave_portfolio_trades.pkl")
HOLD_H, COST = 240, 0.35
RISK = {"proven": 1.0, "long_out": 0.5, "short": 0.25}
DAILY_LIMIT = 25.0


def per_symbol(args):
    sym, trades = args
    import logging
    logging.disable(logging.CRITICAL)
    import joint_state_journal as J
    from research_harness import load
    out = []
    try:
        d15 = load(sym, "15m")
        W = J._wave_ctx(load(sym, "1h"))
    except Exception:                                    # noqa: BLE001
        return [dict(t, exit_time=None, pnl_re=np.nan) for t in trades]
    W = W.assign(visible=pd.to_datetime(W.time) + pd.Timedelta("4h"),
                 top_key=pd.to_datetime(W.top_time).dt.strftime("%Y-%m-%d %H:%M"))
    lt = d15.index.tz_convert(None).values.astype("datetime64[ns]")
    op, hi, lo, cl = (d15[c].values.astype(float) for c in ("open", "high", "low", "close"))
    for t in trades:
        E = pd.Timestamp(t["entry_time"])
        c = W[(W.side == t["side"]) & (W.top_key == t["top_time"]) & (W.visible <= E)]
        j1 = int(np.searchsorted(lt, np.datetime64(E.to_datetime64())))
        if c.empty or j1 >= len(lt):
            out.append(dict(t, exit_time=None, pnl_re=np.nan))
            continue
        tp = float(c.sort_values("visible").iloc[-1].p4)
        long_ = t["side"] == "LONG"
        e = float(op[j1])
        sl = e * (1 - t["stop_pct"] / 100) if long_ else e * (1 + t["stop_pct"] / 100)
        end_t = lt[j1] + np.timedelta64(HOLD_H * 60, "m")
        k_exit, px = len(lt) - 1, float(cl[-1])
        for k in range(j1, len(lt)):                     # то же правило, что wave_entry_delay_lab._walk
            if (lo[k] <= sl) if long_ else (hi[k] >= sl):
                k_exit, px = k, sl
                break
            if (hi[k] >= tp) if long_ else (lo[k] <= tp):
                k_exit, px = k, tp
                break
            if lt[k] >= end_t:
                k_exit, px = k, float(cl[k])
                break
        pnl = ((px - e) / e * 100.0) * (1 if long_ else -1) - COST
        out.append(dict(t, exit_time=str(pd.Timestamp(lt[k_exit]))[:16], pnl_re=pnl))
    return out


def collect(procs: int) -> pd.DataFrame:
    R = pd.DataFrame(pickle.load(open(SRC, "rb")))
    jobs = [(s, g.to_dict("records")) for s, g in R.groupby("sym")]
    rows = []
    with Pool(procs) as pool:
        for r in pool.imap_unordered(per_symbol, jobs):
            rows += r
    D = pd.DataFrame(rows)
    assert len(D) == len(R)
    D.to_pickle(OUT)
    return D


def simulate(T: pd.DataFrame, slots: int | None, prio: str = "fifo", daily: float | None = None,
             risk_col: str = "risk") -> dict:
    """События по времени: выходы раньше входов того же момента. Одновременные входы (один бар) —
    по приоритету: fifo — порядок появления, wt — глубже |WT пятой| первым."""
    T = T.sort_values(["E", "order" if prio == "fifo" else "wt_neg"]).reset_index(drop=True)
    open_pos: list[tuple] = []                          # (exit_ts, contrib, risk)
    taken, realized = [], []
    day_pnl: dict = {}
    max_open, max_risk = 0, 0.0
    for _, t in T.iterrows():
        still = []
        for ex, contrib, rk in open_pos:                 # закрыть всё, что вышло до этого входа
            if ex <= t.E:
                realized.append((ex, contrib))
                day_pnl[ex.floor("D")] = day_pnl.get(ex.floor("D"), 0.0) + contrib
            else:
                still.append((ex, contrib, rk))
        open_pos = still
        if slots is not None and len(open_pos) >= slots:
            continue
        if daily is not None and day_pnl.get(t.E.floor("D"), 0.0) <= -daily:
            continue
        contrib = t[risk_col] * t.pnl_re / t.stop_pct
        open_pos.append((t.X, contrib, t[risk_col]))
        taken.append(t)
        max_open = max(max_open, len(open_pos))
        max_risk = max(max_risk, sum(p[2] for p in open_pos))
    for ex, contrib, _ in open_pos:
        realized.append((ex, contrib))
    Rz = pd.DataFrame(realized, columns=["X", "c"]).sort_values("X")
    eq = Rz.c.cumsum()
    dd = float((eq - eq.cummax()).min()) if len(eq) else 0.0
    daily_s = Rz.groupby(Rz.X.dt.floor("D")).c.sum()
    tk = pd.DataFrame(taken)
    by_year = Rz.groupby(Rz.X.dt.year).c.sum().round(1).to_dict()
    return {"n": len(tk), "total": float(Rz.c.sum()), "dd": dd, "worst_day": float(daily_s.min()),
            "max_open": max_open, "max_risk": max_risk, "years": by_year,
            "wt75": int((tk.wt_abs >= 75).sum()) if len(tk) else 0,
            "proven": int((tk.risk == RISK["proven"]).sum()) if len(tk) else 0}


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    D = pd.read_pickle(OUT) if OUT.exists() else collect(procs)
    # ГОЛДЕН §0A.2: пересчитанный доход = записанный
    ok = D.pnl_re.notna()
    match = (np.abs(D.pnl_re[ok] - D.pnl_0[ok]) < 0.05).mean()
    print(f"пересчёт выходов: {ok.mean() * 100:.1f}% сделок · доход совпал с rows_v2 в {match * 100:.1f}%")
    assert match > 0.97, "пересчёт выхода не воспроизводит замер — симуляции верить нельзя"
    D = D[ok & (np.abs(D.pnl_re - D.pnl_0) < 0.05)].copy()
    # ключ — с вершиной пятой: у монеты бывают две пятёрки с одним временем входа
    key = ["sym", "entry_time", "side", "top_time"]
    L = pd.read_pickle(LAYERS)[key + ["wt_top"]].drop_duplicates(key)
    n0 = len(D)
    D = D.merge(L, on=key, how="left", validate="many_to_one")
    assert len(D) == n0                                                       # §0A.3
    D["E"], D["X"] = pd.to_datetime(D.entry_time), pd.to_datetime(D.exit_time)
    D["wt_abs"] = D.wt_top.abs()
    D["wt_neg"] = -D.wt_abs.fillna(0)
    D["order"] = np.arange(len(D))
    proven = (D.side == "LONG") & ((D.stop_pct >= 6) | ((D.stop_rel >= 0.30) & (D.stop_rel < 0.50)))
    D["risk"] = np.where(D.side == "SHORT", RISK["short"], np.where(proven, RISK["proven"], RISK["long_out"]))
    # риск по глубине WT: доказанный лонг с |WT пятой| ≥ 75 — полный, прочий доказанный — половина
    D["risk_wt"] = np.where(proven & (D.wt_abs >= 75), 1.0, D.risk * np.where(proven, 0.5, 1.0))
    print(f"в симуляции {len(D)} сделок · {D.E.min():%Y-%m-%d} → {D.E.max():%Y-%m-%d} · доказанных лонгов "
          f"{int(proven.sum())} · из них |WT|≥75 {int((proven & (D.wt_abs >= 75)).sum())}")
    print(D[["sym", "side", "entry_time", "exit_time", "stop_pct", "pnl_0", "pnl_re", "risk", "wt_top"]].head(3)
          .round(3).to_string(index=False))
    # одновременность: сколько позиций открыто без лимита
    ev = pd.concat([pd.DataFrame({"t": D.E, "d": 1, "r": D.risk}), pd.DataFrame({"t": D.X, "d": -1, "r": -D.risk})])
    ev = ev.sort_values(["t", "d"])
    print(f"без лимита: максимум одновременно {int(ev.d.cumsum().max())} позиций · риска {ev.r.cumsum().max():.1f}% капитала")

    print("\n" + "=" * 112)
    print(f"{'сценарий':<44}{'сделок':>8}{'итог %':>9}{'просадка':>10}{'худший день':>12}{'макс поз.':>10}{'макс риск':>10}{'|WT|≥75':>9}")
    print("=" * 112)
    scen = [("без лимита", dict(slots=None)),
            ("без лимита + дневной лимит −25%", dict(slots=None, daily=DAILY_LIMIT)),
            ("лимит 15", dict(slots=15)), ("лимит 10", dict(slots=10)),
            ("лимит 6 (как в бою) + дневной −25%", dict(slots=6, daily=DAILY_LIMIT)),
            ("лимит 6, приоритет |WT| + дневной −25%", dict(slots=6, prio="wt", daily=DAILY_LIMIT)),
            ("лимит 3", dict(slots=3)),
            ("без лимита, риск по глубине WT", dict(slots=None, risk_col="risk_wt")),
            ("лимит 10, приоритет |WT|, риск по WT", dict(slots=10, prio="wt", risk_col="risk_wt"))]
    res = {}
    for nm, kw in scen:
        r = simulate(D, **kw)
        res[nm] = r
        print(f"{nm:<44}{r['n']:>8}{r['total']:>+9.1f}{r['dd']:>+10.1f}{r['worst_day']:>+12.1f}{r['max_open']:>10}"
              f"{r['max_risk']:>10.1f}{r['wt75']:>9}")
    print("\nпо годам (итог % капитала):")
    for nm in ("без лимита", "лимит 6 (как в бою) + дневной −25%", "лимит 6, приоритет |WT| + дневной −25%",
               "без лимита, риск по глубине WT"):
        print(f"  {nm:<44} {res[nm]['years']}")
    # ── кто занимает слоты: доказанные лонги отдельно (гипотеза: в бою слоты забивает недоказанный поток) ──
    P = D[proven].copy()
    O = D[~proven].copy()
    print("\n" + "=" * 112)
    print(f"ТОЛЬКО ДОКАЗАННЫЕ ЛОНГИ ({len(P)} сд.) и раздельные пулы")
    print("=" * 112)
    scen2 = [("доказанные · без лимита", P, dict(slots=None)),
             ("доказанные · лимит 10", P, dict(slots=10)),
             ("доказанные · лимит 6", P, dict(slots=6)),
             ("доказанные · лимит 6, приоритет |WT|", P, dict(slots=6, prio="wt")),
             ("доказанные · без лимита, риск по WT", P, dict(slots=None, risk_col="risk_wt")),
             ("доказанные · только |WT|≥75, без лимита", P[P.wt_abs >= 75], dict(slots=None)),
             ("недоказанные (лонг вне зоны+шорт) · без лимита", O, dict(slots=None)),
             ("недоказанные · лимит 3", O, dict(slots=3))]
    for nm, T, kw in scen2:
        r = simulate(T, **kw)
        res[nm] = r
        print(f"{nm:<44}{r['n']:>8}{r['total']:>+9.1f}{r['dd']:>+10.1f}{r['worst_day']:>+12.1f}{r['max_open']:>10}"
              f"{r['max_risk']:>10.1f}{r['wt75']:>9}")
    print("\nпо годам:")
    for nm, _, _ in scen2:
        print(f"  {nm:<44} {res[nm]['years']}")
    print("\n⚠️ учёт по закрытию: открытые позиции не переоцениваются → просадка ЗАНИЖЕНА (в кластере капитуляции все "
          "позиции идут вниз одновременно до разворота); маржа, плечо и проскальзывание VST не моделируются.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
