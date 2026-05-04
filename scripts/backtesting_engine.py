#!/usr/bin/env python3
"""
Backtesting Framework — тестирование стратегий на исторических данных.
Запуск: python scripts/backtesting_engine.py [--scenario quick_test]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import ccxt.async_support as ccxt_async
from core.infra.data_collector import RealTimeData
from core.indicators.indicators import calculate_trend, calculate_wt, get_trend_info, calculate_trend_strength
from core.signals.signal_checkers import (
    check_anomaly_signals, check_wt_signals,
    check_trend_signals, check_divergence_signals, check_pivot_signals,
)
from core.indicators.market_regime import MarketRegimeClassifier
from core.trading.trade_simulator import STATUS_TP, STATUS_SL, STATUS_TSL, STATUS_EXPIRED

logger = logging.getLogger(__name__)


def _ms_to_date_str(ts_ms: int) -> str:
    """Конвертирует Unix ms timestamp в строку YYYY-MM-DD (UTC)."""
    return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


def _trade_pnl(trade: "BacktestTrade", balance: float, config: "BacktestConfig") -> float:
    """DEV-33: P&L сделки с учётом leverage и комиссии (round-trip).

    Математика:
      margin        = balance × risk_per_trade_pct / 100
      position_size = margin × leverage
      gross_pnl     = position_size × profit_pct / 100
      commission    = position_size × commission_pct / 100 × 2  (entry + exit)
      net_pnl       = gross_pnl - commission

    Liquidation guard: потеря не может превысить margin (capital committed).
    """
    leverage = max(1, int(config.leverage))
    margin = balance * (config.risk_per_trade_pct / 100)
    position_size = margin * leverage
    gross_pnl = position_size * (trade.profit_pct / 100)
    commission = position_size * (config.commission_pct / 100) * 2  # round-trip
    net_pnl = gross_pnl - commission
    # Liquidation guard: убыток не может превысить вложенный margin
    if net_pnl < -margin:
        net_pnl = -margin
    return net_pnl


def _calc_smc_stats(trades: "List[BacktestTrade]") -> dict:
    """DEV-34: статистика SMC флагов по сделкам."""
    if not trades:
        return {}
    ob_trades  = [t for t in trades if t.smc_ob is True]
    fvg_trades = [t for t in trades if t.smc_fvg is True]
    ob_wins    = [t for t in ob_trades  if t.result == BacktestResult.WIN]
    fvg_wins   = [t for t in fvg_trades if t.result == BacktestResult.WIN]
    ob_fvg     = [t for t in trades if t.smc_ob is True and t.smc_fvg is True]
    ob_fvg_wins= [t for t in ob_fvg if t.result == BacktestResult.WIN]

    def _wr(wins, total):
        return round(len(wins) / len(total) * 100, 1) if total else 0.0

    def _avg_r(lst):
        import numpy as np
        return round(float(np.mean([t.r_multiple for t in lst])), 2) if lst else 0.0

    return {
        'ob_count':      len(ob_trades),
        'ob_wr':         _wr(ob_wins, ob_trades),
        'ob_avg_r':      _avg_r(ob_trades),
        'fvg_count':     len(fvg_trades),
        'fvg_wr':        _wr(fvg_wins, fvg_trades),
        'fvg_avg_r':     _avg_r(fvg_trades),
        'ob_fvg_count':  len(ob_fvg),
        'ob_fvg_wr':     _wr(ob_fvg_wins, ob_fvg),
        'ob_fvg_avg_r':  _avg_r(ob_fvg),
    }


def _week_start_ms(ts_ms: int) -> int:
    """Возвращает timestamp начала недели (Пн 00:00 UTC) для ts_ms."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    week_start = dt - timedelta(days=dt.weekday())
    return int(week_start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


class BacktestResult(Enum):
    """Результаты бэктестинга"""
    WIN = "WIN"
    LOSS = "LOSS"
    EXPIRED = "EXPIRED"


@dataclass
class BacktestTrade:
    """Результат одной сделки в бэктестинге"""
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    result: BacktestResult
    r_multiple: float
    profit_pct: float
    duration_hours: float
    signal_type: str
    regime: Optional[str] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    max_r_possible: Optional[float] = None
    captured_r_pct: Optional[float] = None
    smc_ob: Optional[bool] = None   # DEV-34: Bull/Bear OB был у цены входа
    smc_fvg: Optional[bool] = None  # DEV-34: незаполненный FVG был у цены входа


@dataclass
class BacktestConfig:
    """Конфигурация бэктестинга"""
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    start_date: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_date: datetime = datetime(2024, 12, 31, tzinfo=timezone.utc)
    initial_balance: float = 10000.0
    risk_per_trade_pct: float = 1.0
    max_duration_hours: int = 48
    use_tsl: bool = True
    tsl_activation_r: float = 1.0
    commission_pct: float = 0.1
    leverage: int = 1             # DEV-33: плечо (1=спот, 2/3/5=фьючерс). Риск остаётся risk_per_trade_pct; leverage увеличивает позицию и комиссию
    use_htf_filter: bool = True   # фильтр по HTF тренду
    use_pivot_filter: bool = True  # фильтр по weekly pivot PP
    htf_timeframe: str = "4h"    # ТФ для HTF фильтра
    atr_period: int = 14          # период ATR для расчёта SL (43 = как в живом боте)
    atr_factor: float = 1.5       # множитель ATR для SL (1.0 = как в живом боте)
    use_pivot_tp: bool = False     # TP = ближайший pivot level вместо фиксированного 2R
    pivot_tp_min_r: float = 1.0   # минимальный R до pivot (иначе пропустить сигнал)
    # --- Параметрический конструктор стратегий ---
    use_wt: bool = True           # включить WT crossover детектор
    use_divergence: bool = True   # включить дивергенции
    div_regular: bool = True      # Regular div: инд. HL/LH при цене LL/HH
    div_hidden: bool = True       # Hidden div: инд. LL/HH при цене HL/LH
    use_anomaly: bool = True      # включить аномалии объёма
    use_trend: bool = True        # включить трендовые сигналы
    use_fvg: bool = False         # требовать FVG подтверждение (detect_fvg)
    fvg_timeframe: str = "15m"   # TF для FVG детектора (3m/15m)
    wt_ob: float = 60.0           # порог перекупленности (OB) для фильтра WT
    wt_os: float = -60.0          # порог перепроданности (OS) для фильтра WT
    pivot_touch_pct: float = 0.5  # допуск касания пивота, %
    tp_type: str = "fixed_2r"     # "fixed_2r" | "next_pivot" | "tsl_only"
    tp_r: float = 2.0             # TP в R-кратных (2 = 2R, 3 = 3R)
    tsl_lag_bars: int = 0         # задержка TSL в барах (0 = без задержки)
    use_fvg_boost: bool = False   # FVG как усилитель силы сигнала (не фильтр)
    use_pivot_boost: bool = False # касание pivot-уровня как усилитель силы сигнала
    use_reentry: bool = False     # перезаход после SL по дивергенции
    reentry_lookback: int = 10    # сколько баров после SL искать перезаход
    # --- DEV-34: SMC фильтр ---
    use_smc: bool = False         # вычислять SMC контекст (требуется для smc_require_*)
    smc_require_ob: bool = False  # LONG требует Bull OB у цены, SHORT — Bear OB
    smc_require_fvg: bool = False # LONG требует незаполненный Bull FVG, SHORT — Bear FVG
    smc_ob_tf: str = "15m"        # ТФ для OB (будущее: 1h, 4h; сейчас = основной TF)
    smc_ob_pairs: list = None     # per-asset OB-фильтр: список символов где smc_require_ob активен.
                                  # None = применять ко всем. ["ETH/USDT","BTC/USDT"] = только топ-5.
    # --- DEV-35: источник данных ---
    data_source: str = "bingx"    # "bingx" | "cryptocom" | "binance". Binance: с 2017, максимальная история
    # --- Стратегия ---
    strategy: str = "default"     # "default" | "confluence_scanner" | любое имя из registry
    strategy_config: dict = None  # параметры стратегии (min_strength и т.д.)
    use_confluence: bool = True   # включить confluence_scanner во все стратегии
    train_pct: float = 0.7        # доля данных для in-sample (0.7 = 70%)


class BacktestingEngine:
    """
    Движок для бэктестинга стратегий на исторических данных
    """

    def __init__(self, config: BacktestConfig, shared_exchange=None):
        self.config = config
        self.data_collector = RealTimeData()
        # DEV-35: выбираем биржу по data_source
        if config.data_source == "cryptocom":
            # Crypto.com: спот, история с 2018
            self._swap_exchange = ccxt_async.cryptocom({'enableRateLimit': True})
            self._owned_exchange = True
        elif config.data_source == "binance":
            # Binance: спот, максимальная история (BTC с 2017, большинство альтов с 2019-2021)
            self._swap_exchange = ccxt_async.binance({'enableRateLimit': True})
            self._owned_exchange = True
        else:
            # BingX: фьючерс-swap (текущее поведение)
            self._owned_exchange = shared_exchange is None
            self._swap_exchange = shared_exchange or ccxt_async.bingx({
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'},
            })
        self.trades: List[BacktestTrade] = []
        self.balance = config.initial_balance
        self.current_balance = config.initial_balance

    def _to_swap_symbol(self, symbol: str) -> str:
        """Конвертирует 'BTC/USDT' → 'BTC/USDT:USDT' для фьючерсов BingX."""
        if ':' not in symbol:
            base = symbol.split('/')[1] if '/' in symbol else 'USDT'
            return f"{symbol}:{base}"
        return symbol

    def _to_source_symbol(self, symbol: str) -> str:
        """DEV-35: возвращает символ в формате нужной биржи.
        BingX   → 'BTC/USDT:USDT' (swap/perpetual)
        Binance → 'BTC/USDT'      (spot)
        Crypto.com → 'BTC/USDT'  (spot)
        """
        if self.config.data_source in ("cryptocom", "binance"):
            return symbol.split(':')[0]  # убираем ':USDT' суффикс если есть
        return self._to_swap_symbol(symbol)

    def _cache_symbol_key(self, symbol: str) -> str:
        """DEV-35: ключ символа для кэша — с префиксом источника во избежание коллизий.
        Пример: 'bingx:BTC/USDT:USDT', 'cryptocom:BTC/USDT'
        """
        return f"{self.config.data_source}:{self._to_source_symbol(symbol)}"

    async def _fetch_ohlcv_swap(self, symbol: str, timeframe: str, since: int, limit: int = 1000) -> Optional[pd.DataFrame]:
        """Загружает OHLCV пачками через configured exchange, начиная с since.
        DEV-32: сначала проверяет SQLite кэш, докачивает только недостающее.
        DEV-35: использует _to_source_symbol() + _cache_symbol_key() для поддержки Crypto.com.
        """
        source_symbol = self._to_source_symbol(symbol)   # DEV-35: BingX swap или Crypto.com spot
        cache_key = self._cache_symbol_key(symbol)        # DEV-35: с префиксом источника
        end_ms = int(self.config.end_date.timestamp() * 1000)

        # ── DEV-32: SQLite кэш ──────────────────────────────────────────────
        try:
            from scripts.ohlcv_cache import get_cache
            cache = get_cache()
            c_min, c_max = cache.get_coverage(cache_key, timeframe)

            if c_min is not None and c_min <= since and c_max is not None and c_max >= end_ms:
                # Полное покрытие — API не нужен
                cached_df = cache.read(cache_key, timeframe, since, end_ms)
                if cached_df is not None:
                    logger.info("[cache] HIT %s %s (%d bars)", cache_key, timeframe, len(cached_df))
                    return cached_df

            # Инкрементальное обновление: есть данные, но хвост устарел
            fetch_since = since
            if c_min is not None and c_min <= since and c_max is not None and c_max < end_ms:
                fetch_since = c_max + 1  # докачиваем только пропущенный хвост
                logger.info(
                    "[cache] PARTIAL %s %s: cached to %s, fetching tail",
                    cache_key, timeframe,
                    _ms_to_date_str(c_max),
                )
        except Exception as _e:
            logger.debug("[cache] unavailable: %s", _e)
            cache = None
            fetch_since = since
        else:
            pass  # fetch_since уже выставлен выше
        # ── /DEV-32 ─────────────────────────────────────────────────────────

        all_data = []
        current_since = fetch_since

        _retries = 0
        _max_retries = 3
        while True:
            try:
                candles = await self._swap_exchange.fetch_ohlcv(source_symbol, timeframe, since=current_since, limit=limit)
                _retries = 0  # сброс счётчика при успехе
            except Exception as e:
                err_str = str(e)
                # BingX rate limit (100410) — ждём и повторяем (только для BingX)
                if self.config.data_source == "bingx" and "100410" in err_str and _retries < _max_retries:
                    _retries += 1
                    wait_sec = 5 * _retries
                    logger.warning(f"Rate limit 100410 {source_symbol}, retry {_retries}/{_max_retries} через {wait_sec}s")
                    await asyncio.sleep(wait_sec)
                    continue
                logger.error(f"fetch_ohlcv error {source_symbol} {timeframe}: {e}")
                break
            if not candles:
                break
            df_batch = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
            for c in ["open", "high", "low", "close", "volume"]:
                df_batch[c] = pd.to_numeric(df_batch[c], errors="coerce")
            df_batch = df_batch[df_batch['time'] <= end_ms]
            if df_batch.empty:
                break
            all_data.append(df_batch)
            last_time = int(candles[-1][0])
            if last_time >= end_ms or len(candles) < limit:
                break
            current_since = last_time + 1
            await asyncio.sleep(0.15)

        if not all_data:
            return None
        df_new = pd.concat(all_data, ignore_index=True).drop_duplicates(subset=['time']).sort_values('time')
        df_new = df_new.reset_index(drop=True)

        # ── DEV-32: сохраняем в кэш + мержим с ранее закэшированным хвостом ─
        try:
            if cache is not None:
                cache.save(cache_key, timeframe, df_new)
                # Если была частичная загрузка (fetch_since > since) — дочитать голову из кэша
                if fetch_since > since:
                    head = cache.read(cache_key, timeframe, since, fetch_since - 1)
                    if head is not None and not head.empty:
                        df_new = pd.concat([head, df_new], ignore_index=True) \
                                   .drop_duplicates(subset=["time"]).sort_values("time") \
                                   .reset_index(drop=True)
        except Exception as _e:
            logger.debug("[cache] save failed: %s", _e)
        # ── /DEV-32 ──────────────────────────────────────────────────────────

        return df_new

    async def _load_htf_df(self, htf: Optional[str] = None) -> pd.DataFrame:
        """Загружает HTF OHLCV через swap и вычисляет SuperTrend для фильтрации направления."""
        htf = htf or self.config.htf_timeframe
        since = int(self.config.start_date.timestamp() * 1000)
        df = await self._fetch_ohlcv_swap(self.config.symbol, htf, since, limit=500)
        if df is None or df.empty:
            return pd.DataFrame()
        df = calculate_trend(df)
        return df.reset_index(drop=True)

    async def _load_ltf_df(self) -> pd.DataFrame:
        """Загружает LTF OHLCV (15m/3m) для FVG детектора."""
        since = int(self.config.start_date.timestamp() * 1000)
        df = await self._fetch_ohlcv_swap(self.config.symbol, self.config.fvg_timeframe, since, limit=1000)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.reset_index(drop=True)

    def _compute_weekly_pp(self, df: pd.DataFrame) -> Dict[int, float]:
        """
        Вычисляет weekly Pivot Point из основного OHLCV без API-вызовов.
        PP недели N = (high + low + close) прошлой недели / 3.
        Возвращает {week_start_ms → PP}.
        """
        df_t = df.copy()
        df_t.index = pd.to_datetime(df_t['time'], unit='ms', utc=True)
        weekly = df_t.resample('W-MON', closed='left', label='left').agg(
            {'high': 'max', 'low': 'min', 'close': 'last'}
        ).dropna()
        result: Dict[int, float] = {}
        for i in range(1, len(weekly)):
            week_start_ms = int(weekly.index[i].timestamp() * 1000)
            prev = weekly.iloc[i - 1]
            result[week_start_ms] = (prev['high'] + prev['low'] + prev['close']) / 3
        return result

    def _compute_full_pivots(self, df: pd.DataFrame) -> Dict[int, Dict[str, float]]:
        """
        Вычисляет полные weekly pivot levels из OHLCV.
        Возвращает {week_start_ms: {PP, R1, R2, R3, S1, S2, S3}}.
        PP = (H+L+C)/3 предыдущей недели.
        """
        df_t = df.copy()
        df_t.index = pd.to_datetime(df_t['time'], unit='ms', utc=True)
        weekly = df_t.resample('W-MON', closed='left', label='left').agg(
            {'high': 'max', 'low': 'min', 'close': 'last'}
        ).dropna()
        result: Dict[int, Dict[str, float]] = {}
        for i in range(1, len(weekly)):
            week_start_ms = int(weekly.index[i].timestamp() * 1000)
            h, l, c = weekly.iloc[i - 1]['high'], weekly.iloc[i - 1]['low'], weekly.iloc[i - 1]['close']
            pp = (h + l + c) / 3.0
            result[week_start_ms] = {
                'PP': pp,
                'R1': 2 * pp - l,
                'R2': pp + (h - l),
                'R3': h + 2 * (pp - l),
                'S1': 2 * pp - h,
                'S2': pp - (h - l),
                'S3': l - 2 * (h - pp),
            }
        return result

    async def load_historical_data(self) -> pd.DataFrame:
        """Загружает исторические OHLCV данные через BingX swap (поддерживает since)."""
        logger.info(f"Загрузка {self.config.symbol} {self.config.timeframe} "
                    f"{self.config.start_date.date()} → {self.config.end_date.date()}")
        since = int(self.config.start_date.timestamp() * 1000)
        df = await self._fetch_ohlcv_swap(self.config.symbol, self.config.timeframe, since)
        if df is None or df.empty:
            raise ValueError("Не удалось загрузить исторические данные")
        logger.info(f"Загружено {len(df)} свечей")
        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитывает все индикаторы для DataFrame
        """
        logger.info("Расчет индикаторов...")

        # Тренд и TSL
        df = calculate_trend(df)
        df = calculate_trend_strength(df)

        # WT индикатор
        df = calculate_wt(df)

        # Добавляем дополнительные колонки для анализа
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(20).std() * np.sqrt(365)  # Годовая волатильность

        logger.info("Индикаторы рассчитаны")
        return df

    def _detect_mtf_wt_pivot(
        self,
        context: pd.DataFrame,
        bar_time: int,
        full_pivots: Dict[int, Dict[str, float]],
    ) -> List[Dict[str, Any]]:
        """
        MTF WT+Pivot стратегия (упрощённая версия для бэктеста на 1h данных):
        1. Цена касается weekly S/R уровня (±0.5%)
        2. WT 1h crossover в OB/OS зоне (совпадающее с уровнем направление)
        3. Возвращает сигнал с tp_price = следующий pivot level
        """
        from core.indicators.indicators import calculate_wt

        pivots = full_pivots.get(_week_start_ms(bar_time))
        if not pivots:
            return []

        price = float(context['close'].iloc[-1])
        TOUCH_PCT = 0.005  # ±0.5%

        # Находим ближайший уровень и определяем направление
        direction = None
        touched_level_name = None
        tp_price = None

        s_levels = [('S3', 'S2'), ('S2', 'S1'), ('S1', 'PP')]
        r_levels = [('R3', 'R2'), ('R2', 'R1'), ('R1', 'PP')]

        for level_name, tp_name in s_levels:
            level = pivots.get(level_name)
            if level and abs(price - level) / level <= TOUCH_PCT:
                direction = 'LONG'
                touched_level_name = level_name
                tp_price = pivots.get(tp_name)
                break

        if direction is None:
            for level_name, tp_name in r_levels:
                level = pivots.get(level_name)
                if level and abs(price - level) / level <= TOUCH_PCT:
                    direction = 'SHORT'
                    touched_level_name = level_name
                    tp_price = pivots.get(tp_name)
                    break

        if direction is None or tp_price is None:
            return []

        # WT crossover подтверждение
        try:
            wt_df = calculate_wt(context.copy())
        except Exception:
            return []
        if len(wt_df) < 3:
            return []

        wt1 = wt_df['wt1']
        wt2 = wt_df['wt2']
        OB, OS = 60, -60

        wt1_prev, wt2_prev = float(wt1.iloc[-2]), float(wt2.iloc[-2])
        wt1_last, wt2_last = float(wt1.iloc[-1]), float(wt2.iloc[-1])

        if direction == 'LONG':
            cross_up = wt1_prev < wt2_prev and wt1_last >= wt2_last
            if not (cross_up and wt1_last < OS):
                return []
        else:
            cross_down = wt1_prev > wt2_prev and wt1_last <= wt2_last
            if not (cross_down and wt1_last > OB):
                return []

        return [{
            'direction': direction,
            'price': price,
            'touched_level': touched_level_name,
            'tp_price': tp_price,
            'strength': 75,
            'type': 'mtf_wt_pivot',
        }]

    async def detect_signals(
        self,
        df: pd.DataFrame,
        df_htf: pd.DataFrame,
        weekly_pp: Dict[int, float],
        full_pivots: Optional[Dict[int, Dict[str, float]]] = None,
        df_ltf: Optional[pd.DataFrame] = None,
    ) -> List[Dict[str, Any]]:
        """
        Обнаруживает торговые сигналы на исторических данных.
        Скользящее окно 200 баров, шаг STEP свечей.
        Фильтры направления:
          - HTF trend (4h): LONG только при trend=+1, SHORT только при trend=-1
          - Weekly PP: LONG только выше PP, SHORT только ниже PP
        """
        signals: List[Dict[str, Any]] = []
        symbol = self.config.symbol
        logger.info("Поиск торговых сигналов (скользящее окно 200 баров)...")

        WINDOW = 200
        STEP = 1        # каждую свечу; увеличь до 3-5 для скорости
        COOLDOWN = 10   # минимум свечей между сигналами одного типа+направления
        GLOBAL_CD = 10  # минимум свечей между любыми сигналами
        MIN_STRENGTH = 60  # порог силы сигнала (как в реальном боте)

        # LTF данные для FVG детектора
        fvg_times = np.array(df_ltf['time']) if df_ltf is not None and not df_ltf.empty else np.array([])

        # Предвычисляем массив HTF-времён для бинарного поиска
        htf_times = df_htf['time'].values if not df_htf.empty else np.array([])
        htf_trends = df_htf['trend'].values if not df_htf.empty else np.array([])

        last_signal_bar: Dict[str, int] = {}
        last_any_signal_bar: int = -GLOBAL_CD

        # DEV-34: импорт analyze_smc один раз
        _analyze_smc = None
        if self.config.use_smc:
            try:
                from core.smc import analyze_smc as _analyze_smc
            except Exception as _e:
                logger.warning("[DEV-34] SMC недоступен: %s — use_smc игнорируется", _e)

        for i in range(WINDOW, len(df), STEP):
            context = df.iloc[i - WINDOW:i].copy().reset_index(drop=True)
            current_bar = df.iloc[i - 1]
            bar_time = int(current_bar['time'])
            signal_price = float(current_bar['close'])

            # DEV-34: SMC анализ текущего окна (один раз за бар, переиспользуется всеми сигналами)
            smc_ctx = None
            if _analyze_smc is not None:
                try:
                    smc_ctx = _analyze_smc(context)
                except Exception:
                    pass

            # HTF trend: последний 4h-бар ≤ bar_time
            htf_trend = None
            if self.config.use_htf_filter and len(htf_times) > 0:
                idx = int(np.searchsorted(htf_times, bar_time, side='right')) - 1
                if 0 <= idx < len(htf_trends):
                    htf_trend = int(htf_trends[idx])

            # Weekly PP для текущей свечи
            pp = None
            if self.config.use_pivot_filter:
                pp = weekly_pp.get(_week_start_ms(bar_time))

            checkers = []
            if self.config.use_anomaly:
                checkers.append(check_anomaly_signals(symbol, context))
            if self.config.use_wt:
                checkers.append(check_wt_signals(symbol, context))
            if self.config.use_trend:
                checkers.append(check_trend_signals(symbol, context))
            if self.config.use_divergence:
                checkers.append(check_divergence_signals(symbol, context))
            checkers.append(check_pivot_signals(symbol, context))

            for coro in checkers:
                try:
                    sig_list = await coro
                except Exception as e:
                    logger.debug(f"Ошибка сигнального чекера: {e}")
                    continue

                for sig in sig_list:
                    if sig.strength < MIN_STRENGTH:
                        continue
                    if i - last_any_signal_bar < GLOBAL_CD:
                        continue

                    direction_str = sig.direction.value
                    sig_type_str = sig.signal_type.value

                    # Фильтр 1: HTF trend
                    if htf_trend is not None:
                        if direction_str == 'LONG' and htf_trend < 0:
                            continue  # HTF DOWN → пропускаем LONG
                        if direction_str == 'SHORT' and htf_trend > 0:
                            continue  # HTF UP → пропускаем SHORT

                    # Фильтр 2: Weekly pivot PP
                    if pp is not None:
                        if direction_str == 'LONG' and signal_price < pp:
                            continue  # Ниже weekly PP → не LONG
                        if direction_str == 'SHORT' and signal_price > pp:
                            continue  # Выше weekly PP → не SHORT

                    # Фильтр 3: WT OB/OS зона — check_wt_signals уже фильтрует внутри
                    # (wt1_last < os_ для LONG, wt1_last > ob для SHORT)
                    # Дополнительный фильтр по wt_ob/wt_os используется только если
                    # значения строже дефолта (60/-60), тогда берём из sig.data
                    if sig_type_str == 'wt_signal' and sig.data:
                        wt1_val = sig.data.get('wt1', 0)
                        if direction_str == 'LONG' and wt1_val > self.config.wt_os:
                            continue
                        if direction_str == 'SHORT' and wt1_val < self.config.wt_ob:
                            continue

                    # Фильтр 4: тип дивергенции (regular / hidden)
                    if sig_type_str == 'divergence':
                        div_type = sig.data.get('divergence_type', '') if sig.data else ''
                        is_hidden = 'hidden' in div_type
                        if is_hidden and not self.config.div_hidden:
                            continue
                        if not is_hidden and not self.config.div_regular:
                            continue

                    # Фильтр 5: FVG подтверждение на LTF (опциональный)
                    if self.config.use_fvg and len(fvg_times) > 0:
                        from core.indicators.indicators import detect_fvg
                        ltf_idx = int(np.searchsorted(fvg_times, bar_time, side='right')) - 1
                        if ltf_idx >= 3 and df_ltf is not None:
                            context_fvg = df_ltf.iloc[ltf_idx - 4:ltf_idx + 1]
                            fvg_type, _ = detect_fvg(context_fvg)
                            if fvg_type is None:
                                continue
                            if direction_str == 'LONG' and fvg_type != 'BULL':
                                continue
                            if direction_str == 'SHORT' and fvg_type != 'BEAR':
                                continue
                        else:
                            continue  # недостаточно LTF данных

                    # Фильтр 6: SMC — Order Block + FVG (DEV-34)
                    _smc_ob_active = False
                    _smc_fvg_active = False
                    if self.config.use_smc and smc_ctx is not None:
                        is_long_sig = direction_str == 'LONG'
                        ob = smc_ctx.nearest_bull_ob if is_long_sig else smc_ctx.nearest_bear_ob
                        fvg = smc_ctx.nearest_bull_fvg if is_long_sig else smc_ctx.nearest_bear_fvg
                        _smc_ob_active = ob is not None and (ob.bottom * 0.995 <= signal_price <= ob.top * 1.005)
                        _smc_fvg_active = fvg is not None
                        # per-asset OB: фильтр применяется только если символ в smc_ob_pairs (или список пустой)
                        _ob_pairs = self.config.smc_ob_pairs
                        _ob_pair_match = (_ob_pairs is None) or (self.config.symbol in _ob_pairs)
                        if self.config.smc_require_ob and _ob_pair_match and not _smc_ob_active:
                            continue
                        if self.config.smc_require_fvg and not _smc_fvg_active:
                            continue

                    key = f"{sig_type_str}_{direction_str}"
                    if i - last_signal_bar.get(key, -COOLDOWN) < COOLDOWN:
                        continue

                    signal_strength = sig.strength

                    # Усилитель 1: FVG на LTF (не фильтр, а бонус к силе)
                    if self.config.use_fvg_boost and len(fvg_times) > 0:
                        from core.indicators.indicators import detect_fvg
                        ltf_idx = int(np.searchsorted(fvg_times, bar_time, side='right')) - 1
                        if ltf_idx >= 3 and df_ltf is not None:
                            context_fvg = df_ltf.iloc[ltf_idx - 4:ltf_idx + 1]
                            fvg_type, _ = detect_fvg(context_fvg)
                            if fvg_type == 'BULL' and direction_str == 'LONG':
                                signal_strength = min(signal_strength + 15, 100)
                            elif fvg_type == 'BEAR' and direction_str == 'SHORT':
                                signal_strength = min(signal_strength + 15, 100)

                    # Усилитель 2: касание pivot-уровня
                    if self.config.use_pivot_boost and full_pivots:
                        week_pivots = full_pivots.get(_week_start_ms(bar_time))
                        if week_pivots:
                            touch_pct = self.config.pivot_touch_pct / 100
                            for level_val in week_pivots.values():
                                if abs(signal_price - level_val) / level_val <= touch_pct:
                                    signal_strength = min(signal_strength + 10, 100)
                                    break

                    last_signal_bar[key] = i
                    last_any_signal_bar = i
                    signals.append({
                        'timestamp': bar_time,
                        'bar_idx': i - 1,
                        'type': sig_type_str,
                        'direction': direction_str,
                        'price': signal_price,
                        'strength': signal_strength,
                        'smc_ob': _smc_ob_active,
                        'smc_fvg': _smc_fvg_active,
                    })

            # Confluence Scanner детектор (всегда, если use_confluence=True)
            if self.config.use_confluence:
                try:
                    from core.confluence.confluence_scanner import scan_confluence
                    from core.signals.signal_models import SignalDirection as _SD
                    _pivots_flat = {}
                    if full_pivots:
                        week_key = _week_start_ms(bar_time)
                        _pivots_flat = full_pivots.get(week_key, {})
                    _conf_cache = {f"{symbol}_1D": _pivots_flat, f"{symbol}_1W": _pivots_flat}
                    _cfg_obj = type("_C", (), {"get": lambda self, k, d=None: d})()
                    for csig in scan_confluence(symbol, context, context, _conf_cache, cfg=_cfg_obj):
                        key = f"confluence_{csig.direction.value}"
                        if i - last_signal_bar.get(key, -COOLDOWN) < COOLDOWN:
                            continue
                        if i - last_any_signal_bar < GLOBAL_CD:
                            continue
                        # HTF / PP фильтры
                        dir_str = csig.direction.value
                        if htf_trend is not None:
                            if dir_str == "LONG" and htf_trend < 0:
                                continue
                            if dir_str == "SHORT" and htf_trend > 0:
                                continue
                        if pp is not None:
                            if dir_str == "LONG" and signal_price < pp:
                                continue
                            if dir_str == "SHORT" and signal_price > pp:
                                continue
                        last_signal_bar[key] = i
                        last_any_signal_bar = i
                        signals.append({
                            'timestamp': bar_time,
                            'bar_idx': i - 1,
                            'type': 'confluence',
                            'direction': dir_str,
                            'price': signal_price,
                            'strength': csig.strength,
                            'confluence_data': csig.data,
                        })
                except Exception as _ce:
                    logger.debug("confluence_scanner detect error: %s", _ce)

            # MTF WT+Pivot детектор (только при use_pivot_tp)
            if self.config.use_pivot_tp and full_pivots:
                mtf_sigs = self._detect_mtf_wt_pivot(context, bar_time, full_pivots)
                for ms in mtf_sigs:
                    key = f"mtf_wt_pivot_{ms['direction']}"
                    if i - last_signal_bar.get(key, -COOLDOWN) < COOLDOWN:
                        continue
                    if i - last_any_signal_bar < GLOBAL_CD:
                        continue
                    last_signal_bar[key] = i
                    last_any_signal_bar = i
                    signals.append({
                        'timestamp': bar_time,
                        'bar_idx': i - 1,
                        'type': ms['type'],
                        'direction': ms['direction'],
                        'price': ms['price'],
                        'strength': ms['strength'],
                        'tp_price': ms.get('tp_price'),
                        'touched_level': ms.get('touched_level'),
                    })

        logger.info(f"Найдено {len(signals)} сигналов")
        return signals

    def simulate_trade_with_tsl(self, signal: Dict[str, Any], df: pd.DataFrame,
                               entry_idx: int) -> Optional[BacktestTrade]:
        """
        Симулирует сделку с TSL на исторических данных.
        SL = ATR(14) × 1.5 от точки входа. TP = 2R.
        """
        direction = signal['direction']
        entry_price = signal['price']
        entry_time = datetime.fromtimestamp(signal['timestamp'] / 1000, tz=timezone.utc)

        # ATR для расчёта SL (период и множитель из конфига)
        atr_window = df.iloc[max(0, entry_idx - self.config.atr_period):entry_idx + 1]
        if len(atr_window) >= 2:
            high_low = atr_window['high'] - atr_window['low']
            high_pc = (atr_window['high'] - atr_window['close'].shift(1)).abs()
            low_pc = (atr_window['low'] - atr_window['close'].shift(1)).abs()
            tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
            atr = tr.mean()
        else:
            atr = entry_price * 0.01  # fallback 1%

        atr_mult = self.config.atr_factor
        sl_distance = atr * atr_mult
        stop_loss_distance_pct = sl_distance / entry_price * 100

        if direction == 'LONG':
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + sl_distance * self.config.tp_r
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - sl_distance * self.config.tp_r

        # TP режим по tp_type
        tp_type = self.config.tp_type
        if tp_type == 'next_pivot' or self.config.use_pivot_tp:
            pivot_tp = signal.get('tp_price')
            if pivot_tp:
                pivot_r = abs(pivot_tp - entry_price) / sl_distance if sl_distance > 0 else 0
                if pivot_r >= self.config.pivot_tp_min_r:
                    take_profit = pivot_tp
        elif tp_type == 'tsl_only':
            # Только TSL — фиксированного TP нет; TSL активируется сразу
            take_profit = None

        # Симулируем движение цены
        # При tsl_only TSL активен сразу (активация при любой прибыли)
        tsl_active = (self.config.tp_type == 'tsl_only')
        tsl_level = stop_loss
        max_price = entry_price
        min_price = entry_price

        # Для TSL lag: хранит последние N значений TSL
        from collections import deque
        tsl_lag = self.config.tsl_lag_bars
        tsl_history: deque = deque(maxlen=max(tsl_lag + 1, 1))

        for i in range(entry_idx + 1, min(len(df), entry_idx + self.config.max_duration_hours)):
            current_bar = df.iloc[i]
            current_time = datetime.fromtimestamp(current_bar['time'] / 1000, tz=timezone.utc)

            high = current_bar['high']
            low = current_bar['low']
            close = current_bar['close']

            # Обновляем экстремумы
            max_price = max(max_price, high)
            min_price = min(min_price, low)

            # Проверяем активацию TSL
            if not tsl_active:
                current_profit = (close - entry_price) / entry_price * 100 if direction == 'LONG' else (entry_price - close) / entry_price * 100
                if current_profit >= self.config.tsl_activation_r * stop_loss_distance_pct:
                    tsl_active = True
                    # Получаем текущий TSL из тренда
                    context_df = df.iloc[max(0, i-50):i+1]
                    trend_df = calculate_trend(context_df)
                    trend_info = get_trend_info(trend_df)
                    if trend_info and trend_info['tsl']:
                        tsl_level = trend_info['tsl']

            # Обновляем TSL если активен
            if tsl_active and self.config.use_tsl:
                context_df = df.iloc[max(0, i-50):i+1]
                trend_df = calculate_trend(context_df)
                trend_info = get_trend_info(trend_df)
                if trend_info and trend_info['tsl']:
                    current_tsl = trend_info['tsl']
                    tsl_history.append(current_tsl)
                    # Используем TSL с lag N баров назад
                    if tsl_lag > 0 and len(tsl_history) > tsl_lag:
                        tsl_level = tsl_history[0]  # самый старый в буфере
                    else:
                        tsl_level = current_tsl

            # Проверяем выходы
            exit_reason = None
            exit_price = None

            if direction == 'LONG':
                # Проверяем SL
                if low <= stop_loss:
                    exit_reason = BacktestResult.LOSS
                    exit_price = stop_loss
                # Проверяем TSL
                elif tsl_active and low <= tsl_level:
                    exit_price = tsl_level
                    exit_reason = BacktestResult.WIN if exit_price > entry_price else BacktestResult.LOSS
                # Проверяем TP
                elif take_profit is not None and high >= take_profit:
                    exit_reason = BacktestResult.WIN
                    exit_price = take_profit
            else:  # SHORT
                # Проверяем SL
                if high >= stop_loss:
                    exit_reason = BacktestResult.LOSS
                    exit_price = stop_loss
                # Проверяем TSL
                elif tsl_active and high >= tsl_level:
                    exit_price = tsl_level
                    exit_reason = BacktestResult.WIN if exit_price < entry_price else BacktestResult.LOSS
                # Проверяем TP
                elif take_profit is not None and low <= take_profit:
                    exit_reason = BacktestResult.WIN
                    exit_price = take_profit

            if exit_reason:
                # Расчет метрик
                profit_pct = (exit_price - entry_price) / entry_price * 100 if direction == 'LONG' else (entry_price - exit_price) / entry_price * 100
                r_multiple = profit_pct / stop_loss_distance_pct
                duration_hours = (current_time - entry_time).total_seconds() / 3600

                # MFE расчет
                if direction == 'LONG':
                    max_r_possible = (max_price - entry_price) / (entry_price - stop_loss) if stop_loss < entry_price else 0
                else:
                    max_r_possible = (entry_price - min_price) / (stop_loss - entry_price) if stop_loss > entry_price else 0

                captured_r_pct = (r_multiple / max_r_possible * 100) if max_r_possible > 0 else 0

                return BacktestTrade(
                    symbol=self.config.symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    entry_time=entry_time,
                    exit_time=current_time,
                    result=exit_reason,
                    r_multiple=round(r_multiple, 2),
                    profit_pct=round(profit_pct, 2),
                    duration_hours=round(duration_hours, 1),
                    signal_type=signal['type'],
                    max_price=max_price,
                    min_price=min_price,
                    max_r_possible=round(max_r_possible, 2) if max_r_possible else None,
                    captured_r_pct=round(captured_r_pct, 1) if captured_r_pct else None,
                    smc_ob=signal.get('smc_ob'),
                    smc_fvg=signal.get('smc_fvg'),
                )

        # Если сделка не закрылась за max_duration
        exit_price = df.iloc[min(len(df)-1, entry_idx + self.config.max_duration_hours)]['close']
        profit_pct = (exit_price - entry_price) / entry_price * 100 if direction == 'LONG' else (entry_price - exit_price) / entry_price * 100
        r_multiple = profit_pct / stop_loss_distance_pct
        exit_time = datetime.fromtimestamp(df.iloc[min(len(df)-1, entry_idx + self.config.max_duration_hours)]['time'] / 1000, tz=timezone.utc)
        duration_hours = (exit_time - entry_time).total_seconds() / 3600

        return BacktestTrade(
            symbol=self.config.symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time,
            result=BacktestResult.EXPIRED,
            r_multiple=round(r_multiple, 2),
            profit_pct=round(profit_pct, 2),
            duration_hours=round(duration_hours, 1),
            signal_type=signal['type'],
            max_price=max_price,
            min_price=min_price,
            smc_ob=signal.get('smc_ob'),
            smc_fvg=signal.get('smc_fvg'),
        )

    async def run_backtest(self) -> Dict[str, Any]:
        """
        Запускает полный бэктест
        """
        logger.info("🚀 Запуск бэктестинга...")

        # 1. Загружаем данные
        df = await self.load_historical_data()

        # 2. Рассчитываем индикаторы
        df = self.calculate_indicators(df)

        # 3. Загружаем HTF данные и вычисляем weekly PP
        df_htf = await self._load_htf_df() if self.config.use_htf_filter else pd.DataFrame()
        weekly_pp = self._compute_weekly_pp(df) if self.config.use_pivot_filter else {}
        need_pivots = self.config.use_pivot_tp or self.config.use_pivot_boost
        full_pivots = self._compute_full_pivots(df) if need_pivots else {}
        df_ltf = await self._load_ltf_df() if (self.config.use_fvg or self.config.use_fvg_boost) else pd.DataFrame()

        # 4. Ищем сигналы
        signals = await self.detect_signals(df, df_htf, weekly_pp, full_pivots, df_ltf=df_ltf)

        # 5. Симулируем торговлю
        logger.info("Симуляция торговли...")
        df = df.reset_index(drop=True)  # гарантируем RangeIndex

        # Индексируем сигналы по bar_idx для перезаходов
        signal_by_idx: Dict[int, List[Dict]] = {}
        for sig in signals:
            idx = sig.get('bar_idx', -1)
            signal_by_idx.setdefault(idx, []).append(sig)

        processed_bars: set = set()  # чтобы не торговать дважды на одном баре

        def _process_signal(signal: Dict, already_traded: set) -> Optional[BacktestTrade]:
            entry_idx = signal.get('bar_idx')
            if entry_idx is None or entry_idx >= len(df) - 1 or entry_idx in already_traded:
                return None
            already_traded.add(entry_idx)
            return self.simulate_trade_with_tsl(signal, df, entry_idx)

        for signal in signals:
            trade = _process_signal(signal, processed_bars)
            if trade:
                self.trades.append(trade)
                self.current_balance += _trade_pnl(trade, self.current_balance, self.config)

                # Перезаход после SL: ищем дивергенцию в том же направлении
                if self.config.use_reentry and trade.result == BacktestResult.LOSS:
                    tf_minutes = {'1m':1,'3m':3,'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
                    bar_minutes = tf_minutes.get(self.config.timeframe, 60)
                    sl_bar = signal.get('bar_idx', 0) + max(1, int(trade.duration_hours * 60 / bar_minutes))
                    search_end = sl_bar + self.config.reentry_lookback
                    reentry_direction = signal['direction']
                    for ridx in range(sl_bar + 1, min(search_end, max(signal_by_idx.keys()) + 1)):
                        re_sigs = signal_by_idx.get(ridx, [])
                        for rsig in re_sigs:
                            if (rsig['direction'] == reentry_direction
                                    and rsig['type'] in ('divergence', 'wt_signal')):
                                re_trade = _process_signal(rsig, processed_bars)
                                if re_trade:
                                    self.trades.append(re_trade)
                                    self.current_balance += _trade_pnl(re_trade, self.current_balance, self.config)
                                break
                        else:
                            continue
                        break

        # 5. Рассчитываем метрики
        metrics = self.calculate_metrics()

        # 6. In-sample / Out-of-sample разбивка
        split_idx = int(len(df) * self.config.train_pct)
        split_bar_time = int(df.iloc[split_idx]['time']) if split_idx < len(df) else 0

        in_sample_trades = [t for t in self.trades if int(t.entry_time.timestamp() * 1000) < split_bar_time]
        oos_trades = [t for t in self.trades if int(t.entry_time.timestamp() * 1000) >= split_bar_time]

        def _calc_simple_metrics(trades: list) -> dict:
            if not trades:
                return {'trades': 0, 'win_rate': 0.0, 'avg_r': 0.0}
            wins = [t for t in trades if t.result == BacktestResult.WIN]
            return {
                'trades': len(trades),
                'win_rate': round(len(wins) / len(trades) * 100, 1),
                'avg_r': round(float(np.mean([t.r_multiple for t in trades])), 2),
            }

        in_sample_metrics = _calc_simple_metrics(in_sample_trades)
        oos_metrics = _calc_simple_metrics(oos_trades)

        # Метрики по типам сигналов с IS/OOS разбивкой
        signal_types = set(t.signal_type for t in self.trades)
        signal_split = {}
        for st in signal_types:
            is_t = [t for t in in_sample_trades if t.signal_type == st]
            oos_t = [t for t in oos_trades if t.signal_type == st]
            signal_split[st] = {
                'in_sample': _calc_simple_metrics(is_t),
                'out_of_sample': _calc_simple_metrics(oos_t),
            }

        if self._owned_exchange:
            await self._swap_exchange.close()
        logger.info("Бэктест завершен")
        return {
            'config': self.config,
            'trades': self.trades,
            'metrics': metrics,
            'data_points': len(df),
            'signals_found': len(signals),
            'in_sample_metrics': in_sample_metrics,
            'out_of_sample_metrics': oos_metrics,
            'signal_split': signal_split,
        }

    def calculate_metrics(self) -> Dict[str, Any]:
        """
        Рассчитывает метрики производительности
        """
        if not self.trades:
            return {
                'total_trades': 0, 'win_rate': 0.0, 'avg_win_pct': 0.0, 'avg_loss_pct': 0.0,
                'avg_r_multiple': 0.0, 'sharpe_ratio': 0.0, 'max_drawdown_pct': 0.0,
                'total_return_pct': 0.0, 'profit_factor': 0.0,
                'expired_pct': 0.0, 'signal_performance': {},
            }

        # Базовые метрики
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.result == BacktestResult.WIN]
        losing_trades = [t for t in self.trades if t.result == BacktestResult.LOSS]
        expired_trades = [t for t in self.trades if t.result == BacktestResult.EXPIRED]

        win_rate = len(winning_trades) / total_trades * 100
        avg_win = np.mean([t.profit_pct for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.profit_pct for t in losing_trades]) if losing_trades else 0
        avg_r = np.mean([t.r_multiple for t in self.trades])

        # DEV-33: account-level returns = price_move × leverage − commission_round_trip
        lev = max(1, int(self.config.leverage))
        comm_rt = self.config.commission_pct * 2  # round-trip commission (entry + exit)
        acct_returns = [t.profit_pct * lev - comm_rt for t in self.trades]

        # Risk metrics (на account-level доходности)
        sharpe_ratio = np.mean(acct_returns) / np.std(acct_returns) * np.sqrt(365) if acct_returns else 0

        # Drawdown (на account-level доходности)
        cumulative_returns = np.cumprod([1 + r/100 for r in acct_returns])
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdowns = (cumulative_returns - running_max) / running_max
        max_drawdown = np.min(drawdowns) * 100 if len(drawdowns) > 0 else 0

        # Profit factor (на account-level)
        gross_profit = sum([r for r in acct_returns if r > 0])
        gross_loss = abs(sum([r for r in acct_returns if r < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Максимальная серия SL подряд
        max_consecutive_sl = 0
        current_sl_streak = 0
        for t in self.trades:
            if t.result == BacktestResult.LOSS:
                current_sl_streak += 1
                max_consecutive_sl = max(max_consecutive_sl, current_sl_streak)
            else:
                current_sl_streak = 0

        # По типам сигналов
        signal_performance = {}
        for signal_type in set([t.signal_type for t in self.trades]):
            type_trades = [t for t in self.trades if t.signal_type == signal_type]
            type_wins = [t for t in type_trades if t.result == BacktestResult.WIN]
            # Серия SL для типа
            max_sl_streak = 0
            streak = 0
            for t in type_trades:
                if t.result == BacktestResult.LOSS:
                    streak += 1
                    max_sl_streak = max(max_sl_streak, streak)
                else:
                    streak = 0
            signal_performance[signal_type] = {
                'total': len(type_trades),
                'win_rate': round(len(type_wins) / len(type_trades) * 100, 1) if type_trades else 0,
                'avg_r': round(np.mean([t.r_multiple for t in type_trades]), 2) if type_trades else 0,
                'max_sl_streak': max_sl_streak,
            }

        return {
            'total_trades': total_trades,
            'win_rate': round(win_rate, 1),
            'avg_win_pct': round(avg_win, 2),
            'avg_loss_pct': round(avg_loss, 2),
            'avg_r_multiple': round(avg_r, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'profit_factor': round(profit_factor, 2),
            'final_balance': round(self.current_balance, 2),
            'total_return_pct': round((self.current_balance - self.config.initial_balance) / self.config.initial_balance * 100, 2),
            'wins': len(winning_trades),
            'losses': len(losing_trades),
            'expired': len(expired_trades),
            'max_consecutive_sl': max_consecutive_sl,
            'signal_performance': signal_performance,
            # DEV-33
            'leverage': lev,
            'commission_pct': self.config.commission_pct,
            # DEV-34: SMC статистика
            'smc_stats': _calc_smc_stats(self.trades) if self.config.use_smc else None,
        }


class HistoricalDataCollector:
    """
    Мок data_collector для бэктестинга: при вызове get_ohlcv() возвращает
    срез предзагруженных исторических данных до current_bar_time включительно.
    Интерфейс совместим с RealTimeData.
    """

    def __init__(self, dfs: Dict[str, pd.DataFrame]):
        """
        dfs: {"1h": df_1h, "15m": df_15m, "3m": df_3m, ...}
        Каждый df должен иметь колонку 'time' в миллисекундах (UTC).
        """
        self._dfs = dfs
        self.current_bar_time: int = 0  # устанавливается перед каждым баром

    def normalize_symbol(self, symbol: str) -> str:
        return symbol

    async def symbol_exists(self, symbol: str) -> bool:
        return True

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m",
                        limit: int = 150, since=None) -> Optional[pd.DataFrame]:
        df = self._dfs.get(timeframe)
        if df is None or df.empty:
            return None
        subset = df[df['time'] <= self.current_bar_time].tail(limit).copy().reset_index(drop=True)
        return subset if not subset.empty else None

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        df15 = self._dfs.get("15m")
        df = df15 if (df15 is not None and not df15.empty) else self._dfs.get("1h")
        if df is None:
            return None
        latest = df[df['time'] <= self.current_bar_time].tail(1)
        if latest.empty:
            return None
        row = latest.iloc[-1]
        # Приближённый 24h объём = сумма последних 96 15m-баров × цена
        vol_bars = df[df['time'] <= self.current_bar_time].tail(96)
        vol_24h = float(vol_bars['volume'].sum()) * float(row['close'])
        return {
            'last': float(row['close']),
            'close': float(row['close']),
            'quoteVolume': vol_24h,
            'baseVolume': float(vol_bars['volume'].sum()),
        }


# Конфигурация по умолчанию — используется и в CLI, и в дашборде
DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "GRT/USDT",
    "LINK/USDT", "AVAX/USDT", "DOGE/USDT", "ADA/USDT",
    "INJ/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
    "SUI/USDT", "TON/USDT", "WIF/USDT", "PEPE/USDT",
    "JUP/USDT", "ATOM/USDT", "TIA/USDT", "MATIC/USDT",
]

# Квартальные периоды (1h бэктест, BingX swap с июля 2024)
DEFAULT_PERIODS = [
    ("Q3-2024", datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 9, 30, tzinfo=timezone.utc)),
    ("Q4-2024", datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, tzinfo=timezone.utc)),
    ("Q1-2025", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 3, 31, tzinfo=timezone.utc)),
    ("Q2-2025", datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 6, 30, tzinfo=timezone.utc)),
    ("Q3-2025", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 9, 30, tzinfo=timezone.utc)),
    ("Q4-2025", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, tzinfo=timezone.utc)),
    ("2026-YTD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 5, tzinfo=timezone.utc)),
]

# Месячные периоды (15m бэктест, BingX swap с ~июля 2025)
DEFAULT_MONTHLY_PERIODS = [
    ("2025-Jul", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 7, 31, tzinfo=timezone.utc)),
    ("2025-Aug", datetime(2025, 8, 1, tzinfo=timezone.utc), datetime(2025, 8, 31, tzinfo=timezone.utc)),
    ("2025-Sep", datetime(2025, 9, 1, tzinfo=timezone.utc), datetime(2025, 9, 30, tzinfo=timezone.utc)),
    ("2025-Oct", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2025, 10, 31, tzinfo=timezone.utc)),
    ("2025-Nov", datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2025, 11, 30, tzinfo=timezone.utc)),
    ("2025-Dec", datetime(2025, 12, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, tzinfo=timezone.utc)),
    ("2026-Jan", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 31, tzinfo=timezone.utc)),
    ("2026-Feb", datetime(2026, 2, 1, tzinfo=timezone.utc), datetime(2026, 2, 28, tzinfo=timezone.utc)),
    ("2026-Mar", datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 3, 6, tzinfo=timezone.utc)),
]


def monte_carlo_from_trades(
    trades: List[BacktestTrade],
    n_simulations: int = 1000,
    risk_pct: float = 1.0,
) -> Dict[str, Any]:
    """
    Bootstrap Monte Carlo: перемешивает trades n_simulations раз (с заменой),
    строит equity curve, возвращает 5/50/95 percentile по WR, Return и MaxDD.
    """
    if not trades:
        return {}
    returns = np.array([t.profit_pct for t in trades])
    wins = np.array([1 if t.result == BacktestResult.WIN else 0 for t in trades])
    rng = np.random.default_rng(42)

    final_rets, max_dds, wrs = [], [], []
    for _ in range(n_simulations):
        idx = rng.integers(0, len(returns), size=len(returns))
        sample_r = returns[idx]
        sample_w = wins[idx]
        wrs.append(float(sample_w.mean() * 100))

        equity, peak, max_dd = 1.0, 1.0, 0.0
        for r in sample_r:
            equity *= (1.0 + r * risk_pct / 10000.0)
            if equity > peak:
                peak = equity
            dd = (equity - peak) / peak
            if dd < max_dd:
                max_dd = dd
        final_rets.append((equity - 1.0) * 100.0)
        max_dds.append(max_dd * 100.0)

    p = lambda arr, q: round(float(np.percentile(arr, q)), 2)
    return {
        'n_trades': len(trades),
        'n_simulations': n_simulations,
        'wr_p5':  p(wrs, 5),  'wr_p50':  p(wrs, 50),  'wr_p95':  p(wrs, 95),
        'ret_p5': p(final_rets, 5), 'ret_p50': p(final_rets, 50), 'ret_p95': p(final_rets, 95),
        'dd_p50': p(max_dds, 50), 'dd_p5': p(max_dds, 5),
    }


async def run_walk_forward_backtest(
    window_weeks: int = 4,
    step_weeks: int = 2,
    wf_start: Optional[datetime] = None,
    symbols: Optional[List[str]] = None,
    on_progress=None,
    **backtest_kwargs,
) -> Dict[str, Any]:
    """
    Walk-Forward бэктест: скользящие окна по window_weeks недель, шаг step_weeks.
    Собирает все сделки из всех окон → Monte Carlo симуляция.
    wf_start — начало walk-forward периода (по умолчанию 2025-07-01 — начало 15m истории).
    """
    symbols = symbols or DEFAULT_SYMBOLS
    start = wf_start or datetime(2025, 7, 1, tzinfo=timezone.utc)
    end = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    windows: List[tuple] = []
    cur = start
    while cur + timedelta(weeks=window_weeks) <= end:
        windows.append((cur, cur + timedelta(weeks=window_weeks)))
        cur += timedelta(weeks=step_weeks)

    def _log(msg: str) -> None:
        print(msg, flush=True)
        if on_progress:
            on_progress(msg)

    _log(f"Walk-Forward: {len(windows)} окон x {len(symbols)} пар "
         f"(окно={window_weeks}нед, шаг={step_weeks}нед)\n")

    all_trades: List[BacktestTrade] = []
    all_results: list = []

    for w_start, w_end in windows:
        label = f"{w_start.strftime('%Y-%m-%d')}..{w_end.strftime('%Y-%m-%d')}"
        _log(f"  Окно {label}")
        periods = [(label, w_start, w_end)]
        results = await run_comprehensive_backtest(
            symbols=symbols,
            periods=periods,
            on_progress=on_progress,
            **backtest_kwargs,
        )
        for r in results:
            all_trades.extend(r.get('trades', []))
        all_results.extend(results)

    mc = monte_carlo_from_trades(all_trades) if len(all_trades) >= 10 else {}

    if mc:
        _log(f"\n=== Monte Carlo ({mc['n_simulations']} симуляций, {mc['n_trades']} сделок) ===")
        _log(f"  Win Rate:  p5={mc['wr_p5']}%  p50={mc['wr_p50']}%  p95={mc['wr_p95']}%")
        _log(f"  Return:    p5={mc['ret_p5']}%  p50={mc['ret_p50']}%  p95={mc['ret_p95']}%")
        _log(f"  Max DD:    медиана={mc['dd_p50']}%  worst-5%={mc['dd_p5']}%")
    else:
        _log("\nНедостаточно сделок для Monte Carlo.")

    return {
        'windows': all_results,
        'all_trades': all_trades,
        'monte_carlo': mc,
    }


class BacktestTradingIntelligence:
    """
    Тонкая обёртка вокруг TradingIntelligence для бэктестинга.
    Переопределяет _filter_signals_by_quality — убирает проверку возраста сигнала
    (исторические сигналы всегда "старые", поэтому фильтр по времени неприменим).
    """

    def __init__(self, mock_collector: HistoricalDataCollector):
        from core.trading_intelligence import TradingIntelligence
        self._ti = TradingIntelligence(mock_collector)
        # Патчим метод фильтрации — убираем проверку timestamp
        self._ti._filter_signals_by_quality = lambda signals: signals
        # Отключаем ML-предиктор: в бэктесте нет обученных моделей
        self._ti.ml_predictor = None
        self._ti.outcome_predictor = None

    async def analyze(self, symbol: str):
        """Вызывает analyze_symbol() и сбрасывает кэш между барами."""
        self._ti.analysis_cache.clear()
        return await self._ti.analyze_symbol(symbol)


async def run_bot_backtest(
    symbol: str = "BTC/USDT",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    min_confidence: float = 0.05,  # 0.0-1.0, rec.confidence — float в диапазоне 0-1
    min_strength: int = 40,
    atr_period: int = 43,
    atr_factor: float = 1.0,
    tp_r: float = 2.0,
    tsl_activation_r: float = 1.0,
    max_duration_bars: int = 96,   # баров 15m (96 = 24h)
    data_source: str = "bingx",    # "bingx" | "binance" | "cryptocom"
    on_progress=None,
    # DEV-34: SMC фильтры (эксперимент cfg1/cfg2/cfg3)
    use_smc: bool = False,
    smc_require_ob: bool = False,
    smc_require_fvg: bool = False,
    smc_ob_pairs: list = None,    # per-asset: None=все, ["ETH/USDT",...]=только эти
) -> Dict[str, Any]:
    """
    Бэктест стандартного поведения бота через TradingIntelligence.analyze_symbol().
    Загружает историю 15m/1h/3m, на каждом 15m-баре вызывает полный анализ,
    при сигнале BUY/SELL симулирует сделку.
    """
    start_date = start_date or datetime(2025, 7, 1, tzinfo=timezone.utc)
    end_date = end_date or datetime.now(tz=timezone.utc)

    def _log(msg: str) -> None:
        print(msg, flush=True)
        if on_progress:
            on_progress(msg)

    _log(f"Bot backtest: {symbol}  {start_date.date()} -> {end_date.date()}")

    since_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)

    # Создаём exchange: BingX шарится как shared_exchange, остальные создаёт engine сам
    shared_ex = None
    if data_source == "bingx":
        shared_ex = ccxt_async.bingx({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
        })

    engine_cfg = BacktestConfig(
        symbol=symbol, timeframe="15m",
        start_date=start_date, end_date=end_date,
        atr_period=atr_period, atr_factor=atr_factor,
        tp_r=tp_r, tsl_activation_r=tsl_activation_r,
        max_duration_hours=max_duration_bars,
        use_tsl=True, risk_per_trade_pct=1.0,
        data_source=data_source,
        use_smc=use_smc, smc_require_ob=smc_require_ob, smc_require_fvg=smc_require_fvg,
        smc_ob_pairs=smc_ob_pairs,
    )
    engine = BacktestingEngine(engine_cfg, shared_exchange=shared_ex)

    try:
        _log("  Загрузка данных 15m...")
        df_15m = await engine._fetch_ohlcv_swap(symbol, "15m", since_ms)
        _log("  Загрузка данных 1h...")
        df_1h = await engine._fetch_ohlcv_swap(symbol, "1h", since_ms)
        _log("  Загрузка данных 3m...")
        df_3m = await engine._fetch_ohlcv_swap(symbol, "3m", since_ms)
    finally:
        if shared_ex:
            await shared_ex.close()
        elif engine._owned_exchange and hasattr(engine._swap_exchange, 'close'):
            await engine._swap_exchange.close()

    if df_15m is None or df_15m.empty:
        _log("  ПРОПУСК: нет данных 15m")
        return {}

    df_15m = df_15m.reset_index(drop=True)
    df_1h = (df_1h if df_1h is not None else pd.DataFrame()).reset_index(drop=True)
    df_3m = (df_3m if df_3m is not None else pd.DataFrame()).reset_index(drop=True)

    mock = HistoricalDataCollector({
        "15m": df_15m,
        "1h": df_1h,
        "3m": df_3m,
    })
    bt_intel = BacktestTradingIntelligence(mock)

    trades: List[BacktestTrade] = []
    current_balance = 10000.0
    in_trade = False
    last_signal_bar = -20   # cooldown
    COOLDOWN = 8            # минимум баров между сигналами

    WINDOW = 200            # минимум баров для инициализации индикаторов
    total_bars = len(df_15m)
    _log(f"  Всего 15m-баров: {total_bars}, анализируем с бара {WINDOW}")

    for i in range(WINDOW, total_bars - 1, COOLDOWN):   # шаг = COOLDOWN (пропускаем «занятые» бары)
        bar = df_15m.iloc[i]
        bar_time = int(bar['time'])

        if bar_time > end_ms:
            break

        if in_trade:
            continue

        mock.current_bar_time = bar_time

        try:
            rec = await bt_intel.analyze(symbol)
        except Exception as e:
            logger.debug(f"analyze error bar {i}: {e}")
            continue

        if rec is None or rec.action not in ('BUY', 'SELL', 'WATCH'):
            continue
        if rec.overall_strength < min_strength:
            continue
        if rec.confidence < min_confidence:
            continue

        # BUY/SELL → direction явная; WATCH → по rec.direction
        from core.signals.signal_models import SignalDirection
        if rec.action == 'BUY':
            direction = 'LONG'
        elif rec.action == 'SELL':
            direction = 'SHORT'
        elif rec.direction == SignalDirection.LONG:
            direction = 'LONG'
        elif rec.direction == SignalDirection.SHORT:
            direction = 'SHORT'
        else:
            continue  # WATCH+NEUTRAL — пропускаем
        signal = {
            'timestamp': bar_time,
            'bar_idx': i,
            'type': rec.primary_signal_type if hasattr(rec, 'primary_signal_type') else 'composite',
            'direction': direction,
            'price': float(bar['close']),
            'strength': rec.overall_strength,
        }

        # DEV-34: SMC фильтр (cfg2/cfg3 — фильтруем сигналы по OB/FVG)
        if use_smc and (smc_require_ob or smc_require_fvg):
            context_window = df_15m.iloc[max(0, i - 200):i].copy().reset_index(drop=True)
            try:
                from core.smc import analyze_smc as _analyze_smc
                smc_ctx = _analyze_smc(context_window)
                is_long_sig = direction == 'LONG'
                ob  = smc_ctx.nearest_bull_ob  if is_long_sig else smc_ctx.nearest_bear_ob
                fvg = smc_ctx.nearest_bull_fvg if is_long_sig else smc_ctx.nearest_bear_fvg
                _ob_ok  = ob  is not None and (ob.bottom * 0.995 <= signal['price'] <= ob.top * 1.005)
                _fvg_ok = fvg is not None
                _ob_pairs = engine_cfg.smc_ob_pairs
                _ob_pair_match = (_ob_pairs is None) or (symbol in _ob_pairs)
                if smc_require_ob and _ob_pair_match and not _ob_ok:
                    continue
                if smc_require_fvg and not _fvg_ok:
                    continue
            except Exception:
                pass  # нет SMC → пропускаем фильтр

        trade = engine.simulate_trade_with_tsl(signal, df_15m, i)
        if trade:
            trades.append(trade)
            trade_value = current_balance * 0.01
            current_balance += trade_value * (trade.profit_pct / 100)
            last_signal_bar = i
            in_trade = False

    # Считаем метрики
    engine.trades = trades
    engine.current_balance = current_balance
    metrics = engine.calculate_metrics()
    mc = monte_carlo_from_trades(trades) if len(trades) >= 10 else {}

    _log(f"  Сделок: {metrics['total_trades']}  WR: {metrics['win_rate']}%  AvgR: {metrics['avg_r_multiple']}")
    if mc:
        _log(f"  MC p50: WR={mc['wr_p50']}%  Return={mc['ret_p50']}%")

    return {
        'symbol': symbol,
        'trades': trades,
        'metrics': metrics,
        'monte_carlo': mc,
    }


def save_results_json(results: list, path: str = "backtest_results.json") -> None:
    """Сохраняет результаты бэктеста в JSON-файл для отображения в дашборде."""
    import json as _json
    serializable = []
    for r in results:
        m = r.get('metrics', {})
        serializable.append({
            'symbol': r.get('symbol', ''),
            'period': r.get('period', ''),
            'total_trades': m.get('total_trades', 0),
            'win_rate': m.get('win_rate', 0),
            'avg_r_multiple': m.get('avg_r_multiple', 0),
            'sharpe_ratio': m.get('sharpe_ratio', 0),
            'max_drawdown_pct': m.get('max_drawdown_pct', 0),
            'total_return_pct': m.get('total_return_pct', 0),
            'wins': m.get('wins', 0),
            'losses': m.get('losses', 0),
            'profit_factor': m.get('profit_factor', 0),
        })
    with open(path, 'w', encoding='utf-8') as f:
        _json.dump({
            'results': serializable,
            'generated_at': datetime.now(tz=timezone.utc).isoformat(),
        }, f, ensure_ascii=False, indent=2)


async def run_comprehensive_backtest(
    symbols: Optional[List[str]] = None,
    periods: Optional[List[tuple]] = None,
    on_progress=None,
    atr_period: int = 14,
    atr_factor: float = 1.5,
    strategy: str = "default",  # "default" | "mtf_pivot"
    use_htf_filter: Optional[bool] = None,   # None = определяется по strategy
    use_pivot_filter: Optional[bool] = None, # None = определяется по strategy
    timeframe: str = "1h",       # основной TF для сигналов
    use_wt: bool = True,
    use_divergence: bool = True,
    div_regular: bool = True,
    div_hidden: bool = True,
    use_anomaly: bool = True,
    use_trend: bool = True,
    use_fvg: bool = False,
    fvg_timeframe: str = "15m",
    use_fvg_boost: bool = False,
    use_pivot_boost: bool = False,
    wt_ob: float = 60.0,
    wt_os: float = -60.0,
    pivot_touch_pct: float = 0.5,
    tp_type: str = "fixed_2r",
    tp_r: float = 2.0,
    tsl_activation_r: float = 1.0,
    tsl_lag_bars: int = 0,
    use_reentry: bool = False,
    reentry_lookback: int = 10,
) -> list:
    """
    Запускает комплексный бэктест по нескольким парам и периодам.
    symbols/periods — переопределяют DEFAULT_SYMBOLS/DEFAULT_PERIODS.
    on_progress(msg) — колбэк для передачи прогресса (напр., в дашборд).
    Возвращает список результатов.
    """
    symbols = symbols or DEFAULT_SYMBOLS
    periods = periods or DEFAULT_PERIODS

    def _log(msg: str) -> None:
        print(msg, flush=True)
        if on_progress:
            on_progress(msg)

    _log("Запуск комплексного бэктестинга: несколько пар x периодов\n")

    # Один shared exchange — load_markets выполняется один раз, экономит rate limit
    shared_ex = ccxt_async.bingx({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })

    results = []
    try:
        for symbol in symbols:
            for period_name, start, end in periods:
                _log(f"  {symbol} {period_name} ...")
                cfg = BacktestConfig(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start,
                    end_date=end,
                    use_tsl=True,
                    tsl_activation_r=tsl_activation_r,
                    risk_per_trade_pct=1.0,
                    use_htf_filter=use_htf_filter if use_htf_filter is not None else (strategy == "default"),
                    use_pivot_filter=use_pivot_filter if use_pivot_filter is not None else (strategy == "default"),
                    atr_period=atr_period,
                    atr_factor=atr_factor,
                    use_pivot_tp=(strategy == "mtf_pivot" or tp_type == "next_pivot"),
                    pivot_tp_min_r=1.0,
                    use_wt=use_wt,
                    use_divergence=use_divergence,
                    div_regular=div_regular,
                    div_hidden=div_hidden,
                    use_anomaly=use_anomaly,
                    use_trend=use_trend,
                    use_fvg=use_fvg,
                    fvg_timeframe=fvg_timeframe,
                    use_fvg_boost=use_fvg_boost,
                    use_pivot_boost=use_pivot_boost,
                    wt_ob=wt_ob,
                    wt_os=wt_os,
                    pivot_touch_pct=pivot_touch_pct,
                    tp_type=tp_type,
                    tp_r=tp_r,
                    tsl_lag_bars=tsl_lag_bars,
                    use_reentry=use_reentry,
                    reentry_lookback=reentry_lookback,
                )
                engine = BacktestingEngine(cfg, shared_exchange=shared_ex)
                try:
                    result = await engine.run_backtest()
                    result['period'] = period_name
                    result['symbol'] = symbol
                    results.append(result)
                    m = result['metrics']
                    _log(f"    сд={m['total_trades']} WR={m['win_rate']}%")
                except Exception as e:
                    _log(f"    ПРОПУСК: {e}")
    finally:
        await shared_ex.close()

    if not results:
        _log("Нет результатов.")
        return results

    # Сохраняем в JSON для дашборда
    try:
        save_results_json(results)
    except Exception as e:
        _log(f"  Не удалось сохранить backtest_results.json: {e}")

    # Таблица сравнения
    _log("")
    header = f"{'Символ':<12} {'Период':<9} {'Сд':>4} {'WR%':>6} {'AvgR':>6} {'Sharpe':>7} {'MaxDD%':>7} {'Return%':>8}"
    sep = "-" * len(header)
    _log("Сравнение по парам и периодам:")
    _log(sep)
    _log(header)
    _log(sep)

    prev_sym = None
    for r in results:
        sym = r['symbol']
        if prev_sym and sym != prev_sym:
            _log("")
        prev_sym = sym
        m = r['metrics']
        _log(f"{sym:<12} {r['period']:<9}"
             f" {m.get('total_trades', 0):>4}"
             f" {m.get('win_rate', 0):>6.1f}"
             f" {m.get('avg_r_multiple', 0):>6.2f}"
             f" {m.get('sharpe_ratio', 0):>7.2f}"
             f" {m.get('max_drawdown_pct', 0):>6.1f}%"
             f" {m.get('total_return_pct', 0):>7.1f}%")

    _log(sep)

    # Итоговая сводка
    all_wr = [r['metrics']['win_rate'] for r in results if r['metrics']['total_trades'] >= 5]
    avg_wr = sum(all_wr) / len(all_wr) if all_wr else 0
    best = max(results, key=lambda x: x['metrics']['total_return_pct'])
    bm = best['metrics']
    _log(f"\nСредний WR по всем парам/периодам (>= 5 сделок): {avg_wr:.1f}%")
    _log(f"Лучший результат: {best['symbol']} {best['period']} — "
         f"WR={bm['win_rate']}% AvgR={bm['avg_r_multiple']} Return={bm['total_return_pct']}%")

    return results


async def _run_bot_backtest_multi():
    """Запускает run_bot_backtest для нескольких пар и выводит сводку."""
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "GRT/USDT",
               "LINK/USDT", "AVAX/USDT", "ARB/USDT", "NEAR/USDT"]
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    all_trades: List[BacktestTrade] = []
    results = []

    for sym in symbols:
        r = await run_bot_backtest(
            symbol=sym,
            start_date=start,
            atr_period=43, atr_factor=1.0,
            tp_r=2.0,
            tsl_activation_r=1.0,
        )
        if r and r.get('metrics', {}).get('total_trades', 0) > 0:
            results.append(r)
            all_trades.extend(r.get('trades', []))

    if not results:
        print("Нет результатов.")
        return

    print("\nСводка bot backtest:")
    print("-" * 60)
    for r in results:
        m = r['metrics']
        print(f"  {r['symbol']:<12}  сд={m['total_trades']:>3}  "
              f"WR={m['win_rate']:>5.1f}%  AvgR={m['avg_r_multiple']:>5.2f}")

    mc = monte_carlo_from_trades(all_trades) if len(all_trades) >= 10 else {}
    if mc:
        print(f"\nMonte Carlo ({mc['n_trades']} сделок):")
        print(f"  WR:     p5={mc['wr_p5']}%  p50={mc['wr_p50']}%  p95={mc['wr_p95']}%")
        print(f"  Return: p5={mc['ret_p5']}%  p50={mc['ret_p50']}%  p95={mc['ret_p95']}%")
        print(f"  Max DD: медиана={mc['dd_p50']}%  worst-5%={mc['dd_p5']}%")


def _print_signal_table(result: dict) -> None:
    """Выводит таблицу результатов по типам сигналов с IS/OOS разбивкой."""
    signal_split = result.get('signal_split', {})
    perf = result.get('metrics', {}).get('signal_performance', {})
    if not perf:
        return
    print("\nТип сигнала     | Сделок | WR%  | Avg R | Серия SL | In-sample        | Out-of-sample")
    print("-" * 90)
    for stype, sp in sorted(perf.items()):
        is_m = signal_split.get(stype, {}).get('in_sample', {})
        oos_m = signal_split.get(stype, {}).get('out_of_sample', {})
        is_str = f"WR={is_m.get('win_rate', 0):.0f}% R={is_m.get('avg_r', 0):.2f}" if is_m.get('trades') else "—"
        oos_str = f"WR={oos_m.get('win_rate', 0):.0f}% R={oos_m.get('avg_r', 0):.2f}" if oos_m.get('trades') else "—"
        print(f"{stype:<16}| {sp['total']:>6} | {sp['win_rate']:>4.0f} | {sp['avg_r']:>5.2f} | {sp['max_sl_streak']:>8} | {is_str:<16} | {oos_str}")
    print("-" * 90)


async def _run_scenario(scenario_name: str) -> None:
    """Запускает сценарий из backtest_config.yaml."""
    import yaml
    config_path = "backtest_config.yaml"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg_yaml = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Файл {config_path} не найден.")
        return
    except Exception as e:
        print(f"Ошибка чтения {config_path}: {e}")
        return

    scenarios = cfg_yaml.get('backtest_scenarios', {})
    if scenario_name not in scenarios:
        available = list(scenarios.keys())
        print(f"Сценарий '{scenario_name}' не найден. Доступные: {available}")
        return

    sc = scenarios[scenario_name]
    symbols = sc.get('symbols', ['BTC/USDT'])
    start_date = datetime.fromisoformat(sc['start_date']).replace(tzinfo=timezone.utc)
    end_date = datetime.fromisoformat(sc['end_date']).replace(tzinfo=timezone.utc)

    print(f"\n🚀 Сценарий: {scenario_name}")
    print(f"   Пары: {symbols}")
    print(f"   Период: {start_date.date()} → {end_date.date()}\n")

    periods = [(scenario_name, start_date, end_date)]
    results = await run_comprehensive_backtest(symbols=symbols, periods=periods)

    # Вывод по типам сигналов
    for r in results:
        sym = r.get('symbol', '')
        m = r.get('metrics', {})
        print(f"\n📊 {sym} — сделок: {m.get('total_trades', 0)}  WR: {m.get('win_rate', 0)}%  "
              f"AvgR: {m.get('avg_r_multiple', 0)}  MaxSL-серия: {m.get('max_consecutive_sl', 0)}")
        is_m = r.get('in_sample_metrics', {})
        oos_m = r.get('out_of_sample_metrics', {})
        print(f"   In-sample (70%):  {is_m.get('trades', 0)} сд  WR={is_m.get('win_rate', 0)}%  AvgR={is_m.get('avg_r', 0)}")
        print(f"   Out-of-sample:    {oos_m.get('trades', 0)} сд  WR={oos_m.get('win_rate', 0)}%  AvgR={oos_m.get('avg_r', 0)}")
        _print_signal_table(r)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtesting Engine")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Сценарий из backtest_config.yaml: quick_test | full_test | stress_test",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Запустить bot backtest (TradingIntelligence.analyze_symbol)",
    )
    args = parser.parse_args()

    if args.scenario:
        asyncio.run(_run_scenario(args.scenario))
    else:
        # Бэктест стандартного поведения бота
        asyncio.run(_run_bot_backtest_multi())