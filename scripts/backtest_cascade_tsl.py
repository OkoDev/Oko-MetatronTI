#!/usr/bin/env python3
"""
Бэктест: Каскадный TSL vs Same-TF TSL
======================================
Берёт ЗАКРЫТЫЕ сделки из БД и переигрывает их с разными TSL-стратегиями
на исторических OHLCV-данных, чтобы проверить гипотезу:
"Эскалация 15m→4h не улучшает результат vs чистый 15m TSL"

Запуск: python scripts/backtest_cascade_tsl.py
"""
import os, sys, asyncio, sqlite3, json, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from core.data_collector import RealTimeData
from core.indicators import calculate_trend, get_trend_info

logging.basicConfig(level=logging.WARNING)

# ── Параметры симуляции ──────────────────────────────────────────────────────
TSL_ACTIVATION_R = 1.0     # После какого R включается TSL
DEESC_THRESHOLDS = [2.5, 3.0, 5.0]  # Пороги де-эскалации для сравнения
SYMBOLS_LIMIT = 40         # Максимум пар для теста (ограничение API)
MIN_CANDLES = 50           # Минимум свечей для расчёта тренда
MAX_CANDLES = 200          # Свечей для загрузки

# ── Вспомогательные функции ──────────────────────────────────────────────────

def get_tsl_price(df_trend, direction: str) -> Optional[float]:
    """Возвращает текущую линию TSL из calculate_trend()."""
    try:
        info = get_trend_info(df_trend)
        if info and info.get("tsl") and info["tsl"] > 0:
            return float(info["tsl"])
        # fallback: напрямую из столбцов
        if "trenddown" in df_trend.columns and direction == "LONG":
            val = df_trend["trenddown"].iloc[-1]
            return float(val) if val and val > 0 else None
        if "trendup" in df_trend.columns and direction == "SHORT":
            val = df_trend["trendup"].iloc[-1]
            return float(val) if val and val > 0 else None
    except Exception:
        pass
    return None


def simulate_tsl_on_candles(
    candles_15m: pd.DataFrame,
    candles_4h: Optional[pd.DataFrame],
    entry_price: float,
    sl_price: float,
    direction: str,
    strategy: str,  # "15m_only" | "cascade_1h" | "cascade_4h" | "deesc_2.5" | "deesc_3.0"
    deesc_r: float = 5.0,
    candles_1h: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Симулирует TSL-стратегию по свечам 15m.
    Для cascade_4h использует 4h тренд как TSL, 15m как entry.
    Возвращает {status, exit_r, exit_candle_idx}.
    """
    if candles_15m is None or len(candles_15m) < 5:
        return {"status": "NO_DATA", "exit_r": None}

    one_r = abs(entry_price - sl_price)
    if one_r == 0:
        return {"status": "INVALID", "exit_r": None}

    tsl_active = False
    current_tsl = sl_price  # начальный SL
    tsl_tf_used = "15m"

    for i in range(1, len(candles_15m)):
        candle = candles_15m.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])
        close_price = float(candle["close"])

        # Текущий P&L в R
        if direction == "LONG":
            current_r = (close_price - entry_price) / one_r
        else:
            current_r = (entry_price - close_price) / one_r

        # ── Проверка SL/TSL ──────────────────────────────────────────────
        sl_hit = False
        if direction == "LONG" and low <= current_tsl:
            sl_hit = True
            exit_price = current_tsl
        elif direction == "SHORT" and high >= current_tsl:
            sl_hit = True
            exit_price = current_tsl

        if sl_hit:
            if direction == "LONG":
                exit_r = (exit_price - entry_price) / one_r
            else:
                exit_r = (entry_price - exit_price) / one_r
            status = "TSL" if tsl_active else "SL"
            return {"status": status, "exit_r": exit_r, "exit_candle": i, "tsl_tf": tsl_tf_used}

        # ── Активация TSL после tsl_activation_r ─────────────────────────
        if not tsl_active and current_r >= TSL_ACTIVATION_R:
            tsl_active = True

        if not tsl_active:
            continue

        # ── Выбор TSL TF в зависимости от стратегии ──────────────────────
        df_for_tsl = candles_15m.iloc[:i+1].copy()
        use_4h = False

        if strategy == "cascade_4h" and candles_4h is not None and len(candles_4h) >= MIN_CANDLES:
            # Всегда используем 4h TSL (максимальная эскалация)
            df_for_tsl = candles_4h
            use_4h = True
            tsl_tf_used = "4h"
        elif strategy == "cascade_1h" and candles_1h is not None and len(candles_1h) >= MIN_CANDLES:
            # Каскад ограничен 1h (не 4h)
            df_for_tsl = candles_1h
            tsl_tf_used = "1h"
        elif strategy.startswith("deesc1h_") and candles_4h is not None and candles_1h is not None and len(candles_4h) >= MIN_CANDLES and len(candles_1h) >= MIN_CANDLES:
            # 4h до порога, потом де-эскалируем на 1h (не на 15m)
            if current_r < deesc_r:
                df_for_tsl = candles_4h
                use_4h = True
                tsl_tf_used = "4h"
            else:
                df_for_tsl = candles_1h
                tsl_tf_used = "1h_deesc"
        elif strategy.startswith("deesc_") and candles_4h is not None and len(candles_4h) >= MIN_CANDLES:
            # Используем 4h до порога, потом переключаемся на 15m
            if current_r < deesc_r:
                df_for_tsl = candles_4h
                use_4h = True
                tsl_tf_used = "4h"
            else:
                tsl_tf_used = "15m_deesc"
        # strategy == "15m_only": используем 15m (df_for_tsl уже = 15m)

        # ── Расчёт TSL линии ─────────────────────────────────────────────
        try:
            if len(df_for_tsl) >= MIN_CANDLES:
                df_trend = calculate_trend(df_for_tsl, factor=1.25)
                new_tsl = get_tsl_price(df_trend, direction)
                if new_tsl:
                    # TSL двигается только в сторону прибыли
                    if direction == "LONG" and new_tsl > current_tsl:
                        current_tsl = new_tsl
                    elif direction == "SHORT" and new_tsl < current_tsl:
                        current_tsl = new_tsl
        except Exception:
            pass

    # Если дошли до конца без закрытия
    if direction == "LONG":
        final_r = (float(candles_15m.iloc[-1]["close"]) - entry_price) / one_r
    else:
        final_r = (entry_price - float(candles_15m.iloc[-1]["close"])) / one_r

    return {"status": "OPEN", "exit_r": final_r, "tsl_tf": tsl_tf_used}


# ── Основная функция ─────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 70)
    print("  БЭКТЕСТ: CASCADE TSL vs SAME-TF 15m TSL")
    print("=" * 70)

    # Загружаем ЗАКРЫТЫЕ сделки с доступными данными
    conn = sqlite3.connect("subscriptions.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Берём ВСЕ TSL/TP/SL закрытые с известными entry/SL — для честного сравнения
    # Фильтр: исключаем баг-сделки timezone (DEV-49/DEV-50)
    cur.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, take_profit,
               R_multiple, tsl_tf, status, signal_type, created_at, features_json
        FROM simulated_trades
        WHERE status IN ('TSL','TP','SL')
          AND entry_price IS NOT NULL
          AND stop_loss IS NOT NULL
          AND entry_price > 0
          AND stop_loss > 0
          AND timeframe = '15m'
          AND (features_json IS NULL OR features_json NOT LIKE '%bug_timezone%')
        ORDER BY created_at DESC
        LIMIT 200
    """)
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"\nЗагружено {len(trades)} сделок для прогона\n")

    # Инициализируем data collector
    dc = RealTimeData("bingx", api_semaphore_size=10, api_rps=10.0)
    await dc.load_markets()

    results = {
        "15m_only":    [],
        "cascade_1h":  [],
        "cascade_4h":  [],
        "deesc_2.5":   [],
        "deesc_3.0":   [],
        "deesc_5.0":   [],
        "deesc1h_2.5": [],
        "deesc1h_3.0": [],
        "deesc1h_5.0": [],
    }

    errors = 0
    processed = 0
    seen_symbols = set()

    for trade in trades:
        sym = trade["symbol"]
        direction = (trade["direction"] or "").upper()
        entry = float(trade["entry_price"])
        sl = float(trade["stop_loss"])
        actual_r = trade["R_multiple"]

        if not direction or direction not in ("LONG", "SHORT"):
            continue

        # Лимит уникальных символов (экономим API)
        if len(seen_symbols) >= SYMBOLS_LIMIT and sym not in seen_symbols:
            continue
        seen_symbols.add(sym)

        try:
            # Получаем OHLCV (15m, 1h и 4h)
            df_15m = await dc.get_ohlcv(sym, timeframe="15m", limit=MAX_CANDLES)
            df_1h  = await dc.get_ohlcv(sym, timeframe="1h",  limit=MAX_CANDLES)
            df_4h  = await dc.get_ohlcv(sym, timeframe="4h",  limit=MAX_CANDLES)

            if df_15m is None or len(df_15m) < 20:
                continue

            # Симулируем все стратегии
            for strategy in results.keys():
                if strategy.startswith("deesc1h_"):
                    deesc_r = float(strategy.split("_")[1])
                elif strategy.startswith("deesc_"):
                    deesc_r = float(strategy.split("_")[1])
                else:
                    deesc_r = 5.0
                res = simulate_tsl_on_candles(
                    df_15m, df_4h, entry, sl, direction,
                    strategy=strategy, deesc_r=deesc_r,
                    candles_1h=df_1h,
                )
                if res["exit_r"] is not None:
                    res["actual_r"] = actual_r
                    res["actual_status"] = trade["status"]
                    res["signal_type"] = trade["signal_type"]
                    res["symbol"] = sym
                    results[strategy].append(res)

            processed += 1
            if processed % 20 == 0:
                print(f"  Обработано {processed}/{len(trades)}...")

        except Exception as e:
            errors += 1
            continue

    await dc.stop()

    # ── Анализ результатов ──────────────────────────────────────────────────
    print(f"\nОбработано: {processed}, ошибок: {errors}, символов: {len(seen_symbols)}\n")

    print("=" * 70)
    print("  РЕЗУЛЬТАТЫ СРАВНЕНИЯ СТРАТЕГИЙ")
    print("=" * 70)

    summary = {}
    for strategy, res_list in results.items():
        if not res_list:
            continue
        rs = [r["exit_r"] for r in res_list if r["exit_r"] is not None]
        if not rs:
            continue
        wins = [r for r in res_list if r["status"] in ("TSL", "TP") or r["exit_r"] > 0]
        tsl_closed = [r for r in res_list if r["status"] == "TSL"]
        moonshots = [r for r in res_list if r["exit_r"] and r["exit_r"] >= 5]

        avg_r = sum(rs) / len(rs)
        avg_tsl = sum(r["exit_r"] for r in tsl_closed) / len(tsl_closed) if tsl_closed else 0
        win_rate = 100 * len(wins) / len(res_list)

        summary[strategy] = {
            "n": len(res_list), "avg_r": avg_r, "avg_tsl_r": avg_tsl,
            "win_rate": win_rate, "tsl_n": len(tsl_closed), "moonshots": len(moonshots)
        }

        label = {
            "15m_only":    "15m TSL (same-TF)",
            "cascade_1h":  "1h TSL (ограниченный каскад)",
            "cascade_4h":  "4h TSL (полная эскалация)",
            "deesc_2.5":   "4h→15m де-эскалация при 2.5R",
            "deesc_3.0":   "4h→15m де-эскалация при 3.0R",
            "deesc_5.0":   "4h→15m де-эскалация при 5.0R",
            "deesc1h_2.5": "4h→1h де-эскалация при 2.5R",
            "deesc1h_3.0": "4h→1h де-эскалация при 3.0R",
            "deesc1h_5.0": "4h→1h де-эскалация при 5.0R",
        }.get(strategy, strategy)

        print(f"\n  {label}")
        print(f"  {'─'*50}")
        print(f"  Сделок:        {len(res_list)}")
        print(f"  Win Rate:      {win_rate:.1f}%")
        print(f"  Avg R (все):   {avg_r:+.2f}")
        print(f"  Avg R (TSL):   {avg_tsl:+.2f}  (n={len(tsl_closed)})")
        print(f"  Moonshots ≥5R: {len(moonshots)}")

    print("\n" + "=" * 70)
    print("  СРАВНИТЕЛЬНАЯ ТАБЛИЦА")
    print("=" * 70)
    print(f"  {'Стратегия':<35} {'Avg R':>7} {'WR%':>7} {'Moonshots':>10}")
    print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*10}")
    for strategy, s in summary.items():
        label = {
            "15m_only":    "15m TSL (same-TF)            ",
            "cascade_1h":  "1h каскад                    ",
            "cascade_4h":  "4h каскад                    ",
            "deesc_2.5":   "4h→15m де-эскалация @ 2.5R   ",
            "deesc_3.0":   "4h→15m де-эскалация @ 3.0R   ",
            "deesc1h_2.5": "4h→1h  де-эскалация @ 2.5R   ",
            "deesc1h_3.0": "4h→1h  де-эскалация @ 3.0R   ",
            "deesc1h_5.0": "4h→1h  де-эскалация @ 5.0R   ",
        }.get(strategy, strategy)
        winner = " ← best" if s["avg_r"] == max(v["avg_r"] for v in summary.values()) else ""
        print(f"  {label:<35} {s['avg_r']:>+7.2f} {s['win_rate']:>6.1f}% {s['moonshots']:>10}{winner}")

    print("\n" + "=" * 70)
    print("  ИНТЕРПРЕТАЦИЯ")
    print("=" * 70)
    if summary:
        best = max(summary.items(), key=lambda x: x[1]["avg_r"])
        worst = min(summary.items(), key=lambda x: x[1]["avg_r"])
        delta = best[1]["avg_r"] - summary.get("15m_only", {}).get("avg_r", 0)

        if best[0] == "15m_only":
            print("  ✅ ГИПОТЕЗА ПОДТВЕРЖДЕНА: 15m TSL лучше каскадной эскалации")
            print(f"     Разница vs худшей стратегии: {best[1]['avg_r'] - worst[1]['avg_r']:+.2f}R")
        elif "deesc" in best[0]:
            print(f"  ⚡ ОПТИМУМ: де-эскалация ({best[0]}) лучше чистого 15m и чистого 4h")
            print(f"     Gain vs 15m_only: {delta:+.2f}R")
        else:
            print("  ❌ ГИПОТЕЗА ОПРОВЕРГНУТА: каскадная эскалация лучше same-TF")
            print(f"     Gain vs 15m_only: {delta:+.2f}R")

    print("\n  R-distribution (15m_only):")
    if "15m_only" in results:
        buckets = {"<0R": 0, "0-1R": 0, "1-3R": 0, "3-5R": 0, "5R+": 0}
        for r_val in [r["exit_r"] for r in results["15m_only"] if r["exit_r"] is not None]:
            if r_val < 0:
                buckets["<0R"] += 1
            elif r_val < 1:
                buckets["0-1R"] += 1
            elif r_val < 3:
                buckets["1-3R"] += 1
            elif r_val < 5:
                buckets["3-5R"] += 1
            else:
                buckets["5R+"] += 1
        for b, n in buckets.items():
            print(f"    {b:8s}: {n:4d}  {'█' * (n // 3)}")


if __name__ == "__main__":
    asyncio.run(run_backtest())
