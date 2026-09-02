# -*- coding: utf-8 -*-
"""
136.E · BOS-ГЕЙТ НА ЯДРЕ — пересборка сигналов вместо пропавшего дампа (01.09.2026).

Повод: `bos_gate_revision.py` читает готовый `scripts/_fade_signals_15m_enriched.csv`
(60 монет, 2024-02→2026-07, 2023 отсутствует), а скрипт, создававший корневой дамп,
в проекте ОТСУТСТВУЕТ. Поэтому сигналы собираются здесь заново — на балансированной
панели и с 2023.

Собрано из двух проверенных мест, без переизобретения:
  · механика bigflush15 — `scripts/golden_bigflush.py`:
    ATRTrend↑ + WT<-60 + WT растёт + стоп >4% (3-барный минимум ×0.997), TP=1R, TTL 24;
  · BOS-гейт — `scripts/bos_gate_revision.py`: медвежий BOS в окне [i-lookback, i],
    две шкалы (internal=len5 и swing=len50), событие по индексу ПОДТВЕРЖДЕНИЯ.

Проверяемое утверждение ([[bos_gate_bigflush_structural]]): на 15m гейт len5 помогает
(PF 1.27→1.49), len50 ВРЕДИТ (0.48). Мерилось на 100 ликвидных монетах 2024-26.

Запуск:  python scripts/bos_gate_core.py [--since 2023] [--lookback 10] [--no-core]
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

from core.smc.oko_sm_engine import run_structure  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.15          # как в golden_bigflush (15m, лимитный вход в пролив)
TTL = 24
MIN_STOP_PCT = 4.0   # боевой bigflush_min_stop_pct


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    tu, td, tr_ = up.copy(), dn.copy(), np.ones(len(hl2))
    for i in range(1, len(hl2)):
        tu[i] = max(up[i], tu[i - 1]) if hl2[i - 1] > tu[i - 1] else up[i]
        td[i] = min(dn[i], td[i - 1]) if hl2[i - 1] < td[i - 1] else dn[i]
        tr_[i] = 1 if hl2[i] > td[i - 1] else (-1 if hl2[i] < tu[i - 1] else tr_[i - 1])
    return tr_


def sim(i, H, L, C, sl, tp, ttl=TTL):
    e = C[i]
    end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl:
            return (sl - e) / e * 100 - COST
        if H[j] >= tp:
            return (tp - e) / e * 100 - COST
    return (C[end] - e) / e * 100 - COST


def stat(rows):
    """rows: список dict с ключом net."""
    if len(rows) < 30:
        return None
    v = np.array([r["net"] for r in rows])
    w, gl = v[v > 0], -v[v <= 0].sum()
    srt = np.sort(v)[::-1]
    coins = defaultdict(float)
    for r in rows:
        coins[r["sym"]] += r["net"]
    return dict(n=len(v), wr=100 * (v > 0).mean(), pf=(w.sum() / gl if gl else 99.0),
                med=float(np.median(v)), avg=float(v.mean()),
                bt=float(srt[int(len(srt) * 0.1):].sum()),
                coins=len(coins), cpos=sum(1 for x in coins.values() if x > 0))


def line(nm, rows, base=None):
    s = stat(rows)
    if not s:
        print(f"  {nm:<30} n={len(rows)} — мало")
        return
    lift = f" ×{s['pf'] / base['pf']:.2f}" if base and base["pf"] else ""
    print(f"  {nm:<30} n={s['n']:>6} WR {s['wr']:>4.1f}% PF {s['pf']:>5.2f}{lift:>7} "
          f"мед {s['med']:>+6.2f}% безтоп10% {s['bt']:>+8.0f} монет+ {s['cpos']}/{s['coins']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--lookback", type=int, default=10)
    ap.add_argument("--no-core", action="store_true", help="старая вселенная (по длине истории)")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    if a.no_core:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        syms = [r[0] for r in con.execute(
            "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
            "GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 100", (t0,)).fetchall()]
        con.close()
        uni = f"{len(syms)} монет по длине истории (НЕ балансировано)"
    else:
        from scripts.research_harness import core_universe
        syms = core_universe("15m", since=f"{a.since}-01-01", until="2026-06-01")
        uni = f"ЯДРО {len(syms)} монет (балансированная панель)"

    print("=" * 118)
    print(f"BOS-ГЕЙТ на bigflush15 · {uni} · с {a.since} · lookback {a.lookback} баров")
    print(f"механика: ATRTrend↑ + WT<-60 растёт + стоп>{MIN_STOP_PCT}% · TP=1R · TTL {TTL} · косты {COST}%")
    print("=" * 118)

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = []
    for k, sym in enumerate(syms, 1):
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                        con, params=(sym, t0))
        if len(d) < 1000:
            continue
        d = d.reset_index(drop=True)
        # структура считается ОДИН раз на монету — событие по индексу подтверждения
        try:
            st = run_structure(d[["open", "high", "low", "close"]])
        except Exception:
            continue
        ev5 = np.array(sorted(e.i for e in st.events
                              if e.kind == "BOS" and not e.bull and e.internal))
        ev50 = np.array(sorted(e.i for e in st.events
                               if e.kind == "BOS" and not e.bull and not e.internal))
        w, at = wt(d), atrt(d)
        H, L, C = d.high.values, d.low.values, d.close.values
        yr = pd.to_datetime(d.time, unit="ms").dt.year.values
        ts = d.time.values
        for i in range(60, len(d) - 1):
            if not (at[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
                continue
            e_, sl = C[i], L[max(0, i - 3):i + 1].min() * 0.997
            if not (sl < e_ and (e_ - sl) / e_ * 100 > MIN_STOP_PCT):
                continue
            net = sim(i, H, L, C, sl, e_ + (e_ - sl))
            rows.append(dict(
                sym=sym, year=int(yr[i]), ts=int(ts[i]), net=net,
                stop=(e_ - sl) / e_ * 100,
                bos5=int(((ev5 >= i - a.lookback) & (ev5 <= i)).sum()) if len(ev5) else 0,
                bos50=int(((ev50 >= i - a.lookback) & (ev50 <= i)).sum()) if len(ev50) else 0))
        if k % 20 == 0:
            print(f"  … {k}/{len(syms)} монет · сигналов {len(rows)}", flush=True)
    con.close()

    if not rows:
        print("🔴 НОЛЬ сигналов — молчаливый пустой замер, проверьте пороги")
        return 1
    base = stat(rows)
    print(f"\nсобрано сигналов: {len(rows)}\n")
    print("=" * 118)
    print("ГЕЙТ: помогает ли требование медвежьего BOS перед проливом")
    print("=" * 118)
    line("БАЗА без гейта", rows)
    line("len5 (internal) ≥1 BOS", [r for r in rows if r["bos5"] >= 1], base)
    line("len5 ≥2 BOS", [r for r in rows if r["bos5"] >= 2], base)
    line("len5 НЕТ BOS", [r for r in rows if r["bos5"] == 0], base)
    line("len50 (swing) ≥1 BOS", [r for r in rows if r["bos50"] >= 1], base)
    line("len50 НЕТ BOS", [r for r in rows if r["bos50"] == 0], base)

    g = [r for r in rows if r["bos5"] >= 1]
    print("\nПО ГОДАМ (боевой гейт len5 ≥1):")
    for y in sorted({r["year"] for r in rows}):
        yb = [r for r in rows if r["year"] == y]
        yg = [r for r in g if r["year"] == y]
        line(f"  {y}", yg, stat(yb))

    print("\nКЛАСТЕР (≥2 монеты в один день) внутри гейта:")
    day = defaultdict(set)
    for r in rows:
        day[pd.Timestamp(r["ts"], unit="ms").date()].add(r["sym"])
    line("  одиночка", [r for r in g if len(day[pd.Timestamp(r['ts'], unit='ms').date()]) < 2])
    line("  кластер ≥2", [r for r in g if len(day[pd.Timestamp(r['ts'], unit='ms').date()]) >= 2])

    print("\nРАЗМЕР СТОПА внутри гейта:")
    for lo, hi in ((4, 6), (6, 10), (10, 20), (20, 100)):
        line(f"  стоп {lo}-{hi}%", [r for r in g if lo <= r["stop"] < hi])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
