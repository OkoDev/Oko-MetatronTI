# -*- coding: utf-8 -*-
"""ПОЧЕМУ У ПАТТЕРНОВ КОМБИНАТОРА WR 97% (13.08.2026, Даат) — третья версия.

Отброшено измерением:
  • механика simulate() — голая база даёт WR 41.5%, допущения стоят 4.4 п.п.;
  • look-ahead во флагах — 17 из 149 переписываются, но на 0.001–0.94% баров,
    дивергенции и WT/RSI/BOS/CHoCH чистые полностью.

Остаётся третья: КАЖДЫЙ БАР считается отдельным наблюдением при горизонте 12 баров.
Флаг `bear_fvg_1d` держится сутки = 24 бара подряд, и все 24 «наблюдения» —
это ОДНО движение. Если движение вниз, паттерн получает 24 победы подряд.
n=6712 при этом эффективно в разы меньше, а WR меряет не «как часто паттерн прав»,
а «сколько баров подряд длилось удачное движение».

Проверка на топ-паттерне комбинатора `bull_fvg_1h + bull_fvg_1d` (он же DS_L052,
заявлен WR 97.5% avgR 1.497; в бою n=1908 WR 29.6% −1.103%/сд):
  A. как считал комбинатор — все бары;
  B. с кулдауном в горизонт (12 баров) — непересекающиеся наблюдения;
  C. по ЭПИЗОДАМ — один вход на непрерывную серию баров с флагом;
  D. то же в % net с костами.

Запуск:  python scripts/combinator_overlap_inflation.py [--coins 30]
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

from core.calculators.combinator_core import compute_flags, aggregate_tf  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.35
TP_R = 2.0
FUTURE = 12


def simulate(df):
    n = len(df)
    high, low, close = df.high.values, df.low.values, df.close.values
    r = np.full(n, np.nan)
    sp = np.full(n, np.nan)
    for i in range(20, n - FUTURE - 1):
        price = close[i]
        sl = low[i - 10:i + 1].min() * 0.999
        sld = price - sl
        if sld > 0 and sld / price < 0.06:
            tp = price + sld * TP_R
            fh, fl = high[i + 1:i + 1 + FUTURE], low[i + 1:i + 1 + FUTURE]
            ht, hs = (fh >= tp), (fl <= sl)
            sp[i] = sld / price * 100
            if ht.any() and hs.any():
                r[i] = TP_R if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any():
                r[i] = TP_R
            elif hs.any():
                r[i] = -1.0
            else:
                r[i] = (close[i + FUTURE] - price) / sld
    return r, sp


def show(nm, r, sp, n_all):
    if len(r) == 0:
        print(f"{nm:<36} {'—':>8}")
        return
    net = r * sp - COST
    pf_v = net[net > 0].sum() / abs(net[net < 0].sum()) if (net < 0).any() else 99.0
    print(f"{nm:<36} {len(r):>8} {100 * len(r) / max(1, n_all):>7.1f}% "
          f"{100 * (r > 0).mean():>7.1f}% {r.mean():>+8.3f} "
          f"{net.mean():>+9.3f}% {pf_v:>7.2f}")


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

    print("═" * 96)
    print(f"РАЗДУВ ЧЕРЕЗ ПЕРЕКРЫТИЕ · паттерн `bull_fvg_1h + bull_fvg_1d` (DS_L052) · "
          f"{len(syms)} монет с {a.since}")
    print(f"заявлено комбинатором: WR 97.5% avgR 1.497 n=6712 · в бою: WR 29.6% −1.103%/сд n=1908")
    print("═" * 96)

    A_r, A_s, B_r, B_s, C_r, C_s = [], [], [], [], [], []
    base_n = 0
    for sym in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                        c, params=(sym, t0))
        c.close()
        if len(d) < 1500:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
        f1h = compute_flags(d, "1h", include_pivots=False)
        d1d = aggregate_tf(d, "1d")
        if len(d1d) < 40:
            continue
        f1d = compute_flags(d1d, "1d", include_pivots=False)
        # HTF только с ЗАКРЫТОГО бара — как в combinator_v2.process_symbol:
        # индекс дневного флага сдвигается на +1 день, иначе весь день знает свой итог
        f1d.index = f1d.index + pd.Timedelta(days=1)
        f1d_on_1h = f1d.reindex(d.index, method="ffill")
        if "bull_fvg_1h" not in f1h.columns or "bull_fvg_1d" not in f1d_on_1h.columns:
            continue
        mask = (f1h["bull_fvg_1h"].fillna(False).values.astype(bool) &
                f1d_on_1h["bull_fvg_1d"].fillna(False).values.astype(bool))
        r, sp = simulate(d)
        ok = ~np.isnan(r)
        base_n += int(ok.sum())
        m = mask & ok
        idx = np.flatnonzero(m)
        if len(idx) == 0:
            continue
        # A — все бары (как комбинатор)
        A_r.append(r[idx]); A_s.append(sp[idx])
        # B — кулдаун в горизонт
        keep, last = [], -10 ** 9
        for i in idx:
            if i - last >= FUTURE:
                keep.append(i); last = i
        B_r.append(r[keep]); B_s.append(sp[keep])
        # C — один вход на эпизод (первый бар непрерывной серии)
        first = [i for k, i in enumerate(idx) if k == 0 or i - idx[k - 1] > 1]
        C_r.append(r[first]); C_s.append(sp[first])

    A_r, A_s = np.concatenate(A_r), np.concatenate(A_s)
    B_r, B_s = np.concatenate(B_r), np.concatenate(B_s)
    C_r, C_s = np.concatenate(C_r), np.concatenate(C_s)

    print(f"\n{'способ счёта':<36} {'n':>8} {'доля':>8} {'WR':>8} {'avgR':>8} "
          f"{'%/сд net':>10} {'PF':>7}")
    print("─" * 96)
    show("A. каждый бар (как комбинатор)", A_r, A_s, base_n)
    show(f"B. кулдаун {FUTURE} баров (горизонт)", B_r, B_s, base_n)
    show("C. один вход на эпизод", C_r, C_s, base_n)
    print("─" * 96)
    print(f"{'база (все бары, без паттерна)':<36} {base_n:>8}")

    print(f"\n=== ЧТО ПОКАЗАЛ ЗАМЕР ===")
    print(f"перекрытие: на одно НЕЗАВИСИМОЕ наблюдение приходится "
          f"{len(A_r) / max(1, len(B_r)):.1f} «сделок» комбинатора")
    print(f"эффективное n паттерна: {len(C_r)} эпизодов вместо {len(A_r)} баров "
          f"(комбинатор считал значимость по большему в {len(A_r) / max(1, len(C_r)):.1f}×)")
    print(f"WR при честном счёте: {100 * (C_r > 0).mean():.1f}% против заявленных 97.5%")
    netC = C_r * C_s - COST
    print(f"деньги при честном счёте: {netC.mean():+.3f}%/сделку "
          f"(в бою {-1.103:+.3f}%/сд — {'сходится' if netC.mean() < 0 else 'РАСХОДИТСЯ'})")
    print("═" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
