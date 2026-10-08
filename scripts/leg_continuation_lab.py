# -*- coding: utf-8 -*-
"""ОТКАТ В НОГЕ ПРИ РАСТУЩЕМ РЫНКЕ — одна гипотеза, заявленная ДО прогона (Егор 08.10: «если рынок рос, возможно
стоит искать механику входа в рост и продолжение»).

H1 (LONG): цена откатила в канон OTE 0.62–0.79 текущей дневной ноги вверх (`legup_ote`) И рынок растёт — дрейф30
вселенной в верхней трети (порог по обычным часам IS). Зеркало H1s (SHORT): откат в OTE ноги вниз при падающем
рынке (нижняя треть). Перебора нет → ярус 2 не нужен; судит карточка яруса 1.

Геометрия — `geo_wide` журнала (стоп 4 ATR / цель 8 ATR от open следующего бара, 72 ч, стоп раньше цели на одном
баре), кост 0.35. События — `joint_trigger_search.py events 12 legup_ote,legdn_ote,ctrl` (кулдаун 72 ч на монету).

Контроль (§2A, два способа, знак Δ обязан совпасть):
  Δr — та же монета, обычные часы сетки ctrl в ±30 дней, кроме ±3 суток вокруг события;
  Δt — другие монеты, обычные часы сетки ctrl в ±1 сутки (тот же момент рынка).
Баланс по ATR% и дрейфу печатается ДО сравнения; расхождение >1.25× — вердикта нет.
Время: 2023–2025 в карточке; 2026 — отложенный год, открывается только если ярус 1 пройден.

Запуск: python scripts/leg_continuation_lab.py
"""
from __future__ import annotations

import sys
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

EV = Path("G:/oko_lab/joint/events")
COST, IS_Y, HOLD = 0.35, (2023, 2024), 2026
R_WIN, R_EXCL, T_WIN = pd.Timedelta(days=30), pd.Timedelta(days=3), pd.Timedelta(days=1)


def _load(name: str) -> pd.DataFrame:
    E = pd.read_parquet(EV / f"{name}.parquet")
    E = E.reset_index().rename(columns={"index": "ts"}) if "ts" not in E.columns else E.reset_index(drop=True)
    E["ts"] = pd.to_datetime(E.ts)
    return E


def controls(E: pd.DataFrame, C: pd.DataFrame, col: str) -> tuple[np.ndarray, np.ndarray]:
    """Парный контроль на каждое событие: Δr (та же монета ±30 дн без ±3 сут) и Δt (другие монеты ±1 сут)."""
    C = C[np.isfinite(C[col].values)]
    by_sym = {s: g.sort_values("ts") for s, g in C.groupby("sym")}
    Cs = C.sort_values("ts")
    tt, vv, ss = Cs.ts.values, Cs[col].values - COST, Cs.sym.values
    cr, ct = np.full(len(E), np.nan), np.full(len(E), np.nan)
    for k, (s, t) in enumerate(zip(E.sym.values, E.ts.values)):
        g = by_sym.get(s)
        if g is not None:
            d = g.ts.values - t
            w = (np.abs(d) <= R_WIN.to_timedelta64()) & (np.abs(d) > R_EXCL.to_timedelta64())
            if w.sum() >= 3:
                cr[k] = g[col].values[w].mean() - COST
        a, b = np.searchsorted(tt, t - T_WIN.to_timedelta64()), np.searchsorted(tt, t + T_WIN.to_timedelta64())
        if b - a >= 5:
            o = ss[a:b] != s
            if o.sum() >= 5:
                ct[k] = vv[a:b][o].mean()
    return cr, ct


def run(trig: str, side: str, regime: str) -> None:
    E, C = _load(trig), _load("ctrl")
    col = f"geo_wide_{side.lower()}"
    E["pnl"] = E[col].astype(float) - COST
    E = E[np.isfinite(E.pnl.values) & np.isfinite(E.mkt_drift30.values)].reset_index(drop=True)
    assert set(E.side) == {side}                                              # §0A.3
    y, cy = E.ts.dt.year.values, C.ts.dt.year.values
    lo, hi = np.nanquantile(C.mkt_drift30.values[np.isin(cy, IS_Y)], [1 / 3, 2 / 3])
    cand = (E.mkt_drift30.values >= hi) if regime == "up" else (E.mkt_drift30.values <= lo)
    # §0A.2: трети по обычным часам IS; кандидат целиком по нужную сторону порога, остальные — по другую
    assert hi > lo
    dv = E.mkt_drift30.values
    assert (dv[cand] >= hi).all() and (dv[~cand] < hi).all() if regime == "up" else \
        (dv[cand] <= lo).all() and (dv[~cand] > lo).all()
    print("=" * 110)
    print(f"{trig} → {side} · кандидат: рынок {'РАСТЁТ (дрейф30 ≥ ' + f'{hi:+.1f})' if regime == 'up' else 'ПАДАЕТ (дрейф30 ≤ ' + f'{lo:+.1f})'}"
          f" · исход {col} − {COST}")
    print("=" * 110)
    E["ctrl_r"], E["ctrl_t"] = controls(E, C, col)
    act = ~(y == HOLD)
    # баланс ДО сравнения (§2A): ATR% и дрейф у события и у его контролей
    Cc = C[np.isfinite(C[col].values)]
    for nm, mm in (("кандидат", cand & act), ("остальные события", ~cand & act)):
        e_atr = np.nanmedian(E.atr_pct.values[mm])
        cr_atr = np.nanmedian(Cc.atr_pct.values[np.isin(Cc.sym.values, E.sym.values[mm])])
        print(f"  баланс {nm:<18} n {int(mm.sum()):>6} · ATR% события {e_atr:.2f} · ATR% обычных часов тех же монет "
              f"{cr_atr:.2f} (×{e_atr / cr_atr:.2f}) · доля с Δr {np.isfinite(E.ctrl_r.values[mm]).mean() * 100:.0f}% · "
              f"с Δt {np.isfinite(E.ctrl_t.values[mm]).mean() * 100:.0f}%")
    print(f"\n  {'год':<6}{'n':>6}{'средн':>8}{'медиана':>9}{'Δr':>8}{'Δt':>8}   (кандидат; Δ = событие − контроль)")
    for yy in sorted(set(y) - {HOLD}):                 # 2026 отложен: открывается только после яруса 1
        m = cand & (y == yy)
        if m.sum() < 20:
            continue
        a = E[m]
        print(f"  {yy:<6}{m.sum():>6}{a.pnl.mean():>+8.2f}{a.pnl.median():>+9.2f}"
              f"{np.nanmean(a.pnl - a.ctrl_r):>+8.2f}{np.nanmean(a.pnl - a.ctrl_t):>+8.2f}")
    a = E[cand & act]
    rr, rt = np.nanmean(a.pnl - a.ctrl_r), np.nanmean(a.pnl - a.ctrl_t)
    print(f"  {'всё':<6}{len(a):>6}{a.pnl.mean():>+8.2f}{a.pnl.median():>+9.2f}{rr:>+8.2f}{rt:>+8.2f}"
          f"   знаки Δr/Δt {'СОВПАЛИ' if np.sign(rr) == np.sign(rt) else '🔴 РАЗОШЛИСЬ — контроль не определён'}")
    print(E.loc[cand & act, ["sym", "ts", "close", "atr_pct", "mkt_drift30", "pnl", "ctrl_r", "ctrl_t"]]
          .head(4).round(3).to_string(index=False))
    D = V.normalize(E[act].rename(columns={"ctrl_r": "ctrl"}), pnl="pnl", ts="ts", liq="liq")
    V.card(D, cand[act], name=f"{trig} × рынок {'растёт' if regime == 'up' else 'падает'} (дрейф30 треть)",
           study="leg-continuation", geo=("atr_pct", "legup_span_pct" if side == "LONG" else "legdn_span_pct"))


def wide_stop(open_holdout: bool = False) -> None:
    """08.10, ПОСЛЕ взгляда (гипотеза №N журнала, не заявленная): в портфеле поток отката при равном риске в минусе
    в 2024–25, а плюс во все три года — только у широкого стопа (верхняя треть 4·ATR%). Закон размера стопа
    ([[stop_zone_survived_blind_test]]). Порог — по IS 2023-24; судят и %, и R (деньги при риске на сделку)."""
    E, C = _load("legup_ote"), _load("ctrl")
    E["pnl"] = E.geo_wide_long.astype(float) - COST
    E = E[np.isfinite(E.pnl.values) & np.isfinite(E.mkt_drift30.values) & np.isfinite(E.atr_pct.values)]
    hi = np.nanquantile(C.mkt_drift30.values[np.isin(C.ts.dt.year.values, IS_Y)], 2 / 3)
    E = E[E.mkt_drift30.values >= hi].reset_index(drop=True)
    E["stop_pct"] = 4.0 * E.atr_pct                      # ≈ стоп 4 ATR (ATR на баре сигнала / close, вход — open след.)
    E["R"] = E.pnl / E.stop_pct
    y = E.ts.dt.year.values
    thr = np.quantile(E.stop_pct.values[np.isin(y, IS_Y)], 2 / 3)
    cand = E.stop_pct.values >= thr
    assert (E.stop_pct.values[cand] >= thr).all() and set(E.side) == {"LONG"}   # §0A.3
    print("=" * 110)
    print(f"ОТКАТ В РОСТЕ × ШИРОКИЙ СТОП (≥ {thr:.2f}% = верхняя треть IS) · рынок дрейф30 ≥ {hi:+.2f}")
    print("=" * 110)
    print(E.loc[cand, ["sym", "ts", "atr_pct", "stop_pct", "pnl", "R"]].head(4).round(3).to_string(index=False))
    act = y < HOLD
    for unit in ("pnl", "R"):
        D = V.normalize(E[act].assign(pnl=E[unit][act]), pnl="pnl", ts="ts", liq="liq")
        V.card(D, cand[act], name=f"legup_ote × рост × стоп ≥ треть IS ({unit})", study="leg-continuation",
               geo=("mkt_drift30",))
    if open_holdout:
        for unit in ("pnl", "R"):
            D = V.normalize(E[~act].assign(pnl=E[unit][~act]), pnl="pnl", ts="ts", liq="liq")
            V.card(D, cand[~act], name=f"legup_ote × рост × стоп ≥ треть IS ({unit})", study="leg-continuation",
                   geo=("mkt_drift30",), holdout=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "wide":
        wide_stop(open_holdout=len(sys.argv) > 2 and sys.argv[2] == "holdout")
    else:
        run("legup_ote", "LONG", "up")
        print()
        run("legdn_ote", "SHORT", "down")
