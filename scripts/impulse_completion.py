"""
impulse_completion.py — ЗАВЕРШЁН ЛИ ИМПУЛЬС В МОМЕНТ РЕГИСТРАЦИИ СЕТАПА (30.08.2026).

Запрос Егора: «для нас важно знать завершённость импульса и верно построить зоны OTE.
механика отслеживания коррекции такого импульса важна и конфлюенции MTF в зоне OTE
как подтверждение».

🔴 ЧТО ПОКАЗАЛА РАЗВЕДКА КОДА (не предположение — `core/smc/impulse_fib.py:84-160`):
**завершённость импульса не проверяется вообще.** `find_impulses` идёт по барам и на
КАЖДОМ баре `b` ищет самый длинный ход `[a..b]`, проходящий два условия:
    ход/ATR >= 3.0      (MIN_ATR)   — амплитуда
    контр-откат <= 32%  (MAX_RETR)  — чистота
Дедуп идёт по НАЧАЛУ импульса (`seen` по `(a, up)`), поэтому сетап рождается на ПЕРВОМ
баре, где ход квалифицировался. Если ход после этого продолжается — сетап уже создан,
и вся геометрия (вход `0.382·amp`, цель `1.618·amp`, стоп) построена от вершины,
КОТОРОЙ ЕЩЁ НЕТ.

Здесь мы это измеряем: как часто импульс продолжается после регистрации, и хуже ли
такие сетапы. Если хуже — «завершённость» становится гейтом, а не пожеланием.

🔴 ЧЕСТНАЯ ОГОВОРКА О ПРИРОДЕ ЗАМЕРА: он ДИАГНОСТИЧЕСКИЙ и смотрит вперёд. Применить
результат нельзя «бесплатно»: чтобы узнать, что импульс завершён, надо ПОДОЖДАТЬ K баров
без нового экстремума, то есть отложить вход. Цена ожидания — цена уходит, откат может
начаться без нас. Поэтому здесь же печатается, сколько сетапов ВЫЖИВАЕТ ожидание
(откат до входа случился ПОСЛЕ подтверждения, а не во время).

    python scripts/impulse_completion.py --tf 1h
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import load, stat, line       # noqa: E402

KS = (3, 6, 12, 24)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--pq", default=None)
    a = ap.parse_args()
    pq = Path(a.pq) if a.pq else ROOT / "cache" / f"matrix_core_{a.tf}.parquet"

    X = pd.read_parquet(pq)
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    print("=" * 104)
    print(f"ЗАВЕРШЁННОСТЬ ИМПУЛЬСА · {pq.name} · {len(X)} сделок · {X.sym.nunique()} монет")
    print("=" * 104)
    print("метрика: был ли НОВЫЙ ЭКСТРЕМУМ в направлении импульса за K баров после его конца")

    # OHLCV грузим по одному разу на символ
    ext = {k: np.zeros(len(X), dtype=bool) for k in KS}
    over = np.full(len(X), np.nan)              # насколько ушёл дальше, в % от amp
    pos = {s: i for i, s in enumerate(X.columns)}
    for sym, grp in X.groupby("sym"):
        try:
            df = load(sym, a.tf)
        except Exception:                        # noqa: BLE001
            continue
        H, L = df.high.values, df.low.values
        n = len(df)
        for ridx, row in grp.iterrows():
            b = int(row.signal_bar)
            if b <= 0 or b >= n - 1:
                continue
            up = row.side == "long"
            iloc = X.index.get_loc(ridx)
            base = H[b] if up else L[b]
            for k in KS:
                hi = min(b + 1 + k, n)
                if hi <= b + 1:
                    continue
                seg = H[b + 1:hi] if up else L[b + 1:hi]
                if len(seg) and ((seg.max() > base) if up else (seg.min() < base)):
                    ext[k][iloc] = True
            hi = min(b + 1 + max(KS), n)
            seg = H[b + 1:hi] if up else L[b + 1:hi]
            if len(seg) and row.amp_pct and row.amp_pct > 0:
                d = ((seg.max() - base) if up else (base - seg.min())) / base * 100
                over[iloc] = max(d, 0.0) / row.amp_pct * 100      # в % от амплитуды

    X = X.assign(**{f"cont{k}": ext[k] for k in KS}, over_pct=over)

    print("\n1. КАК ЧАСТО ИМПУЛЬС ПРОДОЛЖАЕТСЯ ПОСЛЕ РЕГИСТРАЦИИ")
    print(f"   {'K баров':<10} {'продолжился':>13} {'доля':>7}")
    for k in KS:
        c = int(X[f"cont{k}"].sum())
        print(f"   {k:<10} {c:>13} {c/len(X)*100:>6.0f}%")
    ov = X.over_pct.dropna()
    if len(ov):
        print(f"   насколько уходит дальше (в % от амплитуды импульса): "
              f"медиана {ov.median():.0f}% · 75-й {ov.quantile(0.75):.0f}% · 90-й {ov.quantile(0.90):.0f}%")

    print("\n2. ЗАВЕРШЁННЫЕ ПРОТИВ ПРОДОЛЖИВШИХСЯ — есть ли разница в деньгах")
    b_all = stat(X)
    for k in KS:
        col = f"cont{k}"
        print(f"\n   ── подтверждение K={k} баров ──")
        for nm, m in (("ЗАВЕРШЁН (нового экстремума нет)", ~X[col]),
                      ("продолжился", X[col])):
            s = stat(X[m])
            if s:
                print(line(X[m], f"     {nm:<34}") +
                      f"  ×{s['pf']/b_all['pf']:.2f}")

    print("\n3. РАЗРЕЗ ПО СТОРОНАМ (K=6) — правило может быть односторонним")
    for side in ("long", "short"):
        S = X[X.side == side]
        bs = stat(S)
        if not bs:
            continue
        print(f"   ── {side} (база PF {bs['pf']:.2f}) ──")
        for nm, m in (("ЗАВЕРШЁН", ~S.cont6), ("продолжился", S.cont6)):
            s = stat(S[m])
            if s:
                print(line(S[m], f"     {nm:<34}") + f"  ×{s['pf']/bs['pf']:.2f}")

    print("\n4. ПО ГОДАМ (K=6, только ЗАВЕРШЁННЫЕ) — не живёт ли эффект в одном годе")
    for y in sorted(X.year.dropna().unique()):
        g = X[X.year == y]
        s, bb = stat(g[~g.cont6]), stat(g)
        if s and bb and bb["pf"]:
            print(f"   {int(y)}: PF {s['pf']:5.2f} (n={s['n']:>4}) против базы года "
                  f"{bb['pf']:5.2f}  ×{s['pf']/bb['pf']:.2f}  безтоп10% {s['bt']:+7.0f}")

    print("\n5. ЦЕНА ОЖИДАНИЯ — сколько сетапов ПЕРЕЖИВАЕТ задержку входа на K баров")
    print("   🔴 замер выше диагностический (смотрит вперёд). Чтобы применить правило,")
    print("   вход надо отложить на K баров — а за это время откат может пройти без нас.")
    print("   Здесь: доля сделок, у которых ФИЛЛ случился ПОЗЖЕ подтверждения.")
    if "entry_bar" in X.columns:
        for k in KS:
            surv = (X.entry_bar - X.signal_bar) > k
            print(f"   K={k:<3}: переживают {int(surv.sum()):>5} из {len(X)} ({surv.mean()*100:>3.0f}%)")
    else:
        lag = (X._ts - X._ts).dt.total_seconds()      # entry_bar не сохранён
        print("   🔴 `entry_bar` в матрице НЕ сохранён — цену ожидания посчитать нечем.")
        print("   Это отдельный дефект инструмента: без него правило неприменимо к бою.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
