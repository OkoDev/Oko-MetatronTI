#!/usr/bin/env python3
"""
backtest_all_signals.py
=======================
Полный бэктест всех сигналов и стратегий на 3m / 5m / 15m.

16 стратегий × 3 таймфрейма = 48 комбинаций.

LONG:
  wt_os30, wt_os45, wt_os59       — WT crossup из OS зоны
  wt_atr30, wt_atr45              — WT + ATR flip (= wt_signal бота)
  wt_div30, wt_div59              — WT + бычья дивергенция
  atr_long                        — ATR flip only
  pivot_s_wt                      — near S/PP + WT crossup (= pivot_reversal бота)
  confluence_long                 — WT + ATR + near S (тройная)

SHORT:
  wt_ob30, wt_ob45, wt_ob59       — WT crossdown из OB зоны
  wt_atr_sh45                     — WT + ATR flip вниз
  atr_short                       — ATR flip вниз only
  pivot_r_wt                      — near R/PP + WT crossdown

SL: ATR trendline
TP: 2R fixed + TSL после +1R
Период: 30 дней (пагинация)
Пары: топ-50 активных из subscriptions.db

Запуск: python scripts/backtest_all_signals.py [--tf 3m,5m,15m] [--days 30] [--pairs 50]
"""
from __future__ import annotations

import os, sys, asyncio, sqlite3, argparse, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
from typing import Optional

from core.infra.data_collector import RealTimeData
from core.indicators.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Параметры по умолчанию
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TIMEFRAMES = ["3m", "5m", "10m", "15m", "30m", "1h"]
DEFAULT_DAYS       = 30
DEFAULT_PAIRS      = 50
DEFAULT_DB         = "subscriptions.db"

ATR_FACTOR         = 1.25    # для calculate_trend
MIN_SL_PCT         = 0.003   # минимальная дистанция SL (0.3%)
MAX_SL_PCT         = 0.06    # максимальная (6%)
RR                 = 2.0     # reward/risk ratio для fixed TP
TSL_ACTIVATION_R   = 1.0     # активация TSL после N×R
MAX_BARS_HOLD      = 2000    # максимум баров в позиции (защита)
DIV_LOOKBACK       = 50      # bars для поиска дивергенции
DIV_MIN_BARS       = 5
PIVOT_TOUCH_PCT    = 0.008   # 0.8% от пивота = "рядом"

# ─────────────────────────────────────────────────────────────────────────────
# Загрузка данных с пагинацией
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_history(exchange, symbol: str, timeframe: str, days: int) -> Optional[pd.DataFrame]:
    """Загружает N дней OHLCV через пагинацию (по 1440 свечей)."""
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    all_rows = []
    since    = start_ms

    for _attempt in range(20):  # max 20 запросов = 20×1440 свечей
        try:
            rows = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1440)
        except Exception as e:
            logger.debug("fetch_ohlcv %s %s: %s", symbol, timeframe, e)
            break
        if not rows:
            break
        all_rows.extend(rows)
        last_ts = rows[-1][0]
        if last_ts >= end_ms or len(rows) < 100:
            break
        since = last_ts + 1
        await asyncio.sleep(0.15)  # rate limit

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df = df[df["time"] <= end_ms]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Индикаторы
# ─────────────────────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Вычисляет WT, ATR trend, дневные пивоты."""
    df = df.copy()
    df = calculate_wt(df)
    df = calculate_trend(df, factor=ATR_FACTOR)

    # Дневные классические пивоты (без look-ahead: используем предыдущий день)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df_idx   = df.set_index("dt")

    daily = df_idx.resample("1D").agg({"high": "max", "low": "min", "close": "last"})
    daily["pp"] = (daily["high"] + daily["low"] + daily["close"]) / 3
    daily["s1"] = 2 * daily["pp"] - daily["high"]
    daily["r1"] = 2 * daily["pp"] - daily["low"]
    daily["s2"] = daily["pp"] - (daily["high"] - daily["low"])
    daily["r2"] = daily["pp"] + (daily["high"] - daily["low"])

    # shift(1) = используем пивоты ПРЕДЫДУЩЕГО дня → нет look-ahead
    for col in ["pp", "s1", "r1", "s2", "r2"]:
        daily[col] = daily[col].shift(1)

    # Маппинг обратно на минутные бары
    daily_reindexed = daily[["pp", "s1", "r1", "s2", "r2"]].reindex(
        df_idx.index.floor("D"), method="ffill"
    )
    daily_reindexed.index = df_idx.index

    for col in ["pp", "s1", "r1", "s2", "r2"]:
        df[col] = daily_reindexed[col].values

    df = df.drop(columns=["dt"])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Детекторы дивергенции
# ─────────────────────────────────────────────────────────────────────────────

def _bull_div(df: pd.DataFrame, i: int) -> bool:
    """Бычья дивергенция: цена ниже, WT выше предыдущего минимума."""
    if i < DIV_MIN_BARS + 1:
        return False
    cur_wt  = df["wt1"].iloc[i]
    cur_low = df["low"].iloc[i]
    start   = max(1, i - DIV_LOOKBACK)
    for j in range(i - DIV_MIN_BARS, start, -1):
        wt_j = df["wt1"].iloc[j]
        if pd.isna(wt_j):
            continue
        wt_p = df["wt1"].iloc[j - 1]
        wt_n = df["wt1"].iloc[j + 1] if j + 1 < len(df) else np.nan
        if pd.isna(wt_p) or pd.isna(wt_n):
            continue
        if wt_j < wt_p and wt_j < wt_n:  # локальный минимум WT
            if cur_low < df["low"].iloc[j] and cur_wt > wt_j:
                return True
    return False


def _bear_div(df: pd.DataFrame, i: int) -> bool:
    """Медвежья дивергенция: цена выше, WT ниже предыдущего максимума."""
    if i < DIV_MIN_BARS + 1:
        return False
    cur_wt   = df["wt1"].iloc[i]
    cur_high = df["high"].iloc[i]
    start    = max(1, i - DIV_LOOKBACK)
    for j in range(i - DIV_MIN_BARS, start, -1):
        wt_j = df["wt1"].iloc[j]
        if pd.isna(wt_j):
            continue
        wt_p = df["wt1"].iloc[j - 1]
        wt_n = df["wt1"].iloc[j + 1] if j + 1 < len(df) else np.nan
        if pd.isna(wt_p) or pd.isna(wt_n):
            continue
        if wt_j > wt_p and wt_j > wt_n:  # локальный максимум WT
            if cur_high > df["high"].iloc[j] and cur_wt < wt_j:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Детекторы сигналов
# ─────────────────────────────────────────────────────────────────────────────

def _wt_crossup(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    w1p = df["wt1"].iloc[i-1]; w2p = df["wt2"].iloc[i-1]
    w1c = df["wt1"].iloc[i];   w2c = df["wt2"].iloc[i]
    if any(pd.isna(v) for v in [w1p, w2p, w1c, w2c]):
        return False
    return (w1p < w2p) and (w1c >= w2c)


def _wt_crossdown(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    w1p = df["wt1"].iloc[i-1]; w2p = df["wt2"].iloc[i-1]
    w1c = df["wt1"].iloc[i];   w2c = df["wt2"].iloc[i]
    if any(pd.isna(v) for v in [w1p, w2p, w1c, w2c]):
        return False
    return (w1p > w2p) and (w1c <= w2c)


def _atr_flip_long(df: pd.DataFrame, i: int, window: int = 1) -> bool:
    """ATR trend переключился с -1 на +1 в пределах window баров."""
    for w in range(window + 1):
        if i - w < 1:
            continue
        t_cur  = df["trend"].iloc[i - w]
        t_prev = df["trend"].iloc[i - w - 1]
        if pd.isna(t_cur) or pd.isna(t_prev):
            continue
        if t_cur == 1.0 and t_prev == -1.0:
            return True
    return False


def _atr_flip_short(df: pd.DataFrame, i: int, window: int = 1) -> bool:
    for w in range(window + 1):
        if i - w < 1:
            continue
        t_cur  = df["trend"].iloc[i - w]
        t_prev = df["trend"].iloc[i - w - 1]
        if pd.isna(t_cur) or pd.isna(t_prev):
            continue
        if t_cur == -1.0 and t_prev == 1.0:
            return True
    return False


def _near_support(df: pd.DataFrame, i: int, price: float) -> bool:
    """Цена рядом с S1, S2 или PP (снизу)."""
    for col in ["s1", "s2", "pp"]:
        lvl = df[col].iloc[i]
        if pd.isna(lvl) or lvl <= 0:
            continue
        if abs(price - lvl) / price <= PIVOT_TOUCH_PCT:
            return True
    return False


def _near_resistance(df: pd.DataFrame, i: int, price: float) -> bool:
    """Цена рядом с R1, R2 или PP (сверху)."""
    for col in ["r1", "r2", "pp"]:
        lvl = df[col].iloc[i]
        if pd.isna(lvl) or lvl <= 0:
            continue
        if abs(price - lvl) / price <= PIVOT_TOUCH_PCT:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Симуляция сделки
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trade(df: pd.DataFrame, entry_idx: int, direction: str,
                   sl_price: float, rr: float = RR,
                   tsl_r: float = TSL_ACTIVATION_R) -> Optional[dict]:
    """Симулирует сделку с TSL. Возвращает {status, r, bars} или None."""
    if entry_idx >= len(df) - 1:
        return None
    entry = float(df["open"].iloc[entry_idx + 1])  # вход по следующему бару
    if entry <= 0 or sl_price <= 0:
        return None

    sl_dist = abs(entry - sl_price)
    if sl_dist / entry < MIN_SL_PCT or sl_dist / entry > MAX_SL_PCT:
        return None

    tp         = entry + sl_dist * rr if direction == "LONG" else entry - sl_dist * rr
    tsl_active = False
    tsl_line   = sl_price
    one_r      = sl_dist

    for i in range(entry_idx + 2, min(entry_idx + 2 + MAX_BARS_HOLD, len(df))):
        high  = float(df["high"].iloc[i])
        low   = float(df["low"].iloc[i])

        if direction == "LONG":
            trend_sl = df["trendup"].iloc[i]

            if not tsl_active and high >= entry + one_r * tsl_r:
                tsl_active = True

            if tsl_active and not pd.isna(trend_sl):
                tsl_line = max(tsl_line, float(trend_sl))

            if low <= (tsl_line if tsl_active else sl_price):
                r = (tsl_line - entry) / one_r if tsl_active else -1.0
                return {"status": "TSL" if tsl_active else "SL", "r": round(r, 3), "bars": i - entry_idx}

            if high >= tp:
                return {"status": "TP", "r": rr, "bars": i - entry_idx}

        else:  # SHORT
            trend_sl = df["trenddown"].iloc[i]

            if not tsl_active and low <= entry - one_r * tsl_r:
                tsl_active = True

            if tsl_active and not pd.isna(trend_sl):
                tsl_line = min(tsl_line, float(trend_sl))

            if high >= (tsl_line if tsl_active else sl_price):
                r = (entry - tsl_line) / one_r if tsl_active else -1.0
                return {"status": "TSL" if tsl_active else "SL", "r": round(r, 3), "bars": i - entry_idx}

            if low <= tp:
                return {"status": "TP", "r": rr, "bars": i - entry_idx}

    # Позиция не закрылась
    last = float(df["close"].iloc[min(entry_idx + 1 + MAX_BARS_HOLD, len(df) - 1)])
    r = (last - entry) / one_r if direction == "LONG" else (entry - last) / one_r
    return {"status": "OPEN", "r": round(r, 3), "bars": MAX_BARS_HOLD}


# ─────────────────────────────────────────────────────────────────────────────
# Поиск сигналов по стратегии
# ─────────────────────────────────────────────────────────────────────────────

def find_signals(df: pd.DataFrame, strategy: str) -> list:
    """Возвращает список {idx, direction, sl_price} для стратегии."""
    signals = []
    n = len(df)

    for i in range(DIV_LOOKBACK + 2, n - 2):
        w1 = df["wt1"].iloc[i]
        if pd.isna(w1):
            continue

        entry_price  = float(df["open"].iloc[i + 1])  # следующий бар
        trendup_sl   = df["trendup"].iloc[i]
        trenddown_sl = df["trenddown"].iloc[i]

        # ── LONG ──────────────────────────────────────────────────────────────
        if strategy == "wt_os30":
            if _wt_crossup(df, i) and w1 < -30:
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_os45":
            if _wt_crossup(df, i) and w1 < -45:
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_os59":
            if _wt_crossup(df, i) and w1 < -59:
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_atr30":
            if _wt_crossup(df, i) and w1 < -30 and _atr_flip_long(df, i):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_atr45":
            if _wt_crossup(df, i) and w1 < -45 and _atr_flip_long(df, i):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_div30":
            if _wt_crossup(df, i) and w1 < -30 and _bull_div(df, i):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "wt_div59":
            if _wt_crossup(df, i) and w1 < -59 and _bull_div(df, i):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "atr_long":
            if _atr_flip_long(df, i):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "pivot_s_wt":
            if _wt_crossup(df, i) and w1 < -20 and _near_support(df, i, entry_price):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        elif strategy == "confluence_long":
            if (_wt_crossup(df, i) and w1 < -30
                    and _atr_flip_long(df, i)
                    and _near_support(df, i, entry_price)):
                if not pd.isna(trendup_sl):
                    signals.append({"idx": i, "direction": "LONG", "sl": float(trendup_sl)})

        # ── SHORT ─────────────────────────────────────────────────────────────
        elif strategy == "wt_ob30":
            if _wt_crossdown(df, i) and w1 > 30:
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

        elif strategy == "wt_ob45":
            if _wt_crossdown(df, i) and w1 > 45:
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

        elif strategy == "wt_ob59":
            if _wt_crossdown(df, i) and w1 > 59:
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

        elif strategy == "wt_atr_sh45":
            if _wt_crossdown(df, i) and w1 > 45 and _atr_flip_short(df, i):
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

        elif strategy == "atr_short":
            if _atr_flip_short(df, i):
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

        elif strategy == "pivot_r_wt":
            if _wt_crossdown(df, i) and w1 > 20 and _near_resistance(df, i, entry_price):
                if not pd.isna(trenddown_sl):
                    signals.append({"idx": i, "direction": "SHORT", "sl": float(trenddown_sl)})

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Агрегация результатов
# ─────────────────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "wr": None, "avg_r": None, "pf": None, "max_dd": None}

    rs   = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r <= 0]

    wr    = round(len(wins) / len(trades) * 100, 1)
    avg_r = round(sum(rs) / len(rs), 3)

    gross_win  = sum(wins) if wins else 0
    gross_loss = abs(sum(loss)) if loss else 0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")

    # Max drawdown (running)
    peak = 0; dd = 0; max_dd = 0
    equity = 0
    for r in rs:
        equity += r
        if equity > peak:
            peak = equity
        dd = equity - peak
        if dd < max_dd:
            max_dd = dd

    return {
        "n": len(trades),
        "wr": wr,
        "avg_r": avg_r,
        "pf": pf,
        "max_dd": round(max_dd, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Вывод таблицы
# ─────────────────────────────────────────────────────────────────────────────

def _print_table(results: dict, timeframes: list) -> None:
    STRATS = [
        # LONG
        "wt_os30", "wt_os45", "wt_os59",
        "wt_atr30", "wt_atr45",
        "wt_div30", "wt_div59",
        "atr_long",
        "pivot_s_wt",
        "confluence_long",
        # SHORT
        "wt_ob30", "wt_ob45", "wt_ob59",
        "wt_atr_sh45",
        "atr_short",
        "pivot_r_wt",
    ]

    header = f"  {'Стратегия':20s}"
    for tf in timeframes:
        header += f"  {'--- ' + tf + ' ---':>24s}"
    print("\n" + "=" * (24 + 26 * len(timeframes)))
    print("  СРАВНИТЕЛЬНАЯ ТАБЛИЦА  (n / WR% / avgR / PF / MaxDD)")
    print("=" * (24 + 26 * len(timeframes)))
    print(header)
    print("  " + "-" * 20 + ("  " + "-" * 24) * len(timeframes))

    best_avg_r = {}  # strategy → best avgR across TFs
    for s in STRATS:
        best_avg_r[s] = max(
            (results.get((s, tf), {}).get("avg_r") or -99) for tf in timeframes
        )

    # Sort by best avgR
    sorted_strats = sorted(STRATS, key=lambda s: best_avg_r[s], reverse=True)

    prev_long = True
    for s in sorted_strats:
        is_short = s.startswith("wt_ob") or s.startswith("wt_atr_sh") or s in ("atr_short", "pivot_r_wt")
        if is_short and prev_long:
            print("  " + "·" * (20 + 26 * len(timeframes)))  # разделитель LONG/SHORT
            prev_long = False

        row = f"  {s:20s}"
        for tf in timeframes:
            st = results.get((s, tf), {})
            if not st or st.get("n", 0) == 0:
                row += f"  {'—':>24s}"
                continue
            n     = st["n"]
            wr    = st["wr"]
            avg_r = st["avg_r"]
            pf    = st["pf"]
            mdd   = st["max_dd"]
            flag  = " ⚠️" if n < 15 else ""
            cell  = f"n={n:3d} {wr:4.1f}% {avg_r:+.2f} PF{pf:.1f}{flag}"
            row  += f"  {cell:>24s}"
        print(row)

    print()

    # Отдельная таблица — только avgR для быстрого чтения
    print("\n  БЫСТРОЕ СРАВНЕНИЕ: только avgR")
    print("  " + f"{'Стратегия':20s}" + "".join(f"  {tf:>8s}" for tf in timeframes))
    print("  " + "-" * (20 + 10 * len(timeframes)))
    for s in sorted_strats:
        row = f"  {s:20s}"
        for tf in timeframes:
            avg_r = (results.get((s, tf)) or {}).get("avg_r")
            if avg_r is None:
                row += f"  {'—':>8s}"
            else:
                sign = "+" if avg_r >= 0 else ""
                row += f"  {sign}{avg_r:>6.3f}"
        print(row)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────────────────────

STRATEGIES = [
    # LONG
    "wt_os30", "wt_os45", "wt_os59",
    "wt_atr30", "wt_atr45",
    "wt_div30", "wt_div59",
    "atr_long",
    "pivot_s_wt",
    "confluence_long",
    # SHORT
    "wt_ob30", "wt_ob45", "wt_ob59",
    "wt_atr_sh45",
    "atr_short",
    "pivot_r_wt",
]


async def run(timeframes: list, days: int, pairs_limit: int, db_path: str) -> None:
    print("=" * 70)
    print(f"  BACKTEST ALL SIGNALS  |  TF={','.join(timeframes)}  |  {days}д  |  {pairs_limit} пар")
    print("=" * 70)

    # Символы из БД
    conn    = sqlite3.connect(db_path)
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades "
        "WHERE status IN ('TP','SL','TSL') "
        "ORDER BY created_at DESC LIMIT ?", (pairs_limit,)
    ).fetchall()]
    conn.close()
    print(f"Пар для теста: {len(symbols)}\n")

    dc = RealTimeData("bingx", api_semaphore_size=5, api_rps=5.0)
    await dc.load_markets()
    exchange = dc.exchange

    results: dict = {}  # (strategy, tf) → list[trade_dict]
    for key in [(s, tf) for s in STRATEGIES for tf in timeframes]:
        results[key] = []

    total_symbols = 0

    for sym_idx, sym in enumerate(symbols):
        print(f"  [{sym_idx+1:2d}/{len(symbols)}] {sym} ...", end=" ", flush=True)

        for tf in timeframes:
            df_raw = await fetch_history(exchange, sym, tf, days)
            if df_raw is None or len(df_raw) < 200:
                print(f"[{tf}:skip]", end=" ", flush=True)
                continue

            try:
                df = compute_indicators(df_raw)
            except Exception as e:
                print(f"[{tf}:err={e}]", end=" ", flush=True)
                continue

            n_by_strat = {}
            for strat in STRATEGIES:
                sigs = find_signals(df, strat)
                n_by_strat[strat] = len(sigs)
                for sig in sigs:
                    res = simulate_trade(df, sig["idx"], sig["direction"], sig["sl"])
                    if res is not None:
                        results[(strat, tf)].append(res)

            total_n = sum(n_by_strat.values())
            print(f"[{tf}:{total_n}sigs]", end=" ", flush=True)

        print()
        total_symbols += 1
        await asyncio.sleep(0.05)

    await dc.stop()

    # Агрегация и вывод
    stats: dict = {}
    for (strat, tf), trades in results.items():
        stats[(strat, tf)] = _stats(trades)

    print(f"\nОбработано символов: {total_symbols}")
    _print_table(stats, timeframes)

    # Топ-5 по avgR
    ranked = sorted(
        [(k, v) for k, v in stats.items() if v["n"] >= 15 and v["avg_r"] is not None],
        key=lambda x: x[1]["avg_r"], reverse=True
    )
    print("  ТОП-10 комбинаций (n >= 15):")
    for (strat, tf), st in ranked[:10]:
        print(f"    {strat:20s} {tf:4s}  n={st['n']:4d}  WR={st['wr']}%  avgR={st['avg_r']:+.3f}  PF={st['pf']}")


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest all signals on multiple TFs")
    parser.add_argument("--tf",   default=",".join(DEFAULT_TIMEFRAMES),
                        help="Таймфреймы через запятую (default: 3m,5m,15m)")
    parser.add_argument("--days", default=DEFAULT_DAYS,  type=int,
                        help=f"Период в днях (default: {DEFAULT_DAYS})")
    parser.add_argument("--pairs", default=DEFAULT_PAIRS, type=int,
                        help=f"Количество пар (default: {DEFAULT_PAIRS})")
    parser.add_argument("--db",   default=DEFAULT_DB,
                        help=f"Путь к БД (default: {DEFAULT_DB})")
    args = parser.parse_args()

    timeframes = [t.strip() for t in args.tf.split(",")]
    asyncio.run(run(timeframes, args.days, args.pairs, args.db))


if __name__ == "__main__":
    main()
