# -*- coding: utf-8 -*-
"""WAVE3_OTE_SHORT — бэктест стратегии, заявленной 28.05 и ни разу не проверенной.

Долг закрывается по требованию Егора (03.09.2026): «долги закрыть и всё перемерить,
т.к. отключали всё это ДО эталонных детекторов и дополнительных слоёв волнового анализа».
Спека: `docs/STRATEGIES/WAVE3_OTE_SHORT.md` (Triple Confluence: Elliott + OTE + Pivot).

Почему перемер обоснован, а не повтор старого:
  · 19.08 — в `ote_retest_setups` починена ПРИЧИННОСТЬ конфлюэнции (раньше сетап на
    баре 100 усиливался гэпом с бара 500 → «35.4% сетапов не существуют причинно»);
  · 28.08 — переписаны `detect_order_blocks`, `find_choch_ote`, `detect_fvg`;
  · 02.09 — пять детекторов сведены на двухслойный эталон OKO-SM;
  · 03.09 — в матрицу добавлен микро-слой структуры.
Все вердикты, вынесенные ДО этих правок, вынесены другим прибором.

СБОРКА ИЗ ГОТОВЫХ КИРПИЧЕЙ (reuse, закон проекта — ничего не пишем заново):
  · `find_swing_highs` + `calculate_n_down`  → фаза Эллиотта на 4h
  · `structure_trend` (4h)                   → сторона и уровень слома
  · `build_ote`                              → OTE-зона отката на 15m
  · `calculate_pivot_points`                 → дневной PP (пространство вниз)
  · WaveTrend из `indicators`                → OS/OB фильтры

ПРИЧИННОСТЬ: старший ТФ берётся ресемплом со `shift(1)` — только ЗАКРЫТЫЙ бар.
Дневной пивот — по ПРЕДЫДУЩЕМУ дню. Вход на баре, следующем за сигналом.

Запуск: python scripts/wave3_ote_short_backtest.py [n_symbols] [tf]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import collect, report, blind_select, COST_LIMIT  # noqa: E402

OTE_LO, OTE_HI = 0.62, 0.79        # уровни ЭТАЛОНА build_ote (канон Егора 02.06),
                                   # спека писала 0.618/0.786 — движок их не знает
IMPULSE_LOOK = 60                  # окно поиска импульса на LTF
HOLD = 96
WT_OB = 60.0                       # спека: WT 15m > +60
WT_OS = -60.0                      # спека: WT 4h НЕ в OS


def _wt(df: pd.DataFrame) -> np.ndarray:
    """WaveTrend тем же калькулятором, что в бою (indicators.calculate_wt)."""
    from core.indicators.indicators import calculate_wt
    d = calculate_wt(df.copy())
    return d["wt1"].values


def _htf_ctx(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Контекст старшего ТФ на сетке младшего. shift(1) = только ЗАКРЫТЫЙ бар."""
    from core.indicators.indicators import find_swing_highs, calculate_n_down

    agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()
    if len(agg) < 120:
        return pd.DataFrame(index=df.index)
    wt_h = _wt(agg)
    # 🔴 Свинги считаем ОДИН раз (пересчёт на каждом баре давал O(n²) и не досчитывался).
    # Причинность сохранена: pivot high на баре k подтверждается только через `period`
    # баров, поэтому на бар i берём свинги с index <= i - period.
    PER = 5
    sw_all = find_swing_highs(agg["high"], period=PER)
    sw_idx = np.array([p["index"] for p in sw_all], dtype=int)
    lo_v = agg["low"].values
    cl_v = agg["close"].values
    n_down, bear = [], []
    for i in range(len(agg)):
        if i < 60:
            n_down.append(0); bear.append(False); continue
        k = int(np.searchsorted(sw_idx, i - PER, side="right"))   # подтверждённые к бару i
        nd = calculate_n_down(sw_all[max(0, k - 6):k]) if k >= 2 else 0
        n_down.append(nd)
        # 🔴 BearBOS должен был случиться НЕДАВНО, а не прямо сейчас: по спеке слом
        # подтверждён, а ЗАТЕМ цена откатывает вверх в OTE. Требование «новый минимум
        # прямо на баре входа» противоречило условию AbovePP (диагностика 03.09:
        # 720 → 15 сетапов) — цена не может одновременно ставить лой и стоять выше пивота.
        j0 = max(0, i - 40)
        broke_now = bool(cl_v[i] < lo_v[j0:i].min()) if i > j0 + 2 else False
        bear.append(broke_now)
    # слом «свежий» = случился в последние BEAR_FRESH баров старшего ТФ
    BEAR_FRESH = 10
    bear_recent = pd.Series(bear).rolling(BEAR_FRESH, min_periods=1).max().astype(bool).values
    out = pd.DataFrame({"htf_n_down": n_down, "htf_bear": bear_recent, "htf_wt": wt_h},
                       index=agg.index)
    return out.shift(1).reindex(df.index, method="ffill")


def _daily_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Дневные PP/S1/S2 по ПРЕДЫДУЩЕМУ дню (иначе look-ahead).
    S1/S2 — цели SHORT по спеке (TP1=S1 ≈0.382, TP2=S2 ≈0.618 дневного диапазона)."""
    from core.indicators.indicators import calculate_pivot_points
    d = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    rows = [calculate_pivot_points(r.high, r.low, r.close) for r in d.itertuples()]
    out = pd.DataFrame({"PP": [x["PP"] for x in rows],
                        "S1": [x["S1"] for x in rows],
                        "S2": [x["S2"] for x in rows]}, index=d.index)
    return out.shift(1).reindex(df.index, method="ffill")


def make_mechanic(n_down_lo: int, n_down_hi: int, use_wt: bool,
                  stop_mode: str = "ote", target: str = "impulse_low"):
    """Механика по чек-листу спеки. n_down диапазон вынесен в параметр:
    бэктест 28.05 показал, что правило СИГНАЛ-СПЕЦИФИЧНО (для divergence инверсия)."""
    def mechanic(df: pd.DataFrame, tf: str) -> list[dict]:
        ctx = _htf_ctx(df, "4h")
        if ctx.empty or "htf_n_down" not in ctx:
            return []
        piv = _daily_pivots(df)
        wt = _wt(df)
        dd = df.reset_index(drop=True)
        h, l, c, o = dd.high.values, dd.low.values, dd.close.values, dd.open.values
        nd = ctx["htf_n_down"].values
        bear = ctx["htf_bear"].values
        hwt = ctx["htf_wt"].values
        ppv = piv["PP"].values
        s1v = piv["S1"].values
        s2v = piv["S2"].values
        n = len(dd)
        out, last = [], -999
        from core.smc.smc_engine import build_ote

        for i in range(IMPULSE_LOOK + 5, n - HOLD - 2):
            if i - last < 12:                     # не толпиться на одном движении
                continue
            # ── HTF: фаза Эллиотта + структура вниз + WT не перепродан
            if not (n_down_lo <= nd[i] <= n_down_hi):
                continue
            if not bear[i]:
                continue
            if np.isfinite(hwt[i]) and hwt[i] < WT_OS:      # спека: WT 4h НЕ в OS
                continue
            # ── MTF: пространство вниз (цена выше дневного PP)
            if not np.isfinite(ppv[i]) or c[i] <= ppv[i]:
                continue
            # ── LTF: импульс вниз и откат в OTE
            seg_hi = int(np.argmax(h[i - IMPULSE_LOOK:i + 1])) + i - IMPULSE_LOOK
            if seg_hi >= i - 3:
                continue
            seg_lo = int(np.argmin(l[seg_hi:i + 1])) + seg_hi
            if seg_lo <= seg_hi or seg_lo >= i:
                continue
            ote = build_ote(float(h[seg_hi]), float(l[seg_lo]))   # импульс ВНИЗ → откат вверх
            lo_, hi_ = ote["levels"][OTE_HI], ote["levels"][OTE_LO]
            zlo, zhi = min(lo_, hi_), max(lo_, hi_)
            if not (zlo <= c[i] <= zhi):
                continue
            if use_wt and not (np.isfinite(wt[i]) and wt[i] > WT_OB):
                continue
            # ── вход на СЛЕДУЮЩЕМ баре, стоп за верх OTE + буфер (спека)
            e = float(o[i + 1])
            # 🔴 ЗАКОН РАЗМЕРА СТОПА. Стоп по спеке (за верх OTE +0.15%) даёт медиану
            # 0.29-0.36% — МЕНЬШЕ костов круга 0.35%. Полный прогон 03.09: все варианты
            # PF 0.26-0.39, средний убыток −0.333% ≈ ровно косты, охват монет 0%.
            # Значит хоронит не фаза Эллиотта и не OTE, а геометрия стопа.
            # `impulse` — стоп за ХАЙ импульса (структурный, шире).
            if stop_mode == "impulse":
                sl = float(h[seg_hi]) * 1.0015
            else:
                sl = zhi * 1.0015
            if sl <= e:
                continue
            # 🔴 ЦЕЛИ ПО СПЕКЕ: TP1 = дневной S1, TP2 = S2 (≈0.382 и 0.618 диапазона).
            # Цель «низ импульса» оказалась слишком близкой: при стопе 2.15% давала
            # WR 66% и PF 0.64 — много мелких плюсов, редкие стопы съедали всё.
            # Асимметрия «стоп короткий, цель дальняя» — суть метода.
            if target == "pivot_s1":
                tp = float(s1v[i]) if np.isfinite(s1v[i]) else float(l[seg_lo])
            elif target == "pivot_s2":
                tp = float(s2v[i]) if np.isfinite(s2v[i]) else float(l[seg_lo])
            else:
                tp = float(l[seg_lo])                 # низ импульса (продолжение волны 3)
            if tp >= e:                                # цель должна быть НИЖЕ входа
                continue
            pnl = None
            for j in range(i + 1, min(i + 1 + HOLD, n)):
                if h[j] >= sl:
                    pnl = (e - sl) / e * 100
                    break
                if l[j] <= tp:
                    pnl = (e - tp) / e * 100
                    break
            if pnl is None:
                pnl = (e - float(c[min(i + HOLD, n - 1)])) / e * 100
            out.append({"entry_bar": i + 1, "side": "short", "pnl_pct": pnl,
                        "n_down": int(nd[i]), "stop_pct": (sl - e) / e * 100})
            last = i
        return out
    return mechanic


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    print(f"WAVE3_OTE_SHORT — первый бэктест спеки от 28.05 (долг закрыт 03.09)")
    print(f"ТФ входа {tf} · контекст 4h (shift(1)) · дневной PP по ПРЕДЫДУЩЕМУ дню\n")

    variants = [
        ("база: стоп OTE, цель низ импульса", 2, 4, False, "ote", "impulse_low"),
        ("стоп за ХАЙ, цель низ импульса", 2, 4, False, "impulse", "impulse_low"),
        ("СПЕКА ЦЕЛИКОМ: стоп за ХАЙ, цель S1", 2, 4, False, "impulse", "pivot_s1"),
        ("стоп за ХАЙ, цель S2 (дальняя)", 2, 4, False, "impulse", "pivot_s2"),
        ("стоп OTE + цель S2 (макс. асимметрия)", 2, 4, False, "ote", "pivot_s2"),
    ]
    best = None
    for name, lo, hi, wt, smode, tgt in variants:
        print("=" * 110)
        print(f"ВАРИАНТ: {name}")
        print("=" * 110)
        try:
            R = collect(make_mechanic(lo, hi, wt, smode, tgt), tf=tf, n_symbols=n_sym, with_flags=False)
        except RuntimeError as e:
            print(f"  {e}\n")
            continue
        p = R.pnl.values
        w, l_ = p[p > 0].sum(), -p[p < 0].sum()
        pf = w / l_ if l_ > 0 else float("inf")
        frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
        cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100
        print(f"  n={len(p)} WR {(p > 0).mean()*100:.1f}% PF {pf:.2f} ср {p.mean():+.3f}% "
              f"мед {np.median(p):+.3f}% стоп {R.stop_pct.median():.2f}% "
              f"безтоп10% {frag:+.1f}% монет+ {cov:.0f}%")
        for y in sorted(R.year.unique()):
            q = R[R.year == y].pnl.values
            if len(q) < 20:
                continue
            ww, ll = q[q > 0].sum(), -q[q < 0].sum()
            print(f"    {y}: n={len(q):4d} PF {ww / ll if ll > 0 else 0:5.2f} ср {q.mean():+6.3f}%")
        print()
        if best is None or pf > best[0]:
            best = (pf, name, R)

    if best is not None:
        pf, name, R = best
        print("=" * 110)
        print(f"ЛУЧШИЙ ВАРИАНТ: {name} (PF {pf:.2f}) — обязательные срезы")
        print("=" * 110)
        report(R)
        if len(R) > 200:
            blind_select(R)


if __name__ == "__main__":
    main()
