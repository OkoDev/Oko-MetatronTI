#!/usr/bin/env python3
"""
Backtesting: Пивотные конфлюэнции как зоны входа.

Идея:
  - Рассчитываем пивоты 1D / 1W / 1M на истории (скользящее окно)
  - Находим зоны где уровни разных TF совпадают (конфлюэнция)
  - Входим когда цена касается такой зоны
  - Выход: TSL стандартный (15m) или каскадный (1h)
  - Активация TSL: 0.5R / 1.0R / 1.5R / 2.0R

Запуск:
  python scripts/backtest_pivot_confluence.py
  python scripts/backtest_pivot_confluence.py --symbols BTC/USDT ETH/USDT --days 60
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import argparse
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators import calculate_trend, calculate_wt

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Конфигурация ─────────────────────────────────────────────────────────────

SYMBOLS_DEFAULT = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
    "BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
]
DAYS_DEFAULT    = 45
TOUCH_PCT       = 0.5   # % допуск касания зоны конфлюэнции
TOLERANCE_PCT   = 0.8   # % допуск между уровнями для признания конфлюэнции
ATR_PERIOD      = 14
ATR_FACTOR      = 1.5   # SL = entry ± ATR × factor
MAX_BARS_15M    = 192   # макс. длительность сделки (48h = 192 бара по 15m)
MIN_R_TO_TRADE  = 0.8   # мин. R до ближайшего противопивота (чтобы не входить слишком близко)

TSL_ACTIVATIONS = [0.5, 1.0, 1.5, 2.0]

# ── Датакласс результата сделки ───────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: str          # LONG / SHORT
    entry_price: float
    exit_price: float
    sl_price: float
    activation_r: float
    tsl_mode: str           # "15m" | "cascade_1h"
    result: str             # WIN / LOSS / EXPIRED
    r_multiple: float
    bars_held: int
    entry_time: datetime
    confluence_tfs: str     # "1D+1W" / "1D+1M" / "1W+1M" / "1D+1W+1M"
    confluence_strength: str  # "VERY_STRONG" / "STRONG" / "MODERATE"
    signal_type: str        # тип сигнала для входа


# ── Расчёт пивотов ───────────────────────────────────────────────────────────

def _pivot_levels(high: float, low: float, close: float) -> Dict[str, float]:
    """Traditional Pivot Points (PP, S1-S2, R1-R2)."""
    pp = (high + low + close) / 3
    return {
        "PP": pp,
        "R1": 2 * pp - low,
        "R2": pp + (high - low),
        "S1": 2 * pp - high,
        "S2": pp - (high - low),
    }


def compute_rolling_pivots(df_15m: pd.DataFrame) -> pd.DataFrame:
    """
    Для каждой 15m свечи добавляет пивоты 1D/1W/1M которые действовали в тот момент.
    Пивот X = OHLCV предыдущего периода X.
    Возвращает df с доп. столбцами pivot_1D_PP, pivot_1D_R1, ..., pivot_1W_PP, ..., pivot_1M_PP, ...
    """
    df = df_15m.copy()
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["date"] = df["dt"].dt.date
    df["week"] = df["dt"].dt.to_period("W")
    df["month"] = df["dt"].dt.to_period("M")

    # 1D агрегат
    daily = df.groupby("date").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    daily["prev_date"] = daily["date"].shift(1)
    daily["pivot_1D_PP"] = ((daily["high"].shift(1) + daily["low"].shift(1) + daily["close"].shift(1)) / 3)
    pp = daily["pivot_1D_PP"]
    h_prev = daily["high"].shift(1)
    l_prev = daily["low"].shift(1)
    daily["pivot_1D_R1"] = 2 * pp - l_prev
    daily["pivot_1D_R2"] = pp + (h_prev - l_prev)
    daily["pivot_1D_S1"] = 2 * pp - h_prev
    daily["pivot_1D_S2"] = pp - (h_prev - l_prev)
    daily_map = daily.set_index("date")

    # 1W агрегат
    weekly = df.groupby("week").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    weekly["prev_week"] = weekly["week"].shift(1)
    pp_w = (weekly["high"].shift(1) + weekly["low"].shift(1) + weekly["close"].shift(1)) / 3
    h_prev_w = weekly["high"].shift(1)
    l_prev_w = weekly["low"].shift(1)
    weekly["pivot_1W_PP"] = pp_w
    weekly["pivot_1W_R1"] = 2 * pp_w - l_prev_w
    weekly["pivot_1W_R2"] = pp_w + (h_prev_w - l_prev_w)
    weekly["pivot_1W_S1"] = 2 * pp_w - h_prev_w
    weekly["pivot_1W_S2"] = pp_w - (h_prev_w - l_prev_w)
    weekly_map = weekly.set_index("week")

    # 1M агрегат
    monthly = df.groupby("month").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    pp_m = (monthly["high"].shift(1) + monthly["low"].shift(1) + monthly["close"].shift(1)) / 3
    h_prev_m = monthly["high"].shift(1)
    l_prev_m = monthly["low"].shift(1)
    monthly["pivot_1M_PP"] = pp_m
    monthly["pivot_1M_R1"] = 2 * pp_m - l_prev_m
    monthly["pivot_1M_R2"] = pp_m + (h_prev_m - l_prev_m)
    monthly["pivot_1M_S1"] = 2 * pp_m - h_prev_m
    monthly["pivot_1M_S2"] = pp_m - (h_prev_m - l_prev_m)
    monthly_map = monthly.set_index("month")

    pivot_cols_1d = ["pivot_1D_PP","pivot_1D_R1","pivot_1D_R2","pivot_1D_S1","pivot_1D_S2"]
    pivot_cols_1w = ["pivot_1W_PP","pivot_1W_R1","pivot_1W_R2","pivot_1W_S1","pivot_1W_S2"]
    pivot_cols_1m = ["pivot_1M_PP","pivot_1M_R1","pivot_1M_R2","pivot_1M_S1","pivot_1M_S2"]

    for col in pivot_cols_1d + pivot_cols_1w + pivot_cols_1m:
        df[col] = np.nan

    for idx, row in df.iterrows():
        d, w, m = row["date"], row["week"], row["month"]
        if d in daily_map.index:
            for col in pivot_cols_1d:
                df.at[idx, col] = daily_map.at[d, col]
        if w in weekly_map.index:
            for col in pivot_cols_1w:
                df.at[idx, col] = weekly_map.at[w, col]
        if m in monthly_map.index:
            for col in pivot_cols_1m:
                df.at[idx, col] = monthly_map.at[m, col]

    return df


# ── Поиск конфлюэнций ─────────────────────────────────────────────────────────

def find_confluences(row: pd.Series, current_price: float,
                     tolerance_pct: float = TOLERANCE_PCT) -> List[Dict]:
    """
    Для одной свечи находит все конфлюэнции пивотов разных TF.
    Возвращает список зон: {price, side, tfs, strength, label}
    """
    levels: Dict[str, Dict[str, float]] = {}
    for tf in ("1D", "1W", "1M"):
        tfd = {}
        for lvl in ("PP", "R1", "R2", "S1", "S2"):
            val = row.get(f"pivot_{tf}_{lvl}", np.nan)
            if pd.notna(val) and val > 0:
                tfd[lvl] = val
        if tfd:
            levels[tf] = tfd

    if len(levels) < 2:
        return []

    confluences = []
    tfs = list(levels.keys())
    seen = set()

    for i, tf_a in enumerate(tfs):
        for tf_b in tfs[i+1:]:
            for lvl_a, price_a in levels[tf_a].items():
                for lvl_b, price_b in levels[tf_b].items():
                    if price_a <= 0 or price_b <= 0:
                        continue
                    dist_pct = abs(price_a - price_b) / ((price_a + price_b) / 2) * 100
                    if dist_pct > tolerance_pct:
                        continue
                    zone_price = (price_a + price_b) / 2
                    key = round(zone_price, 8)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Сила конфлюэнции
                    if dist_pct < 0.1:
                        strength = "VERY_STRONG"
                    elif dist_pct < 0.4:
                        strength = "STRONG"
                    else:
                        strength = "MODERATE"

                    # Направление (support/resistance)
                    side = "support" if zone_price < current_price else "resistance"

                    # Проверяем третий TF
                    third_tfs = [t for t in tfs if t != tf_a and t != tf_b]
                    tfs_tag = f"{tf_a}+{tf_b}"
                    for tf_c in third_tfs:
                        for lvl_c, price_c in levels[tf_c].items():
                            dist_c = abs(zone_price - price_c) / zone_price * 100
                            if dist_c <= tolerance_pct:
                                tfs_tag = f"{tf_a}+{tf_b}+{tf_c}"
                                if strength != "VERY_STRONG":
                                    strength = "STRONG"
                                break

                    confluences.append({
                        "price": zone_price,
                        "side": side,
                        "tfs": tfs_tag,
                        "strength": strength,
                        "dist_pct": dist_pct,
                        "label": f"{tfs_tag} {lvl_a}/{lvl_b}",
                    })

    # Убираем дубли по близкой цене
    confluences.sort(key=lambda x: x["price"])
    merged = []
    for z in confluences:
        if not merged or abs(z["price"] - merged[-1]["price"]) / merged[-1]["price"] * 100 > 0.3:
            merged.append(z)
        else:
            # Оставляем более сильную
            if z["strength"] == "VERY_STRONG":
                merged[-1] = z

    return merged


# ── Симуляция TSL ─────────────────────────────────────────────────────────────

def simulate_tsl(
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry_price: float,
    sl_price: float,
    activation_r: float,
    cascade_to_1h: bool = False,
    max_bars: int = MAX_BARS_15M,
) -> Tuple[str, float, float, int]:
    """
    Симулирует TSL от entry_idx.
    Возвращает: (result, exit_price, r_multiple, bars_held)
    """
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return "EXPIRED", entry_price, 0.0, 0

    # Рассчитываем TSL линии для 15m и 1h
    df15 = calculate_trend(df_15m.iloc[:entry_idx + max_bars + 10].copy())
    df1h_for_tsl: Optional[pd.DataFrame] = None
    if cascade_to_1h and df_1h is not None and len(df_1h) > 20:
        df1h_for_tsl = calculate_trend(df_1h.copy())

    tsl_active = False
    use_1h_tsl = False

    for i in range(1, min(max_bars, len(df15) - entry_idx - 1)):
        bar_idx = entry_idx + i
        if bar_idx >= len(df15):
            break

        bar = df15.iloc[bar_idx]
        cur_close = bar["close"]
        cur_high  = bar["high"]
        cur_low   = bar["low"]

        # Прибыль/убыток
        if direction == "LONG":
            current_r = (cur_close - entry_price) / risk
            price_worst = cur_low
        else:
            current_r = (entry_price - cur_close) / risk
            price_worst = cur_high

        # Проверка SL
        if direction == "LONG" and price_worst <= sl_price:
            exit_p = sl_price
            r_mul = (exit_p - entry_price) / risk
            return "LOSS", exit_p, round(r_mul, 3), i
        if direction == "SHORT" and price_worst >= sl_price:
            exit_p = sl_price
            r_mul = (entry_price - exit_p) / risk
            return "LOSS", exit_p, round(r_mul, 3), i

        # Активация TSL
        if not tsl_active and current_r >= activation_r:
            tsl_active = True
            if cascade_to_1h and df1h_for_tsl is not None:
                use_1h_tsl = True

        if tsl_active:
            # Определяем TSL уровень
            if use_1h_tsl and df1h_for_tsl is not None:
                # Маппинг времени 15m → 1h
                bar_time = bar.get("time", None) or (bar.name if hasattr(bar, "name") else None)
                if bar_time is not None:
                    # Найти соответствующий 1h бар (округляем вниз)
                    bar_time_ms = int(bar_time) if not isinstance(bar_time, datetime) else int(bar_time.timestamp() * 1000)
                    hour_ms = bar_time_ms - (bar_time_ms % 3_600_000)
                    matching_1h = df1h_for_tsl[df1h_for_tsl["time"] <= hour_ms]
                    if len(matching_1h) > 0:
                        last_1h = matching_1h.iloc[-1]
                        if direction == "LONG":
                            tsl_level = last_1h.get("trendup", None)
                        else:
                            tsl_level = last_1h.get("trenddown", None)
                    else:
                        tsl_level = None
                else:
                    tsl_level = None
                # Fallback на 15m если 1h не доступен
                if tsl_level is None or pd.isna(tsl_level) or tsl_level <= 0:
                    use_1h_tsl = False

            if not use_1h_tsl:
                if direction == "LONG":
                    tsl_level = bar.get("trendup", None)
                else:
                    tsl_level = bar.get("trenddown", None)

            if tsl_level is not None and not pd.isna(tsl_level) and tsl_level > 0:
                # TSL hit?
                if direction == "LONG" and cur_low < tsl_level:
                    exit_p = tsl_level
                    r_mul = (exit_p - entry_price) / risk
                    return "WIN", exit_p, round(r_mul, 3), i
                if direction == "SHORT" and cur_high > tsl_level:
                    exit_p = tsl_level
                    r_mul = (entry_price - exit_p) / risk
                    return "WIN", exit_p, round(r_mul, 3), i

    # EXPIRED
    last = df15.iloc[min(entry_idx + max_bars, len(df15) - 1)]
    exit_p = last["close"]
    if direction == "LONG":
        r_mul = (exit_p - entry_price) / risk
    else:
        r_mul = (entry_price - exit_p) / risk
    return "EXPIRED", exit_p, round(r_mul, 3), max_bars


# ── Основной движок ───────────────────────────────────────────────────────────

class PivotConfluenceBacktest:
    def __init__(self, symbol: str, days: int = DAYS_DEFAULT):
        self.symbol = symbol
        self.days = days
        self.exchange = ccxt_async.bingx({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })

    async def _fetch(self, timeframe: str, limit: int) -> pd.DataFrame:
        """Загружает OHLCV с пагинацией (BingX лимит: 1440 баров за запрос)."""
        PAGE_SIZE = 1000
        since = int((datetime.now(timezone.utc) - timedelta(days=self.days + 10)).timestamp() * 1000)
        all_ohlcv = []
        cur_since = since
        pages = (limit // PAGE_SIZE) + 2
        for _ in range(pages):
            try:
                chunk = await self.exchange.fetch_ohlcv(
                    self.symbol, timeframe, since=cur_since, limit=PAGE_SIZE
                )
            except Exception as e:
                logger.warning(f"{self.symbol} fetch {timeframe}: {e}")
                break
            if not chunk:
                break
            all_ohlcv.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            cur_since = chunk[-1][0] + 1
            if len(all_ohlcv) >= limit:
                break
        if not all_ohlcv:
            return pd.DataFrame()
        df = pd.DataFrame(all_ohlcv, columns=["time","open","high","low","close","volume"])
        df = df.drop_duplicates("time").sort_values("time").dropna().reset_index(drop=True)
        return df

    async def run(self, activation_r: float, cascade: bool) -> List[Trade]:
        df_15m_raw = await self._fetch("15m", self.days * 96 + 200)
        df_1h_raw  = await self._fetch("1h",  self.days * 24 + 50)
        await self.exchange.close()

        if len(df_15m_raw) < 100:
            logger.warning(f"{self.symbol}: недостаточно данных (15m={len(df_15m_raw)})")
            return []

        # Рассчитываем пивоты на истории
        df_15m = compute_rolling_pivots(df_15m_raw)

        # Индикаторы
        df_15m = calculate_trend(df_15m)
        df_15m = calculate_wt(df_15m)

        # ATR для SL
        df_15m["tr"] = pd.concat([
            df_15m["high"] - df_15m["low"],
            (df_15m["high"] - df_15m["close"].shift(1)).abs(),
            (df_15m["low"]  - df_15m["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df_15m["atr14"] = df_15m["tr"].rolling(ATR_PERIOD, min_periods=1).mean()

        # 1h TSL
        df_1h = None
        if cascade and len(df_1h_raw) > 20:
            df_1h = calculate_trend(df_1h_raw)

        trades: List[Trade] = []
        in_trade = False
        skip_until = 0  # бар до которого не входить (после выхода из сделки)

        # Минимум 50 баров данных для прогрева
        for idx in range(50, len(df_15m) - MAX_BARS_15M - 1):
            if idx < skip_until:
                continue

            bar = df_15m.iloc[idx]
            cur_price = bar["close"]

            # Пивоты должны быть рассчитаны
            if pd.isna(bar.get("pivot_1D_PP", np.nan)):
                continue

            # Конфлюэнции на текущем баре
            zones = find_confluences(bar, cur_price)
            if not zones:
                continue

            atr = bar.get("atr14", 0)
            if atr <= 0:
                continue

            # Пробуем войти в одну из зон
            for zone in zones:
                zone_price = zone["price"]
                side = zone["side"]

                # Определяем направление
                direction = "LONG" if side == "support" else "SHORT"

                # Цена касается зоны? (low/high в пределах touch_pct)
                if direction == "LONG":
                    dist = (bar["low"] - zone_price) / zone_price * 100
                    touched = abs(dist) <= TOUCH_PCT and bar["low"] <= zone_price * (1 + TOUCH_PCT / 100)
                else:
                    dist = (bar["high"] - zone_price) / zone_price * 100
                    touched = abs(dist) <= TOUCH_PCT and bar["high"] >= zone_price * (1 - TOUCH_PCT / 100)

                if not touched:
                    continue

                # SL
                if direction == "LONG":
                    entry_price = zone_price * (1 + TOUCH_PCT / 200)  # чуть выше зоны
                    sl_price    = entry_price - ATR_FACTOR * atr
                else:
                    entry_price = zone_price * (1 - TOUCH_PCT / 200)
                    sl_price    = entry_price + ATR_FACTOR * atr

                # R до зоны минимален?
                risk = abs(entry_price - sl_price)
                if risk <= 0:
                    continue

                # Симуляция
                tsl_mode = "cascade_1h" if cascade else "15m"
                result, exit_price, r_mul, bars = simulate_tsl(
                    df_15m, df_1h, idx, direction,
                    entry_price, sl_price, activation_r, cascade_to_1h=cascade
                )

                outcome = "WIN" if r_mul > 0 else ("LOSS" if r_mul < 0 else "EXPIRED")

                trades.append(Trade(
                    symbol=self.symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    sl_price=sl_price,
                    activation_r=activation_r,
                    tsl_mode=tsl_mode,
                    result=outcome,
                    r_multiple=r_mul,
                    bars_held=bars,
                    entry_time=datetime.fromtimestamp(int(bar["time"]) / 1000, tz=timezone.utc),
                    confluence_tfs=zone["tfs"],
                    confluence_strength=zone["strength"],
                    signal_type="pivot_confluence",
                ))

                skip_until = idx + max(bars, 4)  # не входить снова сразу
                break  # одна сделка на бар

        return trades


# ── Агрегация результатов ─────────────────────────────────────────────────────

def aggregate(trades: List[Trade]) -> Dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "avg_r": 0.0, "pf": 0.0}
    n = len(trades)
    wins  = [t for t in trades if t.r_multiple > 0]
    all_r = [t.r_multiple for t in trades]
    wr    = len(wins) / n * 100
    avg_r = sum(all_r) / n
    gp    = sum(r for r in all_r if r > 0)
    gl    = abs(sum(r for r in all_r if r < 0))
    pf    = gp / gl if gl > 0 else 99.0
    return {"n": n, "wr": round(wr, 1), "avg_r": round(avg_r, 3), "pf": round(pf, 2)}


def print_table(all_trades: List[Trade]):
    if not all_trades:
        print("Нет сделок.")
        return

    print()
    print("=" * 90)
    print("СВОДНАЯ ТАБЛИЦА: Пивотные конфлюэнции как вход (TSL выход)")
    print("=" * 90)

    # По activation_r и TSL mode
    print(f"\n{'activation_r':<14} {'tsl_mode':<14} {'N':>5} {'WR%':>7} {'AvgR':>8} {'PF':>6}")
    print("-" * 56)
    for act_r in sorted(set(t.activation_r for t in all_trades)):
        for mode in ["15m", "cascade_1h"]:
            grp = [t for t in all_trades if t.activation_r == act_r and t.tsl_mode == mode]
            m = aggregate(grp)
            if m["n"] == 0:
                continue
            flag = "***" if m["pf"] >= 3 else "**" if m["pf"] >= 2 else "*" if m["pf"] >= 1.5 else "--" if m["pf"] < 1 else ""
            print(f"  {act_r:<12} {mode:<14} {m['n']:>5} {m['wr']:>7.1f} {m['avg_r']:>8.3f} {m['pf']:>6.2f}  {flag}")

    # По конфлюэнции TF
    print(f"\n--- По типу конфлюэнции TF ---")
    print(f"{'tfs':<16} {'N':>5} {'WR%':>7} {'AvgR':>8} {'PF':>6}")
    print("-" * 46)
    tfs_groups: Dict[str, List] = defaultdict(list)
    for t in all_trades:
        tfs_groups[t.confluence_tfs].append(t)
    for tfs in sorted(tfs_groups, key=lambda x: -len(tfs_groups[x])):
        m = aggregate(tfs_groups[tfs])
        print(f"  {tfs:<14} {m['n']:>5} {m['wr']:>7.1f} {m['avg_r']:>8.3f} {m['pf']:>6.2f}")

    # По силе конфлюэнции
    print(f"\n--- По силе конфлюэнции ---")
    print(f"{'strength':<16} {'N':>5} {'WR%':>7} {'AvgR':>8} {'PF':>6}")
    print("-" * 46)
    for strength in ["VERY_STRONG", "STRONG", "MODERATE"]:
        grp = [t for t in all_trades if t.confluence_strength == strength]
        m = aggregate(grp)
        if m["n"] > 0:
            print(f"  {strength:<14} {m['n']:>5} {m['wr']:>7.1f} {m['avg_r']:>8.3f} {m['pf']:>6.2f}")

    # По символу
    print(f"\n--- По символу (все activation_r + modes) ---")
    print(f"{'symbol':<22} {'N':>5} {'WR%':>7} {'AvgR':>8} {'PF':>6}")
    print("-" * 52)
    sym_groups: Dict[str, List] = defaultdict(list)
    for t in all_trades:
        sym_groups[t.symbol].append(t)
    for sym in sorted(sym_groups, key=lambda x: -len(sym_groups[x])):
        m = aggregate(sym_groups[sym])
        print(f"  {sym:<20} {m['n']:>5} {m['wr']:>7.1f} {m['avg_r']:>8.3f} {m['pf']:>6.2f}")

    # Итого
    overall = aggregate(all_trades)
    print(f"\n{'ИТОГО':<22} {overall['n']:>5} {overall['wr']:>7.1f} {overall['avg_r']:>8.3f} {overall['pf']:>6.2f}")

    # Рекомендация
    print("\n" + "=" * 90)
    print("РЕКОМЕНДАЦИИ:")

    best_params = None
    best_pf = 0.0
    for act_r in sorted(set(t.activation_r for t in all_trades)):
        for mode in ["15m", "cascade_1h"]:
            grp = [t for t in all_trades if t.activation_r == act_r and t.tsl_mode == mode]
            m = aggregate(grp)
            if m["n"] >= 10 and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = (act_r, mode, m)
    if best_params:
        act_r, mode, m = best_params
        print(f"  Лучшая комбинация: activation_r={act_r}, tsl={mode}")
        print(f"  N={m['n']} | WR={m['wr']}% | Avg_R={m['avg_r']} | PF={m['pf']}")

    best_tfs = max(tfs_groups, key=lambda x: aggregate(tfs_groups[x])["pf"] if len(tfs_groups[x]) >= 5 else 0, default=None)
    if best_tfs:
        m = aggregate(tfs_groups[best_tfs])
        print(f"  Лучший тип конфлюэнции: {best_tfs} (N={m['n']}, PF={m['pf']})")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Backtest: пивотные конфлюэнции как входы")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS_DEFAULT)
    parser.add_argument("--days",    type=int,   default=DAYS_DEFAULT)
    parser.add_argument("--activations", nargs="+", type=float, default=TSL_ACTIVATIONS,
                        help="Список activation_r для TSL (напр. 0.5 1.0 1.5 2.0)")
    parser.add_argument("--no-cascade", action="store_true",
                        help="Не использовать каскадный TSL (только 15m)")
    args = parser.parse_args()

    symbols  = args.symbols
    days     = args.days
    act_list = args.activations
    cascades = [False] if args.no_cascade else [False, True]

    print(f"Запуск: {len(symbols)} символов, {days} дней, activations={act_list}")
    print(f"TSL режимы: {['15m', 'cascade_1h'] if not args.no_cascade else ['15m']}")

    all_trades: List[Trade] = []
    total = len(symbols) * len(act_list) * len(cascades)
    done  = 0

    for symbol in symbols:
        for cascade in cascades:
            for act_r in act_list:
                done += 1
                print(f"  [{done}/{total}] {symbol} act_r={act_r} cascade={cascade} ...", end="", flush=True)
                try:
                    bt = PivotConfluenceBacktest(symbol, days=days)
                    trades = await bt.run(activation_r=act_r, cascade=cascade)
                    all_trades.extend(trades)
                    m = aggregate(trades)
                    print(f" N={m['n']} WR={m['wr']}% PF={m['pf']}")
                except Exception as e:
                    print(f" ОШИБКА: {e}")

    print_table(all_trades)


if __name__ == "__main__":
    asyncio.run(main())
