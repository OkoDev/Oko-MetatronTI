# -*- coding: utf-8 -*-
"""Бэктест МЕТОДА ЕГОРА V2 (docs/OTE_METHOD_ENTRY_V2.md) на ohlcv_cache (Binance 2022-26, 1h).

Меряем МЕТОД (правильные входы), НЕ сделки бота. Интрабар-исполнение, % net (LAW №1).

Исполнение сетапа (с бара trigger+1):
  1. Ретест: LONG — low ≤ entry (лимитка на сломанном уровне). До ретеста цена взяла t1 → missed.
  2. Лестница 40/30/30 по целям, SL→BE (entry) после t1. Гонка в баре: SL первым (консервативно).
  3. Timeout 400 баров: выход остатка по close. net% = Σ(доля×ход%) − 0.2.

Запуск: python scripts/test_method_v2.py [--tf 1h] [--symbols N] [--year-split]
"""
import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

from core.smc.method_v2 import detect_method_v2

CACHE = "ohlcv_cache.db"
COSTS = 0.2
SHARES = (0.4, 0.3, 0.3)
RETEST_BARS = 24
TIMEOUT_BARS = 400


def load_symbols(tf: str) -> list[str]:
    with sqlite3.connect(CACHE) as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?", (tf,))]


def load_df(sym: str, tf: str) -> pd.DataFrame:
    with sqlite3.connect(CACHE) as c:
        df = pd.read_sql_query(
            "SELECT time, open, high, low, close, volume FROM ohlcv_cache "
            "WHERE symbol=? AND timeframe=? ORDER BY time", c, params=(sym, tf))
    df.index = pd.to_datetime(df["time"], unit="ms")
    return df.drop(columns=["time"])


def simulate(df: pd.DataFrame, s) -> dict | None:
    """Интрабар-исполнение одного сетапа. None = не зафиллен (missed/no-retest)."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    lng = s.direction == "LONG"
    t1, t2, t3 = s.targets
    # 1. ретест
    fill_i = None
    for j in range(s.trigger_idx + 1, min(s.trigger_idx + 1 + RETEST_BARS, n)):
        took_t1 = (high[j] >= t1) if lng else (low[j] <= t1)
        touched = (low[j] <= s.entry) if lng else (high[j] >= s.entry)
        if touched:
            fill_i = j
            break
        if took_t1:
            return None                                    # ушла к цели без нас
    if fill_i is None:
        return None
    # 2. исполнение лестницы
    sl = s.sl
    entry = s.entry
    rem = 1.0
    pnl = 0.0                                             # Σ доля × ход%
    hit = [False, False, False]
    tgts = [t1, t2, t3]
    for j in range(fill_i, min(fill_i + TIMEOUT_BARS, n)):
        sl_hit = (low[j] <= sl) if lng else (high[j] >= sl)
        if sl_hit:
            move = (sl - entry) / entry * 100 if lng else (entry - sl) / entry * 100
            pnl += rem * move
            rem = 0.0
            break
        for k in range(3):
            if hit[k] or rem <= 0:
                continue
            t_hit = (high[j] >= tgts[k]) if lng else (low[j] <= tgts[k])
            if t_hit:
                move = (tgts[k] - entry) / entry * 100 if lng else (entry - tgts[k]) / entry * 100
                pnl += SHARES[k] * move
                rem -= SHARES[k]
                hit[k] = True
                if k == 0:
                    sl = entry                            # БУ после t1
        if rem <= 1e-9:
            break
    if rem > 1e-9:                                        # timeout: остаток по close
        j_last = min(fill_i + TIMEOUT_BARS, n) - 1
        move = (close[j_last] - entry) / entry * 100 if lng else (entry - close[j_last]) / entry * 100
        pnl += rem * move
    return {"net": pnl - COSTS, "kind": s.kind, "dir": s.direction,
            "year": str(df.index[s.trigger_idx])[:4], "t1": hit[0], "t2": hit[1], "t3": hit[2],
            "conf": bool(getattr(s, "conf", False))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--symbols", type=int, default=0, help="лимит символов (0=все)")
    ap.add_argument("--liquid", type=int, default=0, help="top-N по среднему $-объёму (0=все)")
    ap.add_argument("--lenbig", type=int, default=50, help="len_big структуры (100≈4h на 1h)")
    ap.add_argument("--conf-only", action="store_true", help="только conf=ДА сетапы")
    args = ap.parse_args()

    syms = load_symbols(args.tf)
    if args.liquid:
        # ранжируем по медианному $-обороту бара (close×volume), берём top-N
        vol_rank = []
        for sym in syms:
            try:
                df = load_df(sym, args.tf)
                if len(df) < 300:
                    continue
                dv = (df["close"] * df["volume"]).median()
                vol_rank.append((dv, sym))
            except Exception:
                continue
        vol_rank.sort(reverse=True)
        syms = [s for _, s in vol_rank[:args.liquid]]
        print(f"ликвидные top-{args.liquid}: {', '.join(syms[:15])}...")
    elif args.symbols:
        syms = syms[:args.symbols]
    print(f"символов: {len(syms)} · tf={args.tf}")

    res = []
    for si, sym in enumerate(syms):
        try:
            df = load_df(sym, args.tf)
            if len(df) < 300:
                continue
            for s in detect_method_v2(df, len_big=args.lenbig):
                if args.conf_only and not getattr(s, "conf", False):
                    continue
                r = simulate(df, s)
                if r:
                    r["sym"] = sym
                    res.append(r)
        except Exception as e:
            print(f"  {sym}: {e}")
        if (si + 1) % 50 == 0:
            print(f"  ...{si + 1}/{len(syms)}, сделок {len(res)}", flush=True)

    if not res:
        print("сделок нет"); return

    def stat(lst):
        if not lst:
            return "n=0"
        nets = [x["net"] for x in lst]
        wr = sum(1 for v in nets if v > 0) / len(nets) * 100
        return (f"n={len(nets):5d} net={sum(nets)/len(nets):+.3f}%/сд WR={wr:.0f}% "
                f"t1={sum(1 for x in lst if x['t1'])/len(lst)*100:.0f}% "
                f"t3={sum(1 for x in lst if x['t3'])/len(lst)*100:.0f}%")

    print(f"\n═══ ИТОГО (fill'ов {len(res)}) ═══")
    print("  ALL:", stat(res))
    for d in ("LONG", "SHORT"):
        print(f"  {d}:", stat([x for x in res if x["dir"] == d]))
    print("\n  по типу:")
    for kd in ("reversal", "series", "continuation"):
        print(f"  {kd:12s}:", stat([x for x in res if x["kind"] == kd]))
    print("\n  по годам (устойчивость):")
    for y in sorted(set(x["year"] for x in res)):
        print(f"  {y}:", stat([x for x in res if x["year"] == y]))
    print("\n  тип × направление:")
    for kd in ("reversal", "series", "continuation"):
        for d in ("LONG", "SHORT"):
            sub = [x for x in res if x["kind"] == kd and x["dir"] == d]
            if sub:
                print(f"  {kd:12s} {d}:", stat(sub))

    print("\n  ФЛАГМАН reversal SHORT по годам (устойчивость эджа):")
    rs = [x for x in res if x["kind"] == "reversal" and x["dir"] == "SHORT"]
    for y in sorted(set(x["year"] for x in rs)):
        print(f"  {y}:", stat([x for x in rs if x["year"] == y]))

    print("\n  ═══ КОНФЛЮЭНЦИЯ СЕТОК (урок Егора: вход только в пересечении) ═══")
    for kd in ("reversal", "series", "continuation"):
        for d in ("LONG", "SHORT"):
            for cf in (True, False):
                sub = [x for x in res if x["kind"] == kd and x["dir"] == d and x["conf"] == cf]
                if len(sub) >= 30:
                    print(f"  {kd:12s} {d:5s} conf={'ДА ' if cf else 'нет'}:", stat(sub))
    print("\n  conf=ДА reversal SHORT по годам:")
    rsc = [x for x in rs if x["conf"]]
    for y in sorted(set(x["year"] for x in rsc)):
        print(f"  {y}:", stat([x for x in rsc if x["year"] == y]))


if __name__ == "__main__":
    main()
