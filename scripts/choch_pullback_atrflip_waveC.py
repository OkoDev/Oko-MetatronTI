# -*- coding: utf-8 -*-
"""CHoCH → КОРРЕКЦИЯ → ФЛИП ATRTrend → ВОЛНА C (15.08.2026, Даат).

Егор: «ранние входы по флипу ATRTrend после CHoCH и коррекции. Даже если это отскок ABC —
забирать C?»

Зачем именно так. Замер 14.08 показал: CHoCH → коррекция → вход лимитом даёт
WR 51.7–52.5% при цели 1R (монетку обыгрываем), но PF 0.96 — не хватает ~1.3 п.п. WR
до безубытка. Нужен ВЫБОРОЧНЫЙ фильтр, режущий худшие 10–15% сделок, а не половину
(USDT.D дал всего +1.1 п.п. и не годится).

Флип ATRTrend в зоне коррекции — кандидат на эту роль: он отсекает случаи, где откат
перерастает в новый тренд против нас, и оставляет те, где импульс возобновился.
Детекторы причинные: bull/bear_choch и ATRTrend в аудите лага 13.08 — лаг 0.

Разметка ABC:
    A = импульс слома (от экстремума до бара CHoCH)
    B = коррекция (откат на pb от A) — здесь лимитный вход
    C = целевая волна: entry + |A| × k, k ∈ {0.618, 1.0, 1.618}
Стоп — за экстремум B (инвалидация отката).

Сравнивается ЧЕТЫРЕ конструкции на одних сигналах:
  1. вход сразу в коррекции (как 14.08)          — контроль
  2. вход по ФЛИПУ ATRTrend в зоне коррекции     — механика Егора
  3. цель в R (1R/2R)                            — контроль
  4. цель по волне C (0.618/1.0/1.618 от A)      — механика Егора

Косты: LIMIT 0.35% (вход в коррекцию лимитом налога не платит).

Запуск:  python scripts/choch_pullback_atrflip_waveC.py [--coins 120] [--tf 1h]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BAR_H = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}
COST_LIMIT = 0.35
COST_MARKET = 0.79
PB = 0.236                      # глубина коррекции (лучшая по замеру 14.08)
# Егор 15.08: «проверь все возможные цели по фибо начиная от 1»
WAVE_K = [1.0, 1.272, 1.414, 1.618, 2.0, 2.618, 3.618, 4.236]
R_TARGETS = [2.0]


def atr_dir(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    n, cv = len(c), c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def resolve(H, L, C, j, side, entry, sl, tp, ttl):
    """Исход сделки от бара j. SL проверяется первым на баре."""
    end = min(j + ttl, len(C) - 1)
    fl, fh = L[j + 1:end + 1], H[j + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        hs, ht = fl <= sl, fh >= tp
        lo, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
        tail = (C[end] - entry) / entry * 100
    else:
        hs, ht = fh >= sl, fl <= tp
        lo, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
        tail = (entry - C[end]) / entry * 100
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    return lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)


def stat(rows, days, cost):
    if not rows or len(rows) < 40:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net = pr - cost
    neg = abs(net[net < 0].sum())
    r = net / sp
    return dict(n=len(rows), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
                pct=float(net.mean()), stop=float(np.median(sp)),
                freq=len(rows) / max(days, 1), r=float(r.mean()),
                r_day=float(r.mean()) * len(rows) / max(days, 1))


def show(nm, s, base=None):
    if not s:
        print(f"    {nm:<38} — мало данных")
        return
    dwr = f"{s['wr'] - base['wr']:+5.1f}" if base else "     "
    mark = "🟢" if (s["wr"] > 50 and s["pct"] > 0) else ("✅" if s["wr"] > 50 else
                                                        ("💰" if s["pct"] > 0 else "  "))
    print(f"  {mark}{nm:<38} n={s['n']:>5} WR {s['wr']:>5.1f}%({dwr}) PF {s['pf']:>5.2f} "
          f"стоп {s['stop']:>5.2f}% {s['pct']:>+7.2f}%/сд {s['freq']:>5.2f}сд/дн "
          f"{s['r_day']:>+7.3f}R/дн")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=120)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--tf", type=str, default="1h", help="15m,1h,4h,1d или all")
    ap.add_argument("--wait-pb", type=int, default=12, help="ждать коррекцию, баров")
    ap.add_argument("--wait-flip", type=int, default=12, help="ждать флип ATR после коррекции")
    ap.add_argument("--ttl", type=int, default=48)
    a = ap.parse_args()
    # ~4 суток удержания и ~12ч ожидания коррекции в барах КАЖДОГО ТФ
    TTL_BY_TF = {"15m": 384, "1h": 96, "4h": 24, "1d": 4}
    WAIT_BY_TF = {"15m": 48, "1h": 12, "4h": 3, "1d": 2}
    if a.tf in TTL_BY_TF:
        a.ttl = TTL_BY_TF[a.tf]
        a.wait_pb = WAIT_BY_TF[a.tf]

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 124)
    print(f"CHoCH → КОРРЕКЦИЯ {PB} → ФЛИП ATRTrend → ВОЛНА C · {a.tf} · {len(syms)} монет "
          f"с {a.since}")
    print(f"ждём откат {a.wait_pb}б · флип {a.wait_flip}б · держим {a.ttl}б · косты LIMIT {COST_LIMIT}%")
    print("═" * 124)

    A = defaultdict(list)
    CNT = defaultdict(int)
    days = 1

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 8000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        m15 = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        d = m15 if a.tf == "15m" else m15.resample(RULE[a.tf]).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna()
        if len(d) < 300:
            continue
        days = max(days, (d.index.max() - d.index.min()).days)
        try:
            F = compute_flags(d, a.tf, include_pivots=False)
        except Exception:
            continue

        def arr(col):
            k = f"{col}_{a.tf}"
            if k not in F.columns:
                return np.zeros(len(d), dtype=bool)
            try:
                return np.asarray(F[k].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d), dtype=bool)

        bull_ch, bear_ch = arr("bull_choch"), arr("bear_choch")
        td = atr_dir(d)
        H, L, C = d.high.values, d.low.values, d.close.values
        n = len(d)

        for side, ch in (("long", bull_ch), ("short", bear_ch)):
            want = 1 if side == "long" else -1
            for i0 in np.flatnonzero(ch):
                i = int(i0)
                if i < 25 or i >= n - a.ttl - a.wait_pb - a.wait_flip - 2:
                    continue
                # ── волна A: импульс слома ──
                if side == "long":
                    a_lo = float(L[max(0, i - 20):i + 1].min()); a_hi = float(C[i])
                else:
                    a_hi = float(H[max(0, i - 20):i + 1].max()); a_lo = float(C[i])
                if a_hi <= a_lo:
                    continue
                A_len = a_hi - a_lo
                CNT[(side, "CHoCH всего")] += 1

                # ── волна B: коррекция, лимитный вход ──
                entry = a_hi - A_len * PB if side == "long" else a_lo + A_len * PB
                jf = None
                for j in range(i + 1, min(i + 1 + a.wait_pb, n)):
                    if (side == "long" and L[j] <= entry) or (side == "short" and H[j] >= entry):
                        jf = j; break
                if jf is None:
                    continue
                CNT[(side, "коррекция пришла")] += 1

                # экстремум B (для стопа) — от бара CHoCH до заполнения
                if side == "long":
                    b_ext = float(L[i:jf + 1].min())
                    sl = min(b_ext, a_lo) * 0.999
                else:
                    b_ext = float(H[i:jf + 1].max())
                    sl = max(b_ext, a_hi) * 1.001
                sp = abs(entry - sl) / entry * 100
                if sp <= 0 or sp > 25:
                    continue
                risk = abs(entry - sl)

                # ── ФЛИП ATRTrend после коррекции (триггер Егора) ──
                j_flip = None
                for j in range(jf, min(jf + a.wait_flip, n - 1)):
                    if td[j] == want and td[j - 1] != want:
                        j_flip = j; break
                if j_flip is not None:
                    CNT[(side, "флип ATR пришёл")] += 1

                # ── конструкции ──
                for k in WAVE_K:
                    tp = entry + A_len * k if side == "long" else entry - A_len * k
                    pr = resolve(H, L, C, jf, side, entry, sl, tp, a.ttl)
                    if pr is not None:
                        A[(side, f"коррекция → волна C ×{k}")].append((pr, sp))
                    if j_flip is not None:
                        e2 = float(C[j_flip])
                        sl2 = sl
                        sp2 = abs(e2 - sl2) / e2 * 100
                        if 0 < sp2 <= 25:
                            tp2 = e2 + A_len * k if side == "long" else e2 - A_len * k
                            pr2 = resolve(H, L, C, j_flip, side, e2, sl2, tp2, a.ttl)
                            if pr2 is not None:
                                A[(side, f"+ФЛИП ATR → волна C ×{k}")].append((pr2, sp2))
                for tg in R_TARGETS:
                    tp = entry + tg * risk if side == "long" else entry - tg * risk
                    pr = resolve(H, L, C, jf, side, entry, sl, tp, a.ttl)
                    if pr is not None:
                        A[(side, f"коррекция → цель {tg:.0f}R")].append((pr, sp))
                    if j_flip is not None:
                        e2 = float(C[j_flip])
                        sp2 = abs(e2 - sl) / e2 * 100
                        if 0 < sp2 <= 25:
                            r2 = abs(e2 - sl)
                            tp2 = e2 + tg * r2 if side == "long" else e2 - tg * r2
                            pr2 = resolve(H, L, C, j_flip, side, e2, sl, tp2, a.ttl)
                            if pr2 is not None:
                                A[(side, f"+ФЛИП ATR → цель {tg:.0f}R")].append((pr2, sp2))
        if si % 30 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    print(f"\nокно {days} дней")
    for side in ("short", "long"):
        tot = CNT[(side, "CHoCH всего")]
        pb_ = CNT[(side, "коррекция пришла")]
        fl_ = CNT[(side, "флип ATR пришёл")]
        print(f"\n{'=' * 124}")
        print(f"=== {side.upper()} · CHoCH {tot} → коррекция {pb_} ({100 * pb_ / max(tot, 1):.0f}%) "
              f"→ флип ATR {fl_} ({100 * fl_ / max(pb_, 1):.0f}% от коррекций) ===")
        base = stat(A[(side, "коррекция → цель 1R")], days, COST_LIMIT)
        for k in WAVE_K:
            show(f"коррекция → волна C ×{k}", stat(A[(side, f"коррекция → волна C ×{k}")],
                                                  days, COST_LIMIT), base)
        for tg in R_TARGETS:
            show(f"коррекция → цель {tg:.0f}R", stat(A[(side, f"коррекция → цель {tg:.0f}R")],
                                                     days, COST_LIMIT), base)
        print("\n  (флип ATR опровергнут 15.08: WR −3..−8 п.п., стоп 5.44→6.99% — не печатаем)")

    print("\n" + "═" * 124)
    print("🟢 = WR>50% И плюс по деньгам · ✅ = WR>50% но минус · 💰 = плюс при WR<50%")
    print("Δ WR в скобках — к строке «коррекция → цель 1R» (контроль без флипа).")
    print("Флип ATR даёт более поздний вход (хуже цена), но отсекает продолжение отката.")
    print("═" * 124)
    return 0


if __name__ == "__main__":
    sys.exit(main())
