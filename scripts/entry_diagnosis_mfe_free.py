# -*- coding: utf-8 -*-
"""ДИАГНОЗ ВХОДА: рынок не даёт хода — или мы входим не в тот момент? (12.08.2026)

Дизайн предложен DS, согласуется с роем (5/5 предупредили о look-ahead в MFE):
  MFE_free = максимальный ход в сторону сделки за ФИКСИРОВАННОЕ окно N баров,
  НЕ ограниченный нашим стопом и TTL. Наш `max_R_possible` обрезан ранним стопом
  (SL = 42% выборки), поэтому по нему нельзя судить, даёт ли рынок ход.

Диагноз по DS:
  A = MFE_free на барах, где сигнал БЫЛ, но входа не случилось (пропущенные)
  B = MFE_free на фактических входах
  медиана A ≈ B  → рынок не даёт хода (механику хоронить)
  медиана A >> B → входим не в тот момент (чинить триггер)

Плюс «потолок идеального входа»: лучший вход в окне ±N. Если и потолок низкий —
механика мертва, а не сломана.

Запуск:  python scripts/entry_diagnosis_mfe_free.py [n_монет=60]
"""
import datetime as dt
import sqlite3
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
N_FWD = 16          # окно MFE_free (16 баров 15m = 4 часа)
COST = 0.35


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i-1]) if cv[i-1] > u[i-1] else up[i]
        d_[i] = min(dn[i], d_[i-1]) if cv[i-1] < d_[i-1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i-1] else (-1 if cv[i] < u[i-1] else dirn[i-1])
    return dirn


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
con = sqlite3.connect(DB)
syms = [r[0] for r in con.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
    "GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT ?", (t0, NCOIN)).fetchall()]
con.close()

# A — сигнал БЕЗ разворота (как входит БОЙ), B — сигнал С разворотом (как требует БЭКТЕСТ)
A, B, ideal, base_all = [], [], [], []
for s in syms:
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='15m' AND time>=? ORDER BY time", c, params=(s, t0))
    c.close()
    if len(d) < 5000:
        continue
    w = wt(d); tr_ = atrt(d)
    H, L, C, O = d.high.values, d.low.values, d.close.values, d.open.values
    n = len(d)
    for i in range(120, n - N_FWD - 1):
        if not (tr_[i] > 0 and w[i] < -60):
            continue
        e = C[i]
        sl = L[max(0, i - 3):i + 1].min() * 0.997
        if sl >= e:
            continue
        one_r = e - sl
        stop_pct = one_r / e * 100
        if not (4.0 < stop_pct <= 12.0):
            continue
        # MFE_free: лучший ход ВВЕРХ за N баров, в R, без стопа и TTL
        mfe_free = (H[i + 1:i + 1 + N_FWD].max() - e) / one_r
        rising = w[i] > w[i - 1]
        (B if rising else A).append(mfe_free)
        # потолок: лучший вход в окне ±4 бара (обе стороны — это ОЦЕНКА ПОТОЛКА, не стратегия)
        lo = max(120, i - 4); hi = min(n - N_FWD - 1, i + 4)
        best = max(((H[j + 1:j + 1 + N_FWD].max() - C[j]) / one_r) for j in range(lo, hi + 1))
        ideal.append(best)
    base_all.append(s)


def rep(name, v):
    if len(v) < 50:
        print(f"  {name:<44} n={len(v)} — мало")
        return
    a = np.array(v)
    print(f"  {name:<44} n={len(a):<6} мед={np.median(a):+6.3f}R  "
          f"p25={np.percentile(a,25):+6.3f}  p75={np.percentile(a,75):+6.3f}  "
          f"доля≥1R={100*(a>=1).mean():5.1f}%  доля≤0={100*(a<=0).mean():5.1f}%")


print(f"монет обработано: {len(base_all)} · окно MFE_free = {N_FWD} баров (4ч) · сетап bigflush15\n")
print("═══ ДИАГНОЗ: даёт ли рынок ход после сетапа (MFE_free, без стопа и TTL) ═══")
print("   A = WT падает (так входит БОЙ) · B = WT растёт (так требует БЭКТЕСТ)\n")
rep("A. вход В ПАДЕНИЕ (бой)", A)
rep("B. вход НА РАЗВОРОТЕ (бэктест)", B)
if len(A) > 50 and len(B) > 50:
    dm = float(np.median(B)) - float(np.median(A))
    print(f"\n   Δмедиана (разворот − падение) = {dm:+.3f}R  "
          f"{'🔴 ТРИГГЕР ВИНОВАТ (разворот сильно лучше)' if dm > 0.10 else ('≈ триггер НЕ решает' if abs(dm) <= 0.10 else 'падение лучше?!')}")
print()
print("═══ ПОТОЛОК: лучший возможный вход в окне ±4 бара ═══")
print("   Если потолок низкий — механика мертва, а не сломана.\n")
rep("идеальный вход (потолок)", ideal)
if ideal:
    print(f"\n   Цель TP1R требует хода ≥1R. Потолок даёт ≥1R в "
          f"{100*(np.array(ideal) >= 1).mean():.1f}% случаев.")
    print(f"   Косты {COST}% при стопе 4-12% — это 0.03-0.09R, порогом не являются.")
