# -*- coding: utf-8 -*-
"""ОТКУДА В КОМБИНАТОРЕ WR 92-100% (13.08.2026, Даат).

Наборы arch104 (200 паттернов) и ds_patterns в ote_setups.yaml заявлены с WR 75–100%
и avgR 1.2–1.98. В бою те же паттерны дают WR 16–44% и МИНУС по деньгам на всех 25
группах с n≥20. Разрыв Δ WR до −73 п.п. — это не «просадка эджа», это разные метрики.

Гипотезы (проверяются здесь, а не рассуждением):
  H1. WR считает победой любой плюсовой ход: `(arr > 0).mean()`, а при недостижении
      ни TP, ни SL ставится R = ход/стоп → +0.01R попадает в WR как «выигрыш».
  H2. Приоритет TP при равенстве баров: `argmax(ht) <= argmax(hs)` → когда TP и SL
      задеты на ОДНОМ баре, засчитывается TP (биржа бьёт touch, стоп первым).
  H3. Косты не вычитаются вовсе.

Метод: воспроизводим simulate() комбинатора на нашем кэше БЕЗ единого паттерна —
на голой базе. Если база уже даёт WR ~90%, дело в определении метрики, и ни один
из 14 789 паттернов комбинатора не был отобран по деньгам.

Запуск:  python scripts/combinator_wr_diagnosis.py [--coins 30]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
COST = 0.35
TP_R = 2.0            # константы комбинатора
FUTURE_BARS = 12


def simulate_asis(df, tp_r=TP_R, future=FUTURE_BARS, sl_first=False):
    """Копия tools/pattern_mining/combinator_v2.py::simulate.
    sl_first=True — единственное изменение: при равенстве баров побеждает СТОП."""
    n = len(df)
    high, low, close = df.high.values, df.low.values, df.close.values
    r_long = np.full(n, np.nan)
    kind = np.full(n, "", dtype=object)     # чем закончилось: TP / SL / TIME
    stop_pct = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        sl_l = low[i - 10:i + 1].min() * 0.999
        sld = price - sl_l
        if sld > 0 and sld / price < 0.06:
            tp = price + sld * tp_r
            fh = high[i + 1:i + 1 + future]
            fl = low[i + 1:i + 1 + future]
            ht, hs = (fh >= tp), (fl <= sl_l)
            stop_pct[i] = sld / price * 100
            if ht.any() and hs.any():
                tp_wins = (np.argmax(ht) < np.argmax(hs)) if sl_first \
                    else (np.argmax(ht) <= np.argmax(hs))
                r_long[i] = tp_r if tp_wins else -1.0
                kind[i] = "TP" if tp_wins else "SL"
            elif ht.any():
                r_long[i] = tp_r; kind[i] = "TP"
            elif hs.any():
                r_long[i] = -1.0; kind[i] = "SL"
            else:
                r_long[i] = (close[i + future] - price) / sld
                kind[i] = "TIME"
    return r_long, kind, stop_pct


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=30)
    ap.add_argument("--since", type=int, default=2023)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 104)
    print(f"ДИАГНОЗ WR КОМБИНАТОРА · ТФ 1h · TP={TP_R}R · горизонт {FUTURE_BARS} баров · "
          f"{len(syms)} монет с {a.since}")
    print("механика simulate() воспроизведена ДОСЛОВНО, БЕЗ ЕДИНОГО ПАТТЕРНА (голая база)")
    print("═" * 104)

    R, K, S = [], [], []
    Rsl = []
    for sym in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe='1h' AND time>=? ORDER BY time", c, params=(sym, t0))
        c.close()
        if len(d) < 300:
            continue
        r, k, s = simulate_asis(d)
        r2, _, _ = simulate_asis(d, sl_first=True)
        m = ~np.isnan(r)
        R.append(r[m]); K.append(k[m]); S.append(s[m]); Rsl.append(r2[m])
    r = np.concatenate(R); k = np.concatenate(K); s = np.concatenate(S)
    rsl = np.concatenate(Rsl)

    wr = 100 * (r > 0).mean()
    print(f"\nвсего сигналов (каждый бар — сигнал): {len(r)}")
    print(f"медиана стопа: {np.median(s):.2f}%  (косты {COST}% = "
          f"{100 * COST / np.median(s):.0f}% от стопа)")
    print(f"\n🔴 WR как считает комбинатор `(R>0).mean()`:  {wr:.1f}%")
    print(f"   avgR:                                      {r.mean():+.3f}")

    print(f"\n=== H1: ИЗ ЧЕГО СОСТОИТ ЭТОТ WR ===")
    print(f"{'исход':<24} {'доля':>8} {'вклад в WR':>12} {'медиана R':>11}")
    for nm in ("TP", "SL", "TIME"):
        sub = r[k == nm]
        share = 100 * len(sub) / len(r)
        contrib = 100 * ((sub > 0).sum()) / len(r)
        print(f"{nm:<24} {share:>7.1f}% {contrib:>11.1f}% {np.median(sub):>+10.3f}")
    tim = r[k == "TIME"]
    print(f"\n➜ из {100 * len(tim) / len(r):.1f}% сделок, закрытых ПО ВРЕМЕНИ, "
          f"{100 * (tim > 0).mean():.1f}% попали в WR как «победа»")
    print(f"   их медианный R = {np.median(tim):+.3f} — это ход в доли стопа, а не цель")
    print(f"   WR только по РЕАЛЬНО дошедшим до цели (TP из TP+SL): "
          f"{100 * (k == 'TP').sum() / max(1, (k != 'TIME').sum()):.1f}%")

    print(f"\n=== H2: ПРИОРИТЕТ TP ПРИ РАВЕНСТВЕ БАРОВ ===")
    print(f"WR как есть (TP выигрывает ничью):   {wr:>6.1f}%   avgR {r.mean():+.3f}")
    print(f"WR если ничью выигрывает СТОП:       {100 * (rsl > 0).mean():>6.1f}%   "
          f"avgR {rsl.mean():+.3f}")
    print(f"➜ цена допущения: {r.mean() - rsl.mean():+.3f}R на сделку")

    print(f"\n=== H3: ТО ЖЕ САМОЕ, НО В ДЕНЬГАХ (% net, косты {COST}%) ===")
    pct = r * s - COST          # R × размер стопа в % − косты
    pct_nc = r * s              # без костов
    print(f"{'метрика':<34} {'значение':>12}")
    print(f"{'avgR (метрика комбинатора)':<34} {r.mean():>+11.3f}R")
    print(f"{'% на сделку БЕЗ костов':<34} {pct_nc.mean():>+11.3f}%")
    print(f"{'% на сделку С костами':<34} {pct.mean():>+11.3f}%")
    print(f"{'WR по деньгам (net>0)':<34} {100 * (pct > 0).mean():>11.1f}%")
    print(f"➜ косты съедают {abs(pct_nc.mean() - pct.mean()) / max(1e-9, abs(pct_nc.mean())) * 100:.0f}% "
          f"результата базы")

    print(f"\n=== ЧТО ЭТО ЗНАЧИТ ДЛЯ ОТБОРА 14 789 ПАТТЕРНОВ ===")
    print(f"score_fn = avgR × (WR/100) × log(n) — обе величины завышены системно:")
    print(f"  • WR завышен на {wr - 100 * (pct > 0).mean():.1f} п.п. (победа = любой плюсовой ход)")
    print(f"  • avgR не знает костов, а косты = {100 * COST / np.median(s):.0f}% медианного стопа")
    print(f"Отбор шёл по метрике, не связанной с деньгами → ранг паттернов не переносится в бой.")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
