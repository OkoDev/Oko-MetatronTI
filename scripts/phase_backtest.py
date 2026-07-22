# -*- coding: utf-8 -*-
"""PHASE-BACKTEST — ретро-проверка инсайта Егора БЕЗ ожидания (22.07).

Вопрос: «сторона ПРОТИВ тренда рынка льёт» — правда на РЕАЛЬНЫХ исходах?
Вместо 3 недель форварда: берём ~46k закрытых сделок (VST+SIM), восстанавливаем
структурный тренд BTC 4h на момент КАЖДОГО входа (look-ahead-safe: только бары до входа,
скользящее окно 200 как в phase_watch) → veto стороны → бакетим net% ПО фазе vs ПРОТИВ.

net% = profit_pct − costs_pct (ЗАКОН №1). Reuse: structure_trend (ote_matrix), BTC 4h из
ohlcv_cache + докачка свежих баров с Binance. Запуск: python scripts/phase_backtest.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import sqlite3
import time
import urllib.request
from bisect import bisect_right
from datetime import datetime, timezone

import pandas as pd

from core.smc.ote_matrix import structure_trend

DB = "subscriptions.db"
CACHE = "ohlcv_cache.db"
WINDOW = 200   # скользящее окно баров для structure_trend (как live phase_watch)


def _load_btc_4h() -> pd.DataFrame:
    """BTC 4h из кэша + докачка свежих баров с Binance (кэш обрывается ~31.05)."""
    o = sqlite3.connect(CACHE)
    # ключ символа: пробуем известные варианты
    key = None
    for cand in ("BTC/USDT", "binance:BTC/USDT"):
        n = o.execute("SELECT COUNT(*) FROM ohlcv_cache WHERE symbol=? AND timeframe='4h'", (cand,)).fetchone()[0]
        if n > 1000:
            key = cand
            break
    rows = o.execute("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time", (key,)).fetchall()
    o.close()
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    # докачка с Binance от последнего бара до now
    last_ms = int(df["time"].iloc[-1])
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=4h&startTime={last_ms + 1}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "oko-bt"})
        arr = json.load(urllib.request.urlopen(req, timeout=15))
        fresh = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in arr]
        if fresh:
            df = pd.concat([df, pd.DataFrame(fresh, columns=["time", "open", "high", "low", "close"])], ignore_index=True)
            print(f"[BTC] докачано свежих 4h баров: {len(fresh)} (до {datetime.fromtimestamp(fresh[-1][0]/1000, timezone.utc).date()})")
    except Exception as e:
        print(f"[BTC] докачка не удалась ({e}) — работаю на кэше до {datetime.fromtimestamp(last_ms/1000, timezone.utc).date()}")
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def _btc_trend_timeline(df: pd.DataFrame):
    """→ (times[], trends[]) — structure_trend на скользящем окне на закрытии каждого бара."""
    times, trends = [], []
    for i in range(WINDOW, len(df)):
        w = df.iloc[i - WINDOW:i + 1].reset_index(drop=True)
        try:
            tr = structure_trend(w).get("trend")
        except Exception:
            tr = None
        times.append(int(df["time"].iloc[i]))
        trends.append(tr)
    return times, trends


def _to_ms(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except Exception:
        return 0


def _stat(rows):
    if not rows:
        return 0, None, None
    n = len(rows)
    wr = 100.0 * sum(1 for x in rows if x > 0) / n
    return n, wr, sum(rows) / n


def main():
    print("[1/3] Загружаю BTC 4h…")
    btc = _load_btc_4h()
    print(f"[2/3] Строю тренд-таймлайн BTC ({len(btc)} баров, окно {WINDOW})…")
    t0 = time.time()
    times, trends = _btc_trend_timeline(btc)
    print(f"      готово за {time.time()-t0:.0f}с, точек тренда: {len(times)}")

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT direction, profit_pct, costs_pct, created_at, execution_mode, signal_type "
        "FROM simulated_trades WHERE status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL "
        "AND created_at >= '2026-01-01'").fetchall()
    print(f"[3/3] Классифицирую {len(rows)} сделок по фазе BTC на входе…\n")

    # buckets[mode][fit] = [net,...] ; None-тренд пропускаем
    buckets = {"VST": {True: [], False: []}, "SIM": {True: [], False: []}}
    src = {}  # (signal_type, fit) → [net] (VST only)
    skipped = 0
    for r in rows:
        ms = _to_ms(r["created_at"])
        if not ms:
            skipped += 1; continue
        idx = bisect_right(times, ms) - 1   # последний бар ДО входа (look-ahead-safe)
        if idx < 0:
            skipped += 1; continue
        tr = trends[idx]
        if tr not in ("long", "short"):
            skipped += 1; continue
        veto = "SHORT" if tr == "long" else "LONG"     # тренд вверх → veto шорт
        d = (r["direction"] or "").upper()
        fit = d != veto
        net = float(r["profit_pct"]) - float(r["costs_pct"] or 0)
        mode = "VST" if r["execution_mode"] == "VST" else "SIM"
        buckets[mode][fit].append(net)
        if mode == "VST":
            src.setdefault((r["signal_type"], fit), []).append(net)

    print("═══ ИНСАЙТ ЕГОРА: сторона vs структурный тренд BTC 4h ═══")
    print("    (fit = сделка ПО тренду рынка; anti = ПРОТИВ)\n")
    for mode in ("VST", "SIM"):
        nf, wrf, netf = _stat(buckets[mode][True])
        na, wra, neta = _stat(buckets[mode][False])
        print(f"── {mode} ──")
        if nf: print(f"  ПО фазе    n={nf:5} WR{wrf:3.0f}% net={netf:+.3f}%")
        if na: print(f"  ПРОТИВ     n={na:5} WR{wra:3.0f}% net={neta:+.3f}%")
        if nf and na and netf is not None and neta is not None:
            d = netf - neta
            v = "✅ фаза РАЗДЕЛЯЕТ" if d > 0.10 else ("⚪ грань" if d > -0.10 else "❌ НЕ разделяет / обратно")
            print(f"  Δ(ПО−ПРОТИВ) = {d:+.3f}%/сделку  {v}")
        print()

    print("═══ VST по источникам (net% fit vs anti) ═══")
    srcs = sorted({s for s, _ in src})
    for s in srcs:
        nf, _, netf = _stat(src.get((s, True), []))
        na, _, neta = _stat(src.get((s, False), []))
        parts = []
        if nf: parts.append(f"ПО n={nf} {netf:+.2f}%")
        if na: parts.append(f"ПРОТИВ n={na} {neta:+.2f}%")
        if parts:
            print(f"  {str(s)[:22]:22} {' · '.join(parts)}")
    print(f"\n(пропущено {skipped}: нет тренда/до истории)")


if __name__ == "__main__":
    main()
