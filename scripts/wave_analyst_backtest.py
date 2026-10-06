#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ЗАМЕР ВОЛНОВОГО РАЗБОРА: платят ли ЗОНА СХОЖДЕНИЯ, НОМЕР ВОЛНЫ и ЯСНОСТЬ СЦЕНАРИЯ.

Повод (Егор 06.10): «изучи принципы волн и пойми где искать зоны… смотри снимки
графиков глазами, а не в коде». Посмотрел — и увидел то, чего не было ни в одном
моём замере за сутки:

  BTC  волна 3, зона 86623–90068 = СХОЖДЕНИЕ ВОСЬМИ уровней (W R2, M R1, фибо-цель
       волны 3, W R1, D R2, начало дневной ноги, D R1, фибо 0.886 дневной ноги)
  ETH  РАЗВИЛКА: два счёта разом — ABC-коррекция (шорт) ИЛИ (iii) из 3 (лонг),
       потому что точка 4 зашла в диапазон первой (правило R3 → импульса нет)
  XRP  волна 4, и разбор честно пишет «зоны схождения НЕТ» (score отсутствует)

Пять отрицательных результатов 05–06.10 получились потому, что я мерил «есть ли
признак рядом» и мешал в одну кучу: сделки с восемью сошедшимися уровнями и с нулём,
волну 3 (цена идёт к целям) и волну 5 (ловушка по канону), ясный счёт и развилку.

Здесь мерим ровно три вещи, которые даёт сам разбор (`core/waves/wave_analyst.analyze`):
    score   — вес схождения уровней в зоне (`zone.score`)
    k       — номер волны (`progress.k`, метки `labels`)
    сценарии— сколько их: 1 = ясно, 2 = развилка

Вход/стоп/цель берём ИЗ СЦЕНАРИЯ, а не выдумываем: `invalid` = стоп, первая цель = TP.

🔴 ПРИЧИННОСТЬ. `analyze(now=t)` получает ряды, обрезанные по t (как это делает
`report_for` через `closed_bars(..., now=t)`). Движок сам объявлен каузальным
(«только закрытые бары»). Шаг по истории — сутки, чтобы соседние сделки не были
одним и тем же сетапом.

Запуск:
    python scripts/wave_analyst_backtest.py --coins 20 --step 6
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

from core.waves.wave_analyst import analyze          # noqa: E402
from research_harness import load, universe, core_universe   # noqa: E402

COST = 0.35          # LIMIT, как во всех наших замерах
TTL_BARS = 60        # держим, баров 4h (≈10 суток)


def _num(x):
    """Первое число из строки вида 'выше 67251.7 — это уже (iii) из 3'."""
    if x is None:
        return None
    if isinstance(x, (int, float)) and x == x:
        return float(x)
    m = re.search(r"(\d+\.?\d*)", str(x).replace(" ", ""))
    return float(m.group(1)) if m else None


def _side(sc: dict) -> str | None:
    s = str(sc.get("side") or "").lower()
    if "шорт" in s or "short" in s:
        return "short"
    if "лонг" in s or "long" in s:
        return "long"
    return None


def resolve(H, L, C, j, side, entry, sl, tp, ttl=TTL_BARS) -> float:
    end = min(j + ttl, len(C) - 1)
    for k in range(j, end + 1):
        if side == "long":
            if L[k] <= sl:
                return (sl - entry) / entry * 100
            if H[k] >= tp:
                return (tp - entry) / entry * 100
        else:
            if H[k] >= sl:
                return (entry - sl) / entry * 100
            if L[k] <= tp:
                return (entry - tp) / entry * 100
    return ((C[end] - entry) if side == "long" else (entry - C[end])) / entry * 100


def run_symbol(sym: str, step: int, warmup: int = 400) -> list[dict]:
    dh = load(sym, "4h")
    d1 = load(sym, "1h")
    d15 = load(sym, "15m")
    if dh is None or len(dh) < warmup + 200:
        return []
    H, L, C = dh.high.values, dh.low.values, dh.close.values
    out = []
    for t in range(warmup, len(dh) - TTL_BARS - 1, step):
        now = dh.index[t]
        # срезы по времени = то же, что closed_bars(..., now=t)
        _dh = dh.iloc[max(0, t - 1500):t + 1]
        _d1 = d1[d1.index <= now].tail(1500) if d1 is not None else None
        _d15 = d15[d15.index <= now].tail(600) if d15 is not None else None
        try:
            r = analyze(sym.split("/")[0], _dh, _d15, "15m", now=now, d1=_d1, dl15=_d15)
        except Exception:                            # noqa: BLE001
            continue
        scs = r.get("scenarios") or []
        if not scs:
            continue
        zone = r.get("zone") if isinstance(r.get("zone"), dict) else {}
        prog = r.get("progress") or {}
        price = float(C[t])
        # берём ПЕРВЫЙ сценарий (разбор ставит основной первым)
        sc = scs[0]
        side = _side(sc)
        if side is None:
            continue
        tgts = [v for _, v in (sc.get("targets") or []) if v is not None and v == v]
        sl = _num(sc.get("invalid"))
        if not tgts or sl is None or sl <= 0:
            continue
        tp = float(tgts[0])
        # геометрия должна быть осмысленной: стоп и цель по разные стороны цены
        if side == "long" and not (sl < price < tp):
            continue
        if side == "short" and not (tp < price < sl):
            continue
        risk = abs(price - sl) / price * 100
        if risk <= 0.2 or risk > 25:
            continue
        pnl = resolve(H, L, C, t, side, price, sl, tp) - COST
        lbl = (prog.get("labels") or [])
        out.append(dict(
            sym=sym, t=str(now)[:16], year=int(now.year), side=side, pnl=pnl,
            score=float(zone.get("score") or 0.0),
            n_levels=len(zone.get("levels") or []),
            has_zone=int(bool(zone.get("score"))),
            k=int(prog.get("k") or 0),
            wave=str(lbl[-1]) if lbl else "?",
            n_scen=len(scs),
            clear=int(len(scs) == 1),
            risk=round(risk, 2),
            rr=round(abs(tp - price) / max(1e-9, abs(price - sl)), 2),
        ))
    return out


def stat(v: pd.DataFrame) -> dict | None:
    if len(v) < 25:
        return None
    p = v["pnl"].values
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    return dict(n=len(p), wr=(p > 0).mean() * 100, pf=pos / neg if neg > 0 else 9.99,
                mean=p.mean(), med=np.median(p), total=p.sum(),
                frail=np.sort(p)[:max(1, int(len(p) * 0.9))].sum(),
                cov=(v.groupby("sym")["pnl"].sum() > 0).mean() * 100)


def show(nm: str, s: dict | None, base: dict | None = None):
    if s is None:
        print(f"  {nm:<34} — мало сделок")
        return
    flow = f"{s['n'] / base['n'] * 100:>5.0f}%" if base else "  база"
    print(f"  {nm:<34}{flow}{s['n']:>6}{s['wr']:>7.1f}%{s['pf']:>7.2f}"
          f"{s['mean']:>+8.3f}{s['med']:>+8.3f}{s['total']:>+9.0f}"
          f"{s['frail']:>+10.0f}{s['cov']:>7.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=20)
    ap.add_argument("--step", type=int, default=6, help="шаг по 4h-барам (6 = сутки)")
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--save", default="oko_feed/wave_analyst_bt.parquet")
    a = ap.parse_args()

    syms = core_universe("4h", n=a.coins) if a.core else universe("4h", n=a.coins)
    print(f"ЗАМЕР ВОЛНОВОГО РАЗБОРА · монет {len(syms)} · шаг {a.step} баров 4h · "
          f"TTL {TTL_BARS} · косты {COST}%")
    print("Вход/стоп/цель — ИЗ СЦЕНАРИЯ разбора, не выдуманы\n")

    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.step)
        except Exception as e:                       # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · сделок {len(rows)}", flush=True)
    if not rows:
        print("🔴 НОЛЬ сделок — это отказ, а не вывод.")
        return 1

    R = pd.DataFrame(rows)
    try:
        R.to_parquet(a.save)
        print(f"\nвыборка сохранена: {a.save}")
    except Exception:                                # noqa: BLE001
        pass
    print(f"собрано: {len(R)} сделок · {R.sym.nunique()} монет · годы {sorted(R.year.unique())}")
    print(f"зона есть у {R.has_zone.mean()*100:.0f}% · развилка (2 сценария) у "
          f"{(R.n_scen > 1).mean()*100:.0f}% · стороны: "
          f"{dict(R.side.value_counts())}")

    base = stat(R)
    print(f"\n{'клетка':<34}{'поток':>6}{'n':>6}{'WR':>8}{'PF':>7}"
          f"{'средн':>8}{'медиана':>8}{'сумма':>9}{'безтоп10%':>10}{'монет+':>7}")
    show("ВСЁ (база)", base)

    print("  — 1) ЗОНА СХОЖДЕНИЯ —")
    show("зоны нет", stat(R[R.has_zone == 0]), base)
    for lo in (1, 4, 6, 8):
        show(f"score ≥ {lo}", stat(R[R.score >= lo]), base)

    print("  — 2) ЯСНОСТЬ СЦЕНАРИЯ —")
    show("один сценарий (ясно)", stat(R[R.clear == 1]), base)
    show("развилка (2 сценария)", stat(R[R.clear == 0]), base)

    print("  — 3) НОМЕР ВОЛНЫ —")
    for w, g in R.groupby("wave"):
        if len(g) >= 25:
            show(f"волна «{w}»", stat(g), base)

    print("  — КОМБИНАЦИЯ (то, что видно глазами) —")
    show("score ≥ 4 И один сценарий", stat(R[(R.score >= 4) & (R.clear == 1)]), base)
    show("score ≥ 6 И один сценарий", stat(R[(R.score >= 6) & (R.clear == 1)]), base)

    print("\nПО СТОРОНАМ (score ≥ 4 И ясно):")
    for sd in ("long", "short"):
        S = R[R.side == sd]
        b = stat(S)
        if b is None:
            continue
        show(f"{sd}: база", b)
        show(f"{sd}: score≥4 и ясно", stat(S[(S.score >= 4) & (S.clear == 1)]), b)

    print("\nПО ГОДАМ (score ≥ 4 И ясно против базы):")
    for y, g in R.groupby("year"):
        b = stat(g)
        w = stat(g[(g.score >= 4) & (g.clear == 1)])
        if b is None:
            continue
        ws = f"PF {w['pf']:.2f} сум {w['total']:+.0f} n={w['n']}" if w else "мало"
        print(f"  {int(y)}  n={b['n']:>5}  база PF {b['pf']:.2f} сум {b['total']:+.0f}  |  {ws}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
