#!/usr/bin/env python3
"""
Backtest MTF OTE Detector (ARCH-53) — экстремальный тест на 20 парах / 90 дней.

Тестирует два pipeline:
  SWING: zone 1h/4h/1d  → trigger 15m  (позиционный)
  SCALP: zone 15m        → trigger 3m   (скальпинг)

Метрики: Win Rate, Avg R, Sharpe, Max DD, сигналов/день, % пар с конфлюенцией.

Запуск:
  python scripts/backtest_ote_mtf.py
  python scripts/backtest_ote_mtf.py --pairs BTC ETH SOL --days 30
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import ccxt.async_support as ccxt_async
import numpy as np
import pandas as pd

from core.indicators.indicators import calculate_wt
from core.smc.models import analyze_smc, SMCContext
from core.smc.structure import detect_structure
from core.smc.fibonacci import detect_fibonacci, FibAnalysis
from core.signals.ote_detector import detect_ote_signal, _ZONE_TF_PRIORITY
from scripts.ohlcv_cache import OHLCVCache

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ─── Быстрый SMC контекст (только structure + fib) ───────────────────────────

def _fast_zone_ctx(df_zone: pd.DataFrame) -> Optional[SMCContext]:
    """Лёгкая версия analyze_smc — только structure + fibonacci (без FVG/OB/liquidity).
    Используется для precompute кеша в бэктесте (52ms vs 139ms полного analyze_smc).
    """
    if df_zone is None or len(df_zone) < 30:
        return None
    try:
        struct = detect_structure(df_zone)
        fib    = detect_fibonacci(df_zone, struct)
        ctx    = SMCContext()
        ctx.structure  = struct
        ctx.fibonacci  = fib
        return ctx
    except Exception:
        return None


def _precompute_zone_snapshots(
    df_zone: pd.DataFrame,
    refresh_every_n: int = 1,
    lookback: int = 300,
) -> List[Tuple[Any, SMCContext]]:
    """Precompute зонные SMC snapshots.

    Вычисляет _fast_zone_ctx каждые `refresh_every_n` баров.
    Возвращает list[(bar_close_time, ctx)] отсортированный по времени.
    """
    result = []
    for i in range(30, len(df_zone), refresh_every_n):
        ctx = _fast_zone_ctx(df_zone.iloc[max(0, i - lookback) : i + 1])
        if ctx is not None:
            result.append((df_zone.index[i], ctx))
    return result


def _lookup_zone_ctx(
    snapshots: List[Tuple[Any, SMCContext]],
    cur_time: Any,
) -> Optional[SMCContext]:
    """Бинарный поиск последнего snapshot закрытого до cur_time."""
    lo, hi = 0, len(snapshots) - 1
    found = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if snapshots[mid][0] <= cur_time:
            found = snapshots[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found

# ─── Конфигурация ─────────────────────────────────────────────────────────────

PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "DOGE/USDT", "XRP/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "FIL/USDT",
    "ARB/USDT", "OP/USDT", "APT/USDT", "SUI/USDT", "INJ/USDT",
]

ATR_PERIOD   = 14
ATR_FACTOR   = 1.5    # SL = ATR × 1.5
TP_R         = 2.0    # TP = SL_dist × 2.0
MAX_HOLD     = 32     # баров trigger TF (макс время в сделке)
WARMUP_BARS  = 200    # баров прогрева для SMC/индикаторов
STEP_SWING   = 4      # проверять сигнал каждые N баров 15m (= 1 час)
STEP_SCALP   = 5      # проверять сигнал каждые N баров 3m  (= 15 мин)


# ─── Данные ───────────────────────────────────────────────────────────────────

async def fetch_ohlcv(exch, symbol: str, tf: str, days: int,
                       cache: "OHLCVCache") -> pd.DataFrame:
    """Грузим историю с Binance spot. Использует SQLite-кеш для повторных запусков."""
    until_ms  = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms  = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    # Проверяем покрытие кеша
    cache_min, cache_max = cache.get_coverage(symbol, tf)
    need_fetch_from = since_ms

    if cache_min is not None and cache_min <= since_ms:
        # Кеш покрывает нужный начальный период — докачиваем только хвост
        need_fetch_from = cache_max + 1

    # Загружаем недостающий хвост
    all_rows = []
    limit    = 1000
    cur      = need_fetch_from
    while cur < until_ms:
        try:
            rows = await exch.fetch_ohlcv(symbol, tf, since=cur, limit=limit)
        except Exception as e:
            logger.warning("[%s %s] fetch error: %s", symbol, tf, e)
            break
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        cur = rows[-1][0] + 1

    # Сохраняем новые бары в кеш
    if all_rows:
        df_new = pd.DataFrame(all_rows, columns=["time","open","high","low","close","volume"])
        cache.save(symbol, tf, df_new)

    # Читаем из кеша полный диапазон
    df_cached = cache.read(symbol, tf, since_ms, until_ms)
    if df_cached is None or df_cached.empty:
        return pd.DataFrame()

    df_cached["time"] = pd.to_datetime(df_cached["time"], unit="ms", utc=True)
    df_cached = df_cached.set_index("time").drop_duplicates().sort_index()
    for col in ("open","high","low","close","volume"):
        df_cached[col] = pd.to_numeric(df_cached[col], errors="coerce")
    return df_cached


# ─── Trade simulation ─────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    label:              str
    ote_zone_min_fib:   float = 0.705   # граница зоны (0.705 / 0.618 / 0.5)
    require_wt_in_obos: bool  = False   # WT must be in OS(LONG) or OB(SHORT)
    min_zone_tf:        str   = "1h"    # минимальный primary TF ("1h"=нет фильтра, "4h"=только 4h/1d)
    choch_only:         bool  = False   # True → отклонять BOS-сигналы


# Сравниваемые конфигурации
CONFIGS = [
    BacktestConfig(label="C0 baseline  [0.705-0.786]",
                   ote_zone_min_fib=0.705, require_wt_in_obos=False, min_zone_tf="1h",  choch_only=False),
    BacktestConfig(label="C1 DEV-88    [0.705]+4h+CHoCH",
                   ote_zone_min_fib=0.705, require_wt_in_obos=False, min_zone_tf="4h",  choch_only=True),
    BacktestConfig(label="C2 0.618+OB/OS+4h+CHoCH",
                   ote_zone_min_fib=0.618, require_wt_in_obos=True,  min_zone_tf="4h",  choch_only=True),
    BacktestConfig(label="C3 0.5+OB/OS+4h+CHoCH  ",
                   ote_zone_min_fib=0.500, require_wt_in_obos=True,  min_zone_tf="4h",  choch_only=True),
]

_TF_ORDER = {"1h": 0, "4h": 1, "1d": 2}   # для min_zone_tf фильтра


@dataclass
class OTETrade:
    symbol:        str
    mode:          str        # "swing" | "scalp"
    direction:     str        # "LONG" | "SHORT"
    entry_price:   float
    sl:            float
    tp:            float
    entry_bar:     int
    result:        str = ""   # "WIN" | "LOSS" | "EXPIRED"
    exit_price:    float = 0.0
    r_multiple:    float = 0.0
    confirmed_tfs: List[str] = field(default_factory=list)
    primary_tf:    str = ""
    tight_ote:     bool = False
    is_bos:        bool = False


def simulate_trade(df_trigger: pd.DataFrame, entry_idx: int,
                   direction: str, entry_price: float,
                   sl: float, tp: float) -> Tuple[str, float, float]:
    """Проверяем исход на последующих барах. Возвращает (result, exit_price, r_multiple)."""
    sl_dist = abs(entry_price - sl)
    if sl_dist <= 0:
        return "EXPIRED", entry_price, 0.0

    future = df_trigger.iloc[entry_idx + 1 : entry_idx + 1 + MAX_HOLD]
    for _, bar in future.iterrows():
        if direction == "LONG":
            if bar["low"] <= sl:
                return "LOSS", sl, -1.0
            if bar["high"] >= tp:
                return "WIN", tp, TP_R
        else:
            if bar["high"] >= sl:
                return "LOSS", sl, -1.0
            if bar["low"] <= tp:
                return "WIN", tp, TP_R
    return "EXPIRED", float(df_trigger.iloc[min(entry_idx + MAX_HOLD, len(df_trigger)-1)]["close"]), 0.0


# ─── OTE Detection на срезе ───────────────────────────────────────────────────

def run_ote_on_slice(
    symbol: str,
    df_trigger_slice: pd.DataFrame,
    zone_dfs: Dict[str, pd.DataFrame],  # tf -> df (обрезан до current time)
    trigger_tf: str,
    mode: str,
) -> Optional[OTETrade]:
    """Пытается детектировать OTE на текущем срезе. Возвращает незакрытую сделку или None."""
    if len(df_trigger_slice) < WARMUP_BARS:
        return None

    # WT на trigger slice (только последние 100 баров для скорости)
    df_trig = df_trigger_slice.iloc[-min(200, len(df_trigger_slice)):]
    if "cross_up" not in df_trig.columns:
        df_trig = calculate_wt(df_trig)

    # SMC на каждом zone TF
    smc_contexts = {}
    for ztf, df_zone_full in zone_dfs.items():
        if df_zone_full is None or len(df_zone_full) < 30:
            continue
        try:
            ctx = analyze_smc(df_zone_full.iloc[-min(300, len(df_zone_full)):])
            smc_contexts[ztf] = ctx
        except Exception:
            pass

    if not smc_contexts:
        return None

    sig = detect_ote_signal(
        df_trigger=df_trig,
        symbol=symbol,
        smc_contexts=smc_contexts,
        trigger_tf=trigger_tf,
        shadow_mode=False,   # бэктест: shadow=False, получаем SignalData
    )
    if sig is None:
        return None

    # Строим SL/TP от ATR
    close = float(df_trig["close"].iloc[-1])
    atr = float(df_trig["close"].rolling(ATR_PERIOD).std().iloc[-1]) * ATR_FACTOR
    if atr <= 0 or atr / close > 0.1:   # слишком широкий ATR — пропуск
        return None

    direction = sig.direction.value
    if direction == "LONG":
        sl = close - atr
        tp = close + atr * TP_R
    else:
        sl = close + atr
        tp = close - atr * TP_R

    return OTETrade(
        symbol        = symbol,
        mode          = mode,
        direction     = direction,
        entry_price   = close,
        sl            = sl,
        tp            = tp,
        entry_bar     = len(df_trigger_slice) - 1,
        confirmed_tfs = sig.data.get("confirmed_tfs", []),
        primary_tf    = sig.data.get("primary_tf", ""),
        tight_ote     = sig.data.get("tight_ote", False),
        is_bos        = sig.data.get("is_bos", False),
    )


# ─── Backtest одной пары ──────────────────────────────────────────────────────

def backtest_pair(
    symbol: str,
    dfs: Dict[str, pd.DataFrame],
    days: int,
    cfg: Optional["BacktestConfig"] = None,
) -> List[OTETrade]:
    """Полный бэктест одной пары — swing + scalp режимы.

    Оптимизация: SMC zone contexts precomputed один раз (по границам zone TF баров),
    затем переиспользуются через бинарный поиск. Снижает O(n_trigger × n_zones)
    analyze_smc вызовов до O(n_zone_bars).
    """
    trades: List[OTETrade] = []
    if cfg is None:
        cfg = CONFIGS[0]   # baseline по умолчанию

    # ── WT на всём trigger TF (одно вычисление) ───────────────────────────
    # calculate_wt сбрасывает индекс — восстанавливаем DatetimeIndex явно
    # Добавляем cross_up/cross_down, которые нужны detect_ote_signal()
    def _add_wt_crosses(df: pd.DataFrame) -> pd.DataFrame:
        orig_idx = df.index
        df = calculate_wt(df.copy())
        df.index = orig_idx
        cross_up   = (df["wt1"].shift(1) < df["wt2"].shift(1)) & (df["wt1"] > df["wt2"])
        cross_down = (df["wt1"].shift(1) > df["wt2"].shift(1)) & (df["wt1"] < df["wt2"])
        df["cross_up"]   = np.where(cross_up,   df["wt2"], np.nan)
        df["cross_down"] = np.where(cross_down, df["wt2"], np.nan)
        return df

    df_15m_wt = dfs.get("15m")
    if df_15m_wt is not None:
        df_15m_wt = _add_wt_crosses(df_15m_wt)
    df_3m_wt = dfs.get("3m")
    if df_3m_wt is not None:
        df_3m_wt = _add_wt_crosses(df_3m_wt)

    # ── Precompute SWING zone SMC (1h / 4h / 1d) ──────────────────────────
    # Обновляем каждые N зонных баров: 1h→каждый бар, 4h→каждый, 1d→каждый
    # (300 баров lookback = ~12.5 суток для 1h, ~50 суток для 4h, ~10 месяцев для 1d)
    swing_zone_snaps: Dict[str, List] = {}
    for ztf in ["1h", "4h", "1d"]:
        df_z = dfs.get(ztf)
        if df_z is not None:
            swing_zone_snaps[ztf] = _precompute_zone_snapshots(df_z, refresh_every_n=1)

    # ── SWING: zone 1h/4h/1d → trigger 15m ───────────────────────────────
    if df_15m_wt is not None and len(df_15m_wt) > WARMUP_BARS + MAX_HOLD:
        in_trade = False
        for i in range(WARMUP_BARS, len(df_15m_wt) - MAX_HOLD, STEP_SWING):
            if in_trade:
                in_trade = False
                continue

            cur_time = df_15m_wt.index[i]
            df_trig  = df_15m_wt.iloc[max(0, i-200):i+1]

            # Lookup precomputed zone SMC
            smc_contexts: Dict[str, SMCContext] = {}
            for ztf, snaps in swing_zone_snaps.items():
                ctx = _lookup_zone_ctx(snaps, cur_time)
                if ctx is not None:
                    smc_contexts[ztf] = ctx

            if not smc_contexts:
                continue

            sig = detect_ote_signal(
                df_trigger=df_trig, symbol=symbol,
                smc_contexts=smc_contexts, trigger_tf="15m", shadow_mode=False,
                ote_zone_min_fib=cfg.ote_zone_min_fib,
                require_wt_in_obos=cfg.require_wt_in_obos,
            )
            if sig is None:
                continue

            # Post-фильтры по cfg (не встроены в detect_ote_signal для backward-compat)
            ptf = sig.data.get("primary_tf", "1h")
            if _TF_ORDER.get(ptf, 0) < _TF_ORDER.get(cfg.min_zone_tf, 0):
                continue   # primary TF слишком мелкий
            if cfg.choch_only and sig.data.get("is_bos", False):
                continue   # BOS не разрешён

            close = float(df_trig["close"].iloc[-1])
            atr   = float(df_trig["close"].rolling(ATR_PERIOD).std().iloc[-1]) * ATR_FACTOR
            if atr <= 0 or atr / close > 0.1:
                continue

            direction = sig.direction.value
            sl = (close - atr) if direction == "LONG" else (close + atr)
            tp = (close + atr * TP_R) if direction == "LONG" else (close - atr * TP_R)

            result, exit_price, r_mult = simulate_trade(df_15m_wt, i, direction, close, sl, tp)
            trades.append(OTETrade(
                symbol=symbol, mode="swing", direction=direction,
                entry_price=close, sl=sl, tp=tp, entry_bar=i,
                result=result, exit_price=exit_price, r_multiple=r_mult,
                confirmed_tfs=sig.data.get("confirmed_tfs", []),
                primary_tf=sig.data.get("primary_tf", ""),
                tight_ote=False,
                is_bos=sig.data.get("is_bos", False),
            ))
            in_trade = True

    # ── Precompute SCALP zone SMC (15m → обновлять каждые 20 3m-баров = 60 мин) ──
    scalp_zone_snaps: List = []
    df_15m_for_scalp = dfs.get("15m")
    if df_15m_for_scalp is not None:
        # refresh_every_n=20: обновляем каждые 20 3m-баров (1 час), достаточно для SMC
        scalp_zone_snaps = _precompute_zone_snapshots(df_15m_for_scalp, refresh_every_n=10)

    # ── SCALP: zone 15m → trigger 3m ──────────────────────────────────────
    if df_3m_wt is not None and len(df_3m_wt) > WARMUP_BARS + MAX_HOLD:
        in_trade = False
        for i in range(WARMUP_BARS, len(df_3m_wt) - MAX_HOLD, STEP_SCALP):
            if in_trade:
                in_trade = False
                continue

            cur_time = df_3m_wt.index[i]
            df_trig  = df_3m_wt.iloc[max(0, i-200):i+1]

            ctx = _lookup_zone_ctx(scalp_zone_snaps, cur_time)
            if ctx is None:
                continue

            sig = detect_ote_signal(
                df_trigger=df_trig, symbol=symbol,
                smc_contexts={"15m": ctx}, trigger_tf="3m", shadow_mode=False,
                zone_tf_priority=[("15m", 0)],   # scalp: zone=15m baseline
            )
            if sig is None:
                continue

            close = float(df_trig["close"].iloc[-1])
            atr   = float(df_trig["close"].rolling(ATR_PERIOD).std().iloc[-1]) * ATR_FACTOR
            if atr <= 0 or atr / close > 0.1:
                continue

            direction = sig.direction.value
            sl = (close - atr) if direction == "LONG" else (close + atr)
            tp = (close + atr * TP_R) if direction == "LONG" else (close - atr * TP_R)

            result, exit_price, r_mult = simulate_trade(df_3m_wt, i, direction, close, sl, tp)
            trades.append(OTETrade(
                symbol=symbol, mode="scalp", direction=direction,
                entry_price=close, sl=sl, tp=tp, entry_bar=i,
                result=result, exit_price=exit_price, r_multiple=r_mult,
                confirmed_tfs=sig.data.get("confirmed_tfs", []),
                primary_tf=sig.data.get("primary_tf", ""),
                tight_ote=sig.data.get("tight_ote", False),
                is_bos=sig.data.get("is_bos", False),
            ))
            in_trade = True

    return trades


# ─── Метрики ──────────────────────────────────────────────────────────────────

def calc_metrics(trades: List[OTETrade], days: int, label: str) -> dict:
    if not trades:
        return {"label": label, "count": 0}

    closed = [t for t in trades if t.result in ("WIN", "LOSS")]
    wins   = [t for t in closed if t.result == "WIN"]
    wr     = len(wins) / len(closed) * 100 if closed else 0

    rs = [t.r_multiple for t in closed]
    avg_r     = float(np.mean(rs)) if rs else 0
    sharpe    = float(np.mean(rs) / np.std(rs)) * np.sqrt(252) if len(rs) > 1 and np.std(rs) > 0 else 0

    # Просадка (equity curve, risk 1R per trade)
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = eq - peak
        max_dd = min(max_dd, dd)

    # Конфлюенция
    confluences = [t for t in trades if len(t.confirmed_tfs) >= 2]
    conf_pct    = len(confluences) / len(trades) * 100 if trades else 0
    triple      = [t for t in trades if len(t.confirmed_tfs) >= 3]
    tight_pct   = sum(1 for t in trades if t.tight_ote) / len(trades) * 100 if trades else 0
    bos_pct     = sum(1 for t in trades if t.is_bos) / len(trades) * 100 if trades else 0

    # Win rate по конфлюенции
    conf_wins = [t for t in confluences if t.result == "WIN"]
    conf_wr   = len(conf_wins) / len(confluences) * 100 if confluences else 0

    tight_trades = [t for t in trades if t.tight_ote and t.result in ("WIN","LOSS")]
    tight_wr     = sum(1 for t in tight_trades if t.result == "WIN") / len(tight_trades) * 100 if tight_trades else 0

    sigs_per_day = len(trades) / days

    return {
        "label":        label,
        "count":        len(trades),
        "closed":       len(closed),
        "wr":           round(wr, 1),
        "avg_r":        round(avg_r, 3),
        "sharpe":       round(sharpe, 2),
        "max_dd_r":     round(max_dd, 2),
        "sigs_per_day": round(sigs_per_day, 2),
        "conf_pct":     round(conf_pct, 1),
        "conf_wr":      round(conf_wr, 1),
        "triple_count": len(triple),
        "tight_pct":    round(tight_pct, 1),
        "tight_wr":     round(tight_wr, 1),
        "bos_pct":      round(bos_pct, 1),
    }


def print_metrics(m: dict):
    if m.get("count", 0) == 0:
        print(f"  {m['label']}: нет сделок")
        return

    wr_flag    = "✅" if m["wr"] >= 45 else ("⚠️" if m["wr"] >= 35 else "🔴")
    sharpe_flag= "✅" if m["sharpe"] >= 1.5 else ("⚠️" if m["sharpe"] >= 0.8 else "🔴")
    dd_flag    = "✅" if m["max_dd_r"] >= -5 else ("⚠️" if m["max_dd_r"] >= -10 else "🔴")
    avgr_flag  = "✅" if m["avg_r"] >= 0.3 else ("⚠️" if m["avg_r"] >= 0 else "🔴")

    print(f"\n  ── {m['label']} ──────────────────────")
    print(f"  Сделок всего:    {m['count']} ({m['sigs_per_day']}/день)")
    print(f"  Закрытых:        {m['closed']}")
    print(f"  Win Rate:        {m['wr']}%  {wr_flag}")
    print(f"  Avg R:           {m['avg_r']}  {avgr_flag}")
    print(f"  Sharpe:          {m['sharpe']}  {sharpe_flag}")
    print(f"  Max DD (R):      {m['max_dd_r']}  {dd_flag}")
    print(f"  Конфлюенция ≥2:  {m['conf_pct']}% сигналов  (WR={m['conf_wr']}%)")
    print(f"  Конфлюенция 3TF: {m['triple_count']} сигналов")
    print(f"  Tight OTE:       {m['tight_pct']}% сигналов  (WR={m['tight_wr']}%)")
    print(f"  BOS (не CHoCH):  {m['bos_pct']}%")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main(pairs: List[str], days: int):
    print(f"\n{'='*68}")
    print(f"  MTF OTE Backtest — {len(pairs)} пар / {days} дней  [СРАВНЕНИЕ КОНФИГОВ]")
    print(f"  SWING: 1h/4h/1d zone → 15m trigger")
    print(f"{'='*68}")

    exch  = ccxt_async.binance({"enableRateLimit": False})
    cache = OHLCVCache()

    # Загружаем данные один раз, запускаем бэктест для каждого конфига
    all_dfs: Dict[str, Dict[str, pd.DataFrame]] = {}

    for symbol in pairs:
        print(f"\n⏳ Загрузка {symbol}...", end=" ", flush=True)
        try:
            dfs_raw = await asyncio.gather(
                fetch_ohlcv(exch, symbol, "1d",  days + 30, cache),
                fetch_ohlcv(exch, symbol, "4h",  days + 30, cache),
                fetch_ohlcv(exch, symbol, "1h",  days + 30, cache),
                fetch_ohlcv(exch, symbol, "15m", days + 10, cache),
                return_exceptions=True,
            )
            dfs = {}
            for tf, df in zip(["1d","4h","1h","15m"], dfs_raw):
                if isinstance(df, Exception) or (isinstance(df, pd.DataFrame) and df.empty):
                    logger.warning("[%s] %s: нет данных", symbol, tf)
                else:
                    dfs[tf] = df

            if "15m" not in dfs:
                print("SKIP (нет 15m)")
                continue

            all_dfs[symbol] = dfs
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")

    await exch.close()

    # ── Запускаем все конфиги ─────────────────────────────────────────────
    config_results: List[Dict] = []

    for cfg in CONFIGS:
        print(f"\n{'─'*68}")
        print(f"  {cfg.label}")
        print(f"{'─'*68}")
        all_trades: List[OTETrade] = []

        for symbol, dfs in all_dfs.items():
            trades = backtest_pair(symbol, dfs, days, cfg=cfg)
            swing  = [t for t in trades if t.mode == "swing"]
            all_trades.extend(swing)
            print(f"  {symbol:<15} swing={len(swing)}")

        m = calc_metrics(all_trades, days * len(all_dfs), cfg.label)
        print_metrics(m)
        config_results.append(m)

    # ── Сравнительная таблица ─────────────────────────────────────────────
    print(f"\n{'='*68}")
    print("  СРАВНЕНИЕ КОНФИГОВ (SWING)")
    print(f"{'='*68}")
    header = f"  {'Конфиг':<38} {'Сделок':>6} {'WR%':>6} {'AvgR':>6} {'Sharpe':>7} {'MaxDD':>7}"
    print(header)
    print(f"  {'─'*64}")
    for m in config_results:
        if m.get("count", 0) == 0:
            print(f"  {m['label']:<38} {'нет данных':>6}")
            continue
        wr_f = "✅" if m["wr"] >= 45 else ("⚠️" if m["wr"] >= 40 else "🔴")
        print(
            f"  {m['label']:<38} {m['closed']:>6} {m['wr']:>5.1f}% {wr_f}"
            f" {m['avg_r']:>6.3f} {m['sharpe']:>7.2f} {m['max_dd_r']:>7.1f}R"
        )

    # ── Вердикт по конфигам ───────────────────────────────────────────────
    print(f"\n{'='*68}")
    print("  ВЕРДИКТ")
    print(f"{'='*68}")
    for m in config_results:
        if m.get("count", 0) < 10:
            print(f"  {m['label']}: ⚠️ мало данных ({m.get('count',0)} сделок)")
            continue
        wr = m.get("wr", 0)
        sh = m.get("sharpe", 0)
        dd = m.get("max_dd_r", 0)
        if wr >= 45 and sh >= 1.0 and dd >= -8:
            verdict = "✅ ДЕПЛОЙ: shadow→production"
        elif wr >= 40 and sh >= 0.5:
            verdict = "⚠️ ОСТОРОЖНО: ещё 2 недели shadow"
        else:
            verdict = "🔴 ОТКАЗ"
        print(f"  {m['label']}: {verdict}  (WR={wr}% Sharpe={sh} MaxDD={dd}R)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", nargs="+", default=None, help="Символы (без /USDT)")
    parser.add_argument("--days",  type=int, default=90, help="Период (дней)")
    args = parser.parse_args()

    pairs = [f"{p}/USDT" for p in args.pairs] if args.pairs else PAIRS
    asyncio.run(main(pairs, args.days))
