#!/usr/bin/env python3
"""
elliott_n_down_backtest.py
==========================
Бэктест elliott_n_down / n_up на исторических данных.

Для каждой закрытой сделки (n=3587, post-14.05.2026) вычисляет n_down и n_up
из 4h/1h OHLCV на момент входа (no look-ahead), затем группирует по n_down
и показывает avgR / WR / count.

Алгоритм:
  1. Читаем сделки из simulated_trades (status IN TP/SL/TSL/EXPIRED)
  2. Для каждого symbol — 1 API вызов 4h + 1 API вызов 1h (не N×API)
  3. Для каждой сделки: срез df до entry_time → swing_highs → n_down
  4. Таблица: n_down × (ALL / signal_type / direction)

Запуск:
  python scripts/elliott_n_down_backtest.py
  python scripts/elliott_n_down_backtest.py --since 2026-05-14 --min-n 5
"""
from __future__ import annotations

import os, sys, asyncio, sqlite3, argparse, logging
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from core.infra.data_collector import RealTimeData
from core.indicators.indicators import (
    find_swing_highs, find_swing_lows,
    calculate_n_down, calculate_n_up,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH   = "subscriptions.db"
SINCE_DEF = "2026-05-14"
SWING_P   = 5      # period для 4h swing highs/lows
SWING_P1H = 5      # period для 1h
MIN_BARS  = SWING_P * 2 + 5  # минимум баров для расчёта


# ─────────────────────────────────────────────────────────────────────────────
# Загрузка OHLCV для пары за нужный период
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_ohlcv(exchange, symbol: str, tf: str, since_ms: int, limit: int = 500) -> pd.DataFrame | None:
    """Загружает OHLCV начиная с since_ms (пагинация до limit свечей)."""
    all_rows = []
    since = since_ms
    for _ in range(10):
        try:
            rows = await exchange.fetch_ohlcv(symbol, tf, since=since, limit=500)
        except Exception as e:
            logger.debug("fetch_ohlcv %s %s: %s", symbol, tf, e)
            break
        if not rows:
            break
        all_rows.extend(rows)
        if len(all_rows) >= limit or len(rows) < 100:
            break
        since = rows[-1][0] + 1
        await asyncio.sleep(0.15)

    if not all_rows:
        return None
    df = pd.DataFrame(all_rows, columns=["time", "open", "high", "low", "close", "volume"])
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Вычисление n_down/n_up на срезе df до entry_time
# ─────────────────────────────────────────────────────────────────────────────

def calc_n_at_entry(df: pd.DataFrame, entry_ts_ms: int, period: int) -> tuple[int, int]:
    """Возвращает (n_down, n_up) из баров строго ДО entry_ts_ms (no look-ahead)."""
    mask = df["time"] < entry_ts_ms
    sub = df[mask]
    if len(sub) < MIN_BARS:
        return 0, 0
    sh = find_swing_highs(sub["high"], period=period)
    sl = find_swing_lows(sub["low"], period=period)
    return calculate_n_down(sh), calculate_n_up(sl)


# ─────────────────────────────────────────────────────────────────────────────
# Статистика
# ─────────────────────────────────────────────────────────────────────────────

def stats_table(rows: list[dict], group_keys: list[str], title: str) -> None:
    """Печатает таблицу avgR/WR/n по группировке group_keys."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    grp = df.groupby(group_keys)["R_multiple"].agg(
        n="count",
        avgR="mean",
        medR="median",
        WR=lambda x: (x > 0).mean() * 100,
    ).reset_index().sort_values(group_keys)

    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")
    cols = group_keys + ["n", "avgR", "medR", "WR"]
    header = " | ".join(f"{c:>12}" for c in cols)
    print(header)
    print("-" * len(header))
    for _, row in grp.iterrows():
        vals = [f"{row[c]:>12}" if isinstance(row[c], str) else
                f"{row[c]:>12.0f}" if c == "n" else
                f"{row[c]:>12.3f}" if c in ("avgR", "medR") else
                f"{row[c]:>11.1f}%" for c in cols]
        print(" | ".join(vals))


# ─────────────────────────────────────────────────────────────────────────────
# Главный цикл
# ─────────────────────────────────────────────────────────────────────────────

async def main(since: str, min_n: int, db_path: str) -> None:
    since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ms_global = int(since_dt.timestamp() * 1000)
    # Грузим 60 дней 4h ДО since, чтобы swing на начальных сделках тоже считался
    fetch_since_ms = since_ms_global - 60 * 24 * 3600 * 1000

    # Читаем все закрытые сделки
    conn = sqlite3.connect(db_path)
    rows_db = conn.execute("""
        SELECT symbol, signal_type, direction, R_multiple, created_at
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
          AND created_at >= ?
        ORDER BY created_at
    """, (since,)).fetchall()
    conn.close()

    print(f"Сделок для анализа: {len(rows_db)} (since {since})")

    # Группируем сделки по символу
    by_sym: dict[str, list] = defaultdict(list)
    for sym, sig, direc, r_mult, created_at in rows_db:
        # created_at — строка "YYYY-MM-DD HH:MM:SS"
        raw = created_at[:19].replace("T", " ")
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        entry_ms = int(dt.timestamp() * 1000)
        by_sym[sym].append({
            "signal_type": sig or "unknown",
            "direction": direc,
            "R_multiple": float(r_mult),
            "entry_ms": entry_ms,
        })

    print(f"Уникальных пар: {len(by_sym)}")

    # Загружаем exchange
    dc = RealTimeData("bingx", api_semaphore_size=3, api_rps=3.0)
    await dc.load_markets()
    exchange = dc.exchange

    all_results: list[dict] = []
    skipped = 0

    for idx, (sym, trades) in enumerate(by_sym.items()):
        print(f"  [{idx+1:3d}/{len(by_sym)}] {sym} ({len(trades)} сделок) ...", end=" ", flush=True)

        # Загружаем 4h и 1h один раз для всей пары
        df_4h = await fetch_ohlcv(exchange, sym, "4h", fetch_since_ms, limit=1000)
        await asyncio.sleep(0.2)
        df_1h = await fetch_ohlcv(exchange, sym, "1h", fetch_since_ms, limit=2000)
        await asyncio.sleep(0.2)

        if df_4h is None or len(df_4h) < MIN_BARS:
            print(f"[4h:skip]")
            skipped += len(trades)
            continue

        ok = 0
        for trade in trades:
            entry_ms = trade["entry_ms"]

            # n_down/n_up на 4h
            nd_4h, nu_4h = calc_n_at_entry(df_4h, entry_ms, SWING_P)

            # n_down/n_up на 1h (если загружен)
            nd_1h, nu_1h = (0, 0)
            if df_1h is not None and len(df_1h) >= MIN_BARS:
                nd_1h, nu_1h = calc_n_at_entry(df_1h, entry_ms, SWING_P1H)

            all_results.append({
                "symbol":       sym,
                "signal_type":  trade["signal_type"],
                "direction":    trade["direction"],
                "R_multiple":   trade["R_multiple"],
                "n_down_4h":    nd_4h,
                "n_up_4h":      nu_4h,
                "n_down_1h":    nd_1h,
                "n_up_1h":      nu_1h,
            })
            ok += 1

        print(f"OK={ok}")

    print(f"\nОбработано: {len(all_results)} сделок, пропущено: {skipped}\n")

    if not all_results:
        print("Нет данных для анализа.")
        return

    # ─── ТАБЛИЦЫ РЕЗУЛЬТАТОВ ───────────────────────────────────────────────

    # 1. n_down_4h × ВСЕ сделки
    stats_table(all_results, ["n_down_4h"], "n_down 4h — все сделки")

    # 2. n_down_4h × direction
    stats_table(all_results, ["n_down_4h", "direction"], "n_down 4h × direction")

    # 3. n_down_4h × direction только SHORT (главный вопрос)
    short_rows = [r for r in all_results if r["direction"] == "SHORT"]
    if short_rows:
        stats_table(short_rows, ["n_down_4h"], "n_down 4h → SHORT only (подтверждение теории)")

    # 4. n_up_4h × LONG
    long_rows = [r for r in all_results if r["direction"] == "LONG"]
    if long_rows:
        stats_table(long_rows, ["n_up_4h"], "n_up 4h → LONG only (зеркало)")

    # 5. n_down_4h × signal_type для SHORT
    if short_rows:
        stats_table(short_rows, ["signal_type", "n_down_4h"],
                    "n_down 4h × signal_type (SHORT) — фильтруй n=<min_n")

    # 6. n_down_1h × direction (MTF подтверждение)
    stats_table(all_results, ["n_down_1h", "direction"], "n_down 1h (MTF) × direction")

    # 7. Комбо HTF+MTF для SHORT
    if short_rows:
        combo_rows = []
        for r in short_rows:
            combo_rows.append({
                **r,
                "nd_combo": f"4h={r['n_down_4h']} 1h={r['n_down_1h']}",
            })
        # Топ-10 комбо по avgR
        df_combo = pd.DataFrame(combo_rows).groupby("nd_combo")["R_multiple"].agg(
            n="count", avgR="mean", WR=lambda x: (x > 0).mean() * 100
        ).reset_index()
        df_combo = df_combo[df_combo["n"] >= min_n].sort_values("avgR", ascending=False)
        print(f"\n{'─'*60}")
        print(f"  TOP комбо (4h × 1h n_down) для SHORT (n≥{min_n})")
        print(f"{'─'*60}")
        print(df_combo.head(20).to_string(index=False))

    # 8. Сводка: насколько n_down=4+ опасен
    print(f"\n{'═'*60}")
    print("  СВОДКА: SHORT при n_down_4h")
    print(f"{'═'*60}")
    df_all = pd.DataFrame(all_results)
    for nd in sorted(df_all["n_down_4h"].unique()):
        sub_s = df_all[(df_all["n_down_4h"] == nd) & (df_all["direction"] == "SHORT")]
        sub_l = df_all[(df_all["n_down_4h"] == nd) & (df_all["direction"] == "LONG")]
        if len(sub_s) >= 1:
            danger = "🔴 СТОП" if nd >= 4 else ("✅ ОК" if 2 <= nd <= 3 else "⚪")
            print(f"  n_down={nd}: SHORT n={len(sub_s):4d} avgR={sub_s['R_multiple'].mean():+.3f} "
                  f"WR={100*(sub_s['R_multiple']>0).mean():.1f}% {danger}")
        if len(sub_l) >= 1:
            print(f"  n_down={nd}: LONG  n={len(sub_l):4d} avgR={sub_l['R_multiple'].mean():+.3f} "
                  f"WR={100*(sub_l['R_multiple']>0).mean():.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elliott n_down/n_up бэктест")
    parser.add_argument("--since",  default=SINCE_DEF, help="С какой даты (YYYY-MM-DD)")
    parser.add_argument("--min-n",  type=int, default=5, help="Мин. сделок для показа комбо")
    parser.add_argument("--db",     default=DB_PATH, help="Путь к БД")
    args = parser.parse_args()

    asyncio.run(main(args.since, args.min_n, args.db))
