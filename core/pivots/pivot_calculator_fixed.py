"""
Модуль расчета МЕСЯЧНЫХ, НЕДЕЛЬНЫХ и ДНЕВНЫХ пивотов.
Уровни фиксируются на весь период (месяц/неделю/день) по UTC:
  - Месячные: 1-е число 00:00 UTC (= 03:00 МСК)
  - Недельные: Пн 00:00 UTC (= Пн 03:00 МСК)
  - Дневные:   00:00 UTC каждый день (= 03:00 МСК)
"""
import asyncio
import logging
import sqlite3
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Хелперы определения начала периодов (UTC)
# ──────────────────────────────────────────────────────────

def _current_month_start_utc() -> datetime:
    """1-е число текущего месяца 00:00 UTC"""
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _current_week_start_utc() -> datetime:
    """Пн 00:00 UTC текущей недели"""
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _current_day_start_utc() -> datetime:
    """00:00 UTC сегодня"""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _df_with_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет колонку datetime (UTC) из time (ms)"""
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


# ──────────────────────────────────────────────────────────
# Основной класс
# ──────────────────────────────────────────────────────────

class PivotCalculatorFixed:
    """
    Traditional Pivot Points для 1M / 1W / 1D.
    Кеш period-based: уровни не меняются до смены периода.
    """

    def __init__(self, db_path: str = None):
        # {cache_key: {**pivots, "period_start": datetime, ...}}
        self.pivot_cache: Dict[str, Dict] = {}
        self.db_path = db_path
        if db_path:
            self._ensure_table()
            self._load_all_from_db()

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS pivot_cache (
            symbol TEXT,
            timeframe TEXT,
            period_start TEXT,
            pp REAL, s1 REAL, s2 REAL, s3 REAL, s4 REAL, s5 REAL,
            r1 REAL, r2 REAL, r3 REAL, r4 REAL, r5 REAL,
            period_label TEXT,
            method TEXT,
            updated_at TEXT,
            PRIMARY KEY (symbol, timeframe)
        )
    """

    def _ensure_table(self):
        """Создаёт таблицу pivot_cache если не существует. Безопасно при любых условиях."""
        try:
            import os
            db_abs = os.path.abspath(self.db_path)
            logger.debug("PivotCalculatorFixed: db_path=%s (abs=%s)", self.db_path, db_abs)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(self._CREATE_TABLE_SQL)
                conn.commit()
        except Exception as e:
            logger.warning("PivotCalculatorFixed: не удалось создать таблицу: %s", e)

    def _init_db(self):
        """Алиас для обратной совместимости."""
        self._ensure_table()

    def _load_all_from_db(self):
        """Загружает все записи из БД в pivot_cache при старте.
        Пропускает записи с устаревшим period_start (для 1W — не текущая неделя)."""
        try:
            current_week = _current_week_start_utc()
            current_month = _current_month_start_utc()
            current_day = _current_day_start_utc()

            with sqlite3.connect(self.db_path) as conn:
                # Гарантируем наличие таблицы
                conn.execute(self._CREATE_TABLE_SQL)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM pivot_cache").fetchall()

            loaded = 0
            skipped = 0
            for row in rows:
                key = f"{row['symbol']}_{row['timeframe']}"
                d = dict(row)
                # Восстанавливаем period_start как datetime для корректного сравнения с кэшем
                try:
                    period_start = datetime.fromisoformat(d["period_start"])
                except Exception:
                    period_start = d["period_start"]

                # Валидация: пропускаем устаревшие записи
                tf = d.get("timeframe", "")
                if isinstance(period_start, datetime):
                    # Убираем tzinfo для сравнения если нужно
                    ps_naive = period_start.replace(tzinfo=None) if period_start.tzinfo else period_start
                    cw_naive = current_week.replace(tzinfo=None) if current_week.tzinfo else current_week
                    cm_naive = current_month.replace(tzinfo=None) if current_month.tzinfo else current_month
                    cd_naive = current_day.replace(tzinfo=None) if current_day.tzinfo else current_day

                    if tf in ("1W", "1W_prev") and ps_naive != cw_naive:
                        skipped += 1
                        continue
                    if tf == "1M" and ps_naive != cm_naive:
                        skipped += 1
                        continue
                    if tf == "1D" and ps_naive != cd_naive:
                        skipped += 1
                        continue

                # В понедельник: скипаем 1W записи, обновлённые ДО сегодня
                # (они рассчитаны до смены недели и могут содержать стейл данные).
                # Записи, обновлённые сегодня — доверяем (рассчитаны с валидацией свечей).
                now_utc = datetime.now(timezone.utc)
                if tf in ("1W", "1W_prev") and now_utc.weekday() == 0:  # 0 = Monday
                    updated_at_str = d.get("updated_at", "")
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str)
                        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                        today_naive = today_start.replace(tzinfo=None)
                        upd_naive = updated_at.replace(tzinfo=None) if updated_at.tzinfo else updated_at
                        if upd_naive < today_naive:
                            skipped += 1
                            continue
                    except (ValueError, TypeError):
                        skipped += 1
                        continue

                self.pivot_cache[key] = {
                    "PP": d["pp"], "S1": d["s1"], "S2": d["s2"], "S3": d["s3"],
                    "S4": d["s4"], "S5": d["s5"],
                    "R1": d["r1"], "R2": d["r2"], "R3": d["r3"],
                    "R4": d["r4"], "R5": d["r5"],
                    "timeframe": d["timeframe"],
                    "period_start": period_start,
                    "period_label": d.get("period_label", ""),
                    "method": d.get("method", ""),
                }
                loaded += 1
            if rows:
                logger.info(
                    "PivotCalculatorFixed: загружено %d записей из БД (пропущено %d устаревших)",
                    loaded, skipped,
                )
        except Exception as e:
            logger.warning("PivotCalculatorFixed: ошибка загрузки из БД: %s", e)

    def _save_to_db(self, symbol: str, timeframe: str, data: Dict):
        """Сохраняет/обновляет пивоты в БД после вычисления."""
        if not self.db_path:
            return
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(self._CREATE_TABLE_SQL)
                conn.execute("""
                    INSERT OR REPLACE INTO pivot_cache
                    (symbol, timeframe, period_start, pp, s1, s2, s3, s4, s5,
                     r1, r2, r3, r4, r5, period_label, method, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    symbol, timeframe,
                    str(data.get("period_start", "")),
                    data.get("PP"), data.get("S1"), data.get("S2"),
                    data.get("S3"), data.get("S4"), data.get("S5"),
                    data.get("R1"), data.get("R2"), data.get("R3"),
                    data.get("R4"), data.get("R5"),
                    data.get("period_label", ""),
                    data.get("method", ""),
                    now,
                ))
        except Exception as e:
            logger.debug("PivotCalculatorFixed: ошибка сохранения в БД для %s %s: %s", symbol, timeframe, e)

    # ──────────────────────────────────────────────────────
    # Формулы
    # ──────────────────────────────────────────────────────

    def calculate_traditional_pivots(self, high: float, low: float, close: float) -> Dict[str, float]:
        """Traditional Pivot Points — делегирует в calculate_pivot_points из core/indicators.py."""
        from core.indicators.indicators import calculate_pivot_points
        return calculate_pivot_points(high, low, close)

    # ──────────────────────────────────────────────────────
    # Месячные пивоты
    # ──────────────────────────────────────────────────────

    async def get_monthly_pivots(self, symbol: str, data_collector) -> Optional[Dict]:
        """Месячные пивоты = H/L/C предыдущего полного календарного месяца"""
        month_start = _current_month_start_utc()
        cache_key = f"{symbol}_1M"
        cached = self.pivot_cache.get(cache_key)
        if cached and cached.get("period_start") == month_start:
            logger.debug(f"Кеш 1M для {symbol}")
            return cached

        prev_month_end = month_start
        prev_month_start = (month_start - timedelta(days=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=35)
            if df is None or len(df) < 5:
                return None

            df = _df_with_datetime(df)
            prev_month = df[
                (df["datetime"] >= prev_month_start) & (df["datetime"] < prev_month_end)
            ]

            if prev_month.empty:
                logger.debug(f"Нет данных прошлого месяца для {symbol}")
                return None

            pivots = self.calculate_traditional_pivots(
                prev_month["high"].max(),
                prev_month["low"].min(),
                prev_month["close"].iloc[-1],
            )
            pivots.update({
                "timeframe": "1M",
                "method": "aggregated_from_1d",
                "period_start": month_start,
                "period_label": prev_month_start.strftime("%Y-%m"),
                "timestamp": datetime.now(timezone.utc),
            })
            self.pivot_cache[cache_key] = pivots
            self._save_to_db(symbol, "1M", pivots)
            logger.info(f"✅ Месячные пивоты {symbol}: PP={pivots['PP']:.4f} ({pivots['period_label']})")
            return pivots

        except Exception:
            logger.exception(f"Ошибка месячных пивотов для {symbol}")
            return None

    # ──────────────────────────────────────────────────────
    # Недельные пивоты
    # ──────────────────────────────────────────────────────

    async def get_weekly_pivots(self, symbol: str, data_collector) -> Optional[Dict]:
        """Недельные пивоты = H/L/C прошлой полной недели (Пн–Вс UTC)"""
        week_start = _current_week_start_utc()
        cache_key = f"{symbol}_1W"
        cached = self.pivot_cache.get(cache_key)
        if cached and cached.get("period_start") == week_start:
            logger.debug(f"Кеш 1W для {symbol}")
            return cached

        prev_week_end = week_start
        prev_week_start = week_start - timedelta(weeks=1)

        # Метод 1 (PRIMARY): прямой fetch 1w свечей — не зависит от UTC-границ суток биржи
        pivots = await self._weekly_from_1w(symbol, data_collector)
        # Метод 2: из дневных свечей с фильтром дат
        if not pivots:
            pivots = await self._weekly_from_1d(symbol, data_collector, prev_week_start, prev_week_end)
        # Метод 3 (fallback): из 4h свечей
        if not pivots:
            pivots = await self._weekly_from_4h(symbol, data_collector, prev_week_start, prev_week_end)
        # Метод 4 (последний резерв): из 1h свечей — работает даже если биржа не даёт 1d/4h/1w
        if not pivots:
            pivots = await self._weekly_from_1h(symbol, data_collector, prev_week_start, prev_week_end)

        if pivots:
            pivots["period_start"] = week_start
            # Сохраняем старый кэш как prev перед перезаписью
            old = self.pivot_cache.get(cache_key)
            if old and old.get("period_start") != week_start:
                self.pivot_cache[f"{symbol}_1W_prev"] = old
                self._save_to_db(symbol, "1W_prev", old)
            self.pivot_cache[cache_key] = pivots
            self._save_to_db(symbol, "1W", pivots)
            logger.info(f"✅ Недельные пивоты {symbol}: PP={pivots['PP']:.4f} ({pivots.get('period_label','')})")
            return pivots

        logger.info("Недельные пивоты недоступны для %s (нет данных)", symbol)
        return None

    async def _weekly_from_1d(self, symbol, data_collector, week_start, week_end) -> Optional[Dict]:
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=14)
            if df is None or len(df) < 5:
                return None
            df = _df_with_datetime(df)
            week = df[(df["datetime"] >= week_start) & (df["datetime"] < week_end)]
            if len(week) < 3:
                # Fallback: если фильтр дат промахнулся (нестандартная UTC-граница биржи),
                # берём последние 7 завершённых баров (исключая текущий незакрытый)
                week = df.iloc[-8:-1] if len(df) >= 8 else df.iloc[:-1]
                if len(week) < 3:
                    return None
            h_val = float(week["high"].max())
            l_val = float(week["low"].min())
            c_val = float(week["close"].iloc[-1])
            pivots = self.calculate_traditional_pivots(h_val, l_val, c_val)
            logger.info(
                "[weekly_1d] %s: %d bars, %s H=%.6f L=%.6f C=%.6f → PP=%.6f",
                symbol, len(week), week_start.strftime("%Y-W%V"), h_val, l_val, c_val, pivots.get("PP", 0),
            )
            pivots.update({
                "timeframe": "1W",
                "method": "aggregated_from_1d",
                "period_label": week_start.strftime("%Y-W%V"),
                "source_high": h_val,
                "source_low": l_val,
                "source_close": c_val,
                "timestamp": datetime.now(timezone.utc),
            })
            return pivots
        except Exception as e:
            logger.debug(f"_weekly_from_1d failed {symbol}: {e}")
            return None

    async def _weekly_from_4h(self, symbol, data_collector, week_start, week_end) -> Optional[Dict]:
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="4h", limit=56)
            if df is None or len(df) < 30:
                return None
            df = _df_with_datetime(df)
            week = df[(df["datetime"] >= week_start) & (df["datetime"] < week_end)]
            if len(week) < 10:
                return None
            pivots = self.calculate_traditional_pivots(
                week["high"].max(), week["low"].min(), week["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "1W",
                "method": "aggregated_from_4h",
                "period_label": week_start.strftime("%Y-W%V"),
                "timestamp": datetime.now(timezone.utc),
            })
            return pivots
        except Exception as e:
            logger.debug(f"_weekly_from_4h failed {symbol}: {e}")
            return None

    async def _weekly_from_1w(self, symbol: str, data_collector) -> Optional[Dict]:
        """Прямой fetch 1w свечей — самый надёжный метод, без привязки к UTC-границам суток."""
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1w", limit=3)
            if df is None or len(df) < 2:
                return None
            # iloc[-2] = предыдущая завершённая неделя (iloc[-1] = текущая открытая)
            prev = df.iloc[-2]
            h, l, c = float(prev["high"]), float(prev["low"]), float(prev["close"])

            # Валидация: свеча должна быть за прошлую неделю (Пн-1нед .. Пн текущей)
            candle_ts = None
            if "time" in df.columns:
                candle_ts = int(prev["time"])
            elif "timestamp" in df.columns:
                candle_ts = int(prev["timestamp"])

            period_label = ""
            if candle_ts:
                from datetime import datetime as _dt
                candle_dt = _dt.utcfromtimestamp(candle_ts / 1000) if candle_ts > 1e12 else _dt.utcfromtimestamp(candle_ts)
                period_label = candle_dt.strftime("%Y-%m-%d")

                # Проверяем: дата свечи должна быть в пределах prev_week_start ± 2 дня
                # (разные биржи начинают неделю в разные дни: Пн, Вс, Сб)
                expected_start = _current_week_start_utc() - timedelta(weeks=1)
                candle_dt_aware = candle_dt.replace(tzinfo=timezone.utc)
                delta_days = abs((candle_dt_aware - expected_start).days)
                if delta_days > 2:
                    logger.warning(
                        "[weekly_1w] %s: ОТКЛОНЕНА — свеча=%s, ожидалась неделя от %s (delta=%d дней). "
                        "BingX week boundary не совпадает. Fallback на 1d.",
                        symbol, period_label, expected_start.strftime("%Y-%m-%d"), delta_days,
                    )
                    return None  # fallback на _weekly_from_1d

            pivots = self.calculate_traditional_pivots(h, l, c)
            logger.info(
                "[weekly_1w] %s: prev candle=%s H=%.6f L=%.6f C=%.6f → PP=%.6f R1=%.6f S1=%.6f",
                symbol, period_label, h, l, c,
                pivots.get("PP", 0), pivots.get("R1", 0), pivots.get("S1", 0),
            )
            pivots.update({
                "timeframe": "1W",
                "method": "direct_1w",
                "period_label": period_label,
                "source_high": h,
                "source_low": l,
                "source_close": c,
                "timestamp": datetime.now(timezone.utc),
            })
            return pivots
        except Exception as e:
            logger.debug("_weekly_from_1w failed %s: %s", symbol, e)
            return None

    async def _weekly_from_1h(self, symbol: str, data_collector, week_start, week_end) -> Optional[Dict]:
        """Последний резерв: агрегация из 1h свечей. 1h работает на любой бирже."""
        try:
            # limit=160 — максимум BingX на OHLCV-запрос; плюс уже в кеше от скана (cache HIT)
            df = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=160)
            if df is None or len(df) < 24:
                return None
            df = _df_with_datetime(df)
            week = df[(df["datetime"] >= week_start) & (df["datetime"] < week_end)]
            if len(week) < 24:
                # Фильтр дат не сработал — берём последние ~7 дней, исключая текущий бар
                week = df.iloc[-161:-1] if len(df) >= 161 else df.iloc[:-1]
                if len(week) < 24:
                    return None
            pivots = self.calculate_traditional_pivots(
                week["high"].max(), week["low"].min(), week["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "1W",
                "method": "aggregated_from_1h",
                "period_label": week_start.strftime("%Y-W%V"),
                "timestamp": datetime.now(timezone.utc),
            })
            return pivots
        except Exception as e:
            logger.debug("_weekly_from_1h failed %s: %s", symbol, e)
            return None

    # ──────────────────────────────────────────────────────
    # Дневные пивоты
    # ──────────────────────────────────────────────────────

    async def get_daily_pivots(self, symbol: str, data_collector) -> Optional[Dict]:
        """Дневные пивоты = H/L/C предыдущего полного дня (00:00–00:00 UTC)"""
        day_start = _current_day_start_utc()
        cache_key = f"{symbol}_1D"
        cached = self.pivot_cache.get(cache_key)
        if cached and cached.get("period_start") == day_start:
            logger.debug(f"Кеш 1D для {symbol}")
            return cached

        prev_day_end = day_start
        prev_day_start = day_start - timedelta(days=1)

        # Сохраняем старый кэш как prev перед пересчётом
        old_daily = self.pivot_cache.get(cache_key)
        if old_daily and old_daily.get("period_start") != day_start:
            self.pivot_cache[f"{symbol}_1D_prev"] = old_daily
            self._save_to_db(symbol, "1D_prev", old_daily)

        # Сравниваем по ms-timestamp (int) — избегаем TZ-сравнение pandas Timestamp vs Python datetime
        prev_start_ms = int(prev_day_start.timestamp() * 1000)
        today_ms = int(day_start.timestamp() * 1000)

        try:
            # Метод 1: из дневных свечей
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=5)
            if df is not None and len(df) >= 2:
                df = df.sort_values("time")
                # Фильтр по ms-timestamp: yesterday start ≤ time < today start
                prev = df[(df["time"] >= prev_start_ms) & (df["time"] < today_ms)]
                if prev.empty:
                    # Fallback: если свеча отдаётся с close-timestamp (= today_ms), включаем её
                    prev = df[(df["time"] >= prev_start_ms) & (df["time"] <= today_ms)]
                    prev = prev.iloc[:-1] if len(prev) > 1 else prev
                if not prev.empty:
                    H = float(prev["high"].max())
                    L = float(prev["low"].min())
                    C = float(prev["close"].iloc[-1])
                    candle_ts = int(prev["time"].iloc[-1])
                    candle_dt = datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc)
                    logger.debug(
                        "[daily_pivot] %s: prev_candle dt=%s H=%.6f L=%.6f C=%.6f",
                        symbol, candle_dt.strftime("%Y-%m-%d %H:%M"), H, L, C,
                    )
                    pivots = self.calculate_traditional_pivots(H, L, C)
                    pivots.update({
                        "timeframe": "1D",
                        "method": "direct_1d",
                        "period_start": day_start,
                        "period_label": prev_day_start.strftime("%Y-%m-%d"),
                        "timestamp": datetime.now(timezone.utc),
                    })
                    self.pivot_cache[cache_key] = pivots
                    self._save_to_db(symbol, "1D", pivots)
                    logger.info(
                        "✅ Дневные пивоты %s: PP=%.4f R1=%.4f S1=%.4f (%s) [candle=%s]",
                        symbol, pivots["PP"], pivots.get("R1", 0), pivots.get("S1", 0),
                        pivots["period_label"], candle_dt.strftime("%Y-%m-%d %H:%M UTC"),
                    )
                    return pivots

            # Метод 2 (fallback): из 1h свечей
            df_1h = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=30)
            if df_1h is None or len(df_1h) < 24:
                return None
            prev_1h = df_1h[(df_1h["time"] >= prev_start_ms) & (df_1h["time"] < today_ms)]
            if len(prev_1h) < 12:
                return None
            H = float(prev_1h["high"].max())
            L = float(prev_1h["low"].min())
            C = float(prev_1h["close"].iloc[-1])
            logger.debug("[daily_pivot] %s (1h): H=%.6f L=%.6f C=%.6f", symbol, H, L, C)
            pivots = self.calculate_traditional_pivots(H, L, C)
            pivots.update({
                "timeframe": "1D",
                "method": "aggregated_from_1h",
                "period_start": day_start,
                "period_label": prev_day_start.strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc),
            })
            self.pivot_cache[cache_key] = pivots
            self._save_to_db(symbol, "1D", pivots)
            logger.info(f"✅ Дневные пивоты {symbol} (из 1h): PP={pivots['PP']:.4f}")
            return pivots

        except Exception:
            logger.exception(f"Ошибка дневных пивотов для {symbol}")
            return None

    # ──────────────────────────────────────────────────────
    # Future Pivots (DEV-11) — текущий период H/L/C
    # ──────────────────────────────────────────────────────
    # Кеш с TTL=60 сек: уровни меняются с каждой свечой,
    # поэтому используем time-based cache, а не period-based.

    def _future_cache_valid(self, cache_key: str, ttl_sec: int = 60) -> bool:
        """Проверяет свежесть future-кеша по TTL."""
        cached = self.pivot_cache.get(cache_key)
        if not cached or "expires_at" not in cached:
            return False
        return datetime.now(timezone.utc) < cached["expires_at"]

    async def get_future_daily_pivots(
        self, symbol: str, data_collector, ttl_sec: int = 60
    ) -> Optional[Dict]:
        """Future Daily Pivots = PP/S/R из текущего дня (00:00 UTC → сейчас)."""
        cache_key = f"{symbol}_future_1D"
        if self._future_cache_valid(cache_key, ttl_sec):
            return self.pivot_cache[cache_key]

        day_start = _current_day_start_utc()
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=30)
            if df is None or len(df) < 1:
                return None
            df = _df_with_datetime(df)
            today = df[df["datetime"] >= day_start]
            if today.empty:
                return None
            pivots = self.calculate_traditional_pivots(
                today["high"].max(), today["low"].min(), today["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "future_1D",
                "method": "future_from_1h",
                "period_label": day_start.strftime("%Y-%m-%d") + " (live)",
                "expires_at": datetime.now(timezone.utc).replace(
                    second=0, microsecond=0
                ) + timedelta(seconds=ttl_sec),
            })
            self.pivot_cache[cache_key] = pivots
            logger.debug("Future 1D пивоты %s: PP=%.6f", symbol, pivots["PP"])
            return pivots
        except Exception:
            logger.exception("Ошибка future_daily_pivots для %s", symbol)
            return None

    async def get_future_weekly_pivots(
        self, symbol: str, data_collector, ttl_sec: int = 60
    ) -> Optional[Dict]:
        """Future Weekly Pivots = PP/S/R из текущей недели (Пн UTC → сейчас)."""
        cache_key = f"{symbol}_future_1W"
        if self._future_cache_valid(cache_key, ttl_sec):
            return self.pivot_cache[cache_key]

        week_start = _current_week_start_utc()
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="4h", limit=56)
            if df is None or len(df) < 1:
                # fallback к 1h
                df = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=160)
            if df is None or len(df) < 1:
                return None
            df = _df_with_datetime(df)
            this_week = df[df["datetime"] >= week_start]
            if this_week.empty:
                return None
            pivots = self.calculate_traditional_pivots(
                this_week["high"].max(), this_week["low"].min(), this_week["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "future_1W",
                "method": "future_from_4h",
                "period_label": week_start.strftime("%Y-W%V") + " (live)",
                "expires_at": datetime.now(timezone.utc).replace(
                    second=0, microsecond=0
                ) + timedelta(seconds=ttl_sec),
            })
            self.pivot_cache[cache_key] = pivots
            logger.debug("Future 1W пивоты %s: PP=%.6f", symbol, pivots["PP"])
            return pivots
        except Exception:
            logger.exception("Ошибка future_weekly_pivots для %s", symbol)
            return None

    async def get_future_monthly_pivots(
        self, symbol: str, data_collector, ttl_sec: int = 60
    ) -> Optional[Dict]:
        """Future Monthly Pivots = PP/S/R из текущего месяца (1-е UTC → сейчас)."""
        cache_key = f"{symbol}_future_1M"
        if self._future_cache_valid(cache_key, ttl_sec):
            return self.pivot_cache[cache_key]

        month_start = _current_month_start_utc()
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=35)
            if df is None or len(df) < 1:
                return None
            df = _df_with_datetime(df)
            this_month = df[df["datetime"] >= month_start]
            if this_month.empty:
                return None
            pivots = self.calculate_traditional_pivots(
                this_month["high"].max(), this_month["low"].min(), this_month["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "future_1M",
                "method": "future_from_1d",
                "period_label": month_start.strftime("%Y-%m") + " (live)",
                "expires_at": datetime.now(timezone.utc).replace(
                    second=0, microsecond=0
                ) + timedelta(seconds=ttl_sec),
            })
            self.pivot_cache[cache_key] = pivots
            logger.debug("Future 1M пивоты %s: PP=%.6f", symbol, pivots["PP"])
            return pivots
        except Exception:
            logger.exception("Ошибка future_monthly_pivots для %s", symbol)
            return None

    # ──────────────────────────────────────────────────────
    # Сводный метод
    # ──────────────────────────────────────────────────────

    async def get_multi_timeframe_pivots(self, symbol: str, data_collector) -> Dict[str, object]:
        """
        Возвращает {'1M': {...}, '1W': {...}, '1D': {...}, 'confluence': [...]}
        """
        results: Dict = {}

        monthly, weekly, daily = await asyncio.gather(
            self.get_monthly_pivots(symbol, data_collector),
            self.get_weekly_pivots(symbol, data_collector),
            self.get_daily_pivots(symbol, data_collector),
        )

        if monthly:
            results["1M"] = monthly
        if weekly:
            results["1W"] = weekly
        if daily:
            results["1D"] = daily

        # Предыдущие периоды (для flip-levels и кросс-периодных конфлюэнций)
        prev_weekly = self.pivot_cache.get(f"{symbol}_1W_prev")
        if prev_weekly:
            results["1W_prev"] = prev_weekly
        prev_daily = self.pivot_cache.get(f"{symbol}_1D_prev")
        if prev_daily:
            results["1D_prev"] = prev_daily

        # Конфлюэнции между всеми доступными уровнями
        results["confluence"] = self._find_all_confluences(results)
        if results["confluence"]:
            logger.debug(f"🎯 {len(results['confluence'])} конфлюэнций для {symbol}")

        return results

    # ──────────────────────────────────────────────────────
    # Конфлюэнции
    # ──────────────────────────────────────────────────────

    # Допуски по парам TF: разные таймфреймы имеют разный масштаб уровней
    _TF_TOLERANCE = {
        ("1D", "1D_prev"): 0.3,   # тот же TF разных периодов → строго
        ("1W", "1W_prev"): 0.5,
        ("1W", "1D"):      1.0,   # недельный + дневной → мягче
        ("1M", "1W"):      1.5,   # месячный + недельный → ещё мягче
        ("1M", "1D"):      1.5,
    }

    @staticmethod
    def _confluence_strength(dist: float, tf_a: str, tf_b: str) -> str:
        """Сила конфлюэнции с учётом масштаба TF-пары."""
        # Кросс-TF конфлюэнции сами по себе сильнее — разные периоды сошлись
        cross_tf = {tf_a, tf_b} not in ({"1D", "1D_prev"}, {"1W", "1W_prev"})
        if dist < 0.1:
            return "VERY_STRONG"
        if dist < 0.5:
            return "STRONG" if not cross_tf else "VERY_STRONG"
        if dist < 1.0:
            return "MODERATE" if not cross_tf else "STRONG"
        return "WEAK"

    def _find_all_confluences(self, pivots_data: Dict, tolerance_percent: float = None) -> List[Dict]:
        """Конфлюэнции между всеми парами таймфреймов.
        Использует разные допуски для разных пар TF (см. _TF_TOLERANCE).
        tolerance_percent — глобальный override (для обратной совместимости вызовов с явным аргументом).
        """
        all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
        tf_pairs = [
            ("1M", "1W"), ("1M", "1D"), ("1W", "1D"),
            ("1W", "1W_prev"), ("1D", "1D_prev"),  # кросс-периодные конфлюэнции
        ]
        confluences = []

        for tf_a, tf_b in tf_pairs:
            piv_a = pivots_data.get(tf_a)
            piv_b = pivots_data.get(tf_b)
            if not piv_a or not piv_b:
                continue
            # Допуск: явный аргумент > per-pair > дефолт 0.5
            tol = (
                tolerance_percent
                if tolerance_percent is not None
                else self._TF_TOLERANCE.get((tf_a, tf_b), self._TF_TOLERANCE.get((tf_b, tf_a), 0.5))
            )
            for la in all_levels:
                if la not in piv_a:
                    continue
                pa = piv_a[la]
                for lb in all_levels:
                    if lb not in piv_b:
                        continue
                    pb = piv_b[lb]
                    if pa == 0:
                        continue
                    dist = abs((pa - pb) / pa * 100)
                    if dist <= tol:
                        confluences.append({
                            "tf_a": tf_a, "level_a": la, "price_a": pa,
                            "tf_b": tf_b, "level_b": lb, "price_b": pb,
                            # Для обратной совместимости с кодом, ожидающим weekly_level/daily_level
                            "weekly_level": la, "weekly_price": pa,
                            "daily_level": lb, "daily_price": pb,
                            "distance_percent": dist,
                            "strength": self._confluence_strength(dist, tf_a, tf_b),
                        })

        confluences.sort(key=lambda x: x["distance_percent"])
        return confluences

    def find_confluences(self, weekly_pivots: Dict, daily_pivots: Dict,
                         tolerance_percent: float = 0.3) -> List[Dict]:
        """Обратная совместимость: конфлюэнции 1W vs 1D"""
        return self._find_all_confluences(
            {"1W": weekly_pivots, "1D": daily_pivots}, tolerance_percent
        )

    # ──────────────────────────────────────────────────────
    # Утилиты анализа уровней
    # ──────────────────────────────────────────────────────

    def is_near_level(self, current_price: float, pivots: Dict[str, float],
                      threshold_percent: float = 0.5) -> Optional[Dict]:
        """Проверяет близость цены к любому уровню"""
        if not pivots or current_price <= 0:
            return None
        all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
        for key in all_levels:
            if key not in pivots:
                continue
            price = pivots[key]
            if price <= 0:
                continue
            dist = abs((current_price - price) / current_price * 100)
            if dist <= threshold_percent:
                level_type = "pivot" if key == "PP" else ("support" if "S" in key else "resistance")
                return {
                    "near_level": True,
                    "level": key,
                    "level_type": level_type,
                    "price": price,
                    "distance_percent": dist,
                    "timeframe": pivots.get("timeframe", "N/A"),
                }
        return None

    def get_nearest_levels(self, current_price: float, pivots: Dict[str, float],
                           count: int = 3) -> Dict[str, List]:
        """Ближайшие уровни поддержки и сопротивления"""
        if not pivots or current_price <= 0:
            return {"support": [], "resistance": []}
        all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
        supports, resistances = [], []
        for key in all_levels:
            price = pivots.get(key, 0)
            if price <= 0:
                continue
            dist = abs((current_price - price) / current_price * 100)
            if price < current_price:
                supports.append((key, price, dist))
            elif price > current_price:
                resistances.append((key, price, dist))
        supports.sort(key=lambda x: x[2])
        resistances.sort(key=lambda x: x[2])
        return {"support": supports[:count], "resistance": resistances[:count]}

    # ──────────────────────────────────────────────────────
    # Форматирование сообщения
    # ──────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────
    # Этап 6 — Динамический TP
    # ──────────────────────────────────────────────────────

    def get_pivot_tp(
        self,
        direction: str,
        entry_price: float,
        symbol: str,
        stop_loss: Optional[float] = None,
        min_r: float = 1.5,
    ) -> Optional[float]:
        """
        Возвращает TP как ближайший пивот в направлении сделки с R >= min_r.
        Использует кешированные пивоты — не делает API-запросов.
        direction: 'LONG' или 'SHORT'
        """
        result = self.get_pivot_tp_with_source(direction, entry_price, symbol, stop_loss, min_r)
        return result[0] if result else None

    def get_pivot_tp_with_source(
        self,
        direction: str,
        entry_price: float,
        symbol: str,
        stop_loss: Optional[float] = None,
        min_r: float = 1.5,
    ) -> Optional[tuple]:
        """
        Возвращает (tp_price, source_str) — TP и источник уровня.
        source_str формат: "pivot_1W:R1" / "pivot_1D:PP" и т.п.
        Возвращает None если подходящий уровень не найден.
        """
        if entry_price <= 0:
            return None

        # Собираем (price, source) из кеша 1M / 1W / 1D
        all_candidates: List[tuple] = []
        for tf in ("1M", "1W", "1D"):
            pivots = self.pivot_cache.get(f"{symbol}_{tf}")
            if not pivots:
                continue
            for lk in ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]:
                price = pivots.get(lk)
                if price and price > 0:
                    all_candidates.append((price, f"pivot_{tf}:{lk}"))

        if not all_candidates:
            return None

        sl_dist = None
        if stop_loss and direction == "LONG" and stop_loss < entry_price:
            sl_dist = entry_price - stop_loss
        elif stop_loss and direction == "SHORT" and stop_loss > entry_price:
            sl_dist = stop_loss - entry_price

        if direction == "LONG":
            above = sorted((p, s) for p, s in all_candidates if p > entry_price)
            if not above:
                return None
            if sl_dist and sl_dist > 0:
                for tp, src in above:
                    if (tp - entry_price) / sl_dist >= min_r:
                        return tp, src
            return above[0]

        if direction == "SHORT":
            below = sorted(((p, s) for p, s in all_candidates if p < entry_price), reverse=True)
            if not below:
                return None
            if sl_dist and sl_dist > 0:
                for tp, src in below:
                    if (entry_price - tp) / sl_dist >= min_r:
                        return tp, src
            return below[0]

        return None

    def get_tp_by_hierarchy(
        self,
        direction: str,
        entry_price: float,
        symbol: str,
        stop_loss: Optional[float] = None,
        min_r: float = 2.0,
        tolerance_pct: float = 0.3,
        impulse_high: Optional[float] = None,
        impulse_low: Optional[float] = None,
    ) -> Optional[tuple]:
        """
        TP по иерархии уровней (DEV-75): высокоэффективный → низкоэффективный.

        Порядок (по убыванию avg_R из реальной БД):
          1. 1D уровень (avg_R +1.536) — ближайший >= min_r
          2. 1W уровень
          3. Конфлюэнция 1W+1D (±tolerance_pct%)
          4. Конфлюэнция 1M+1W (avg_R -0.603) — только как дальний TP
          5. 1M уровень
          6. Любой пивот (get_pivot_tp_with_source)

        Returns: (tp_price, source_str) или None
        """
        if entry_price <= 0:
            return None

        sl_dist: Optional[float] = None
        if stop_loss and stop_loss > 0:
            if direction == "LONG" and stop_loss < entry_price:
                sl_dist = entry_price - stop_loss
            elif direction == "SHORT" and stop_loss > entry_price:
                sl_dist = stop_loss - entry_price

        def _qualifies(price: float) -> bool:
            if direction == "LONG" and price <= entry_price:
                return False
            if direction == "SHORT" and price >= entry_price:
                return False
            if sl_dist and sl_dist > 0:
                return abs(price - entry_price) / sl_dist >= min_r
            return True

        # Строим pivots_data из кеша
        pivots_data: Dict = {}
        for tf in ("1M", "1W", "1D"):
            cached = self.pivot_cache.get(f"{symbol}_{tf}")
            if cached:
                pivots_data[tf] = cached

        # DEV-75: порядок по убыванию avg_R из реальных данных БД
        # 1. 1D (avg_R=+1.536) → 2. 1W → 3. confluence 1W+1D → 4. confluence 1M+1W → 5. 1M
        # DEV-86: только R1-R3/S1-S3 — R4/R5/S4/S5 расширенные уровни редко достигаются
        all_lvls = ["PP"] + [f"R{i}" for i in range(1, 4)] + [f"S{i}" for i in range(1, 4)]

        # 1-2. Сначала 1D и 1W — самые эффективные одиночные уровни
        for tf in ("1D", "1W"):
            piv = self.pivot_cache.get(f"{symbol}_{tf}")
            if not piv:
                continue
            candidates = [
                (price, f"pivot_{tf}:{lk}")
                for lk in all_lvls
                if (price := piv.get(lk)) and price > 0 and _qualifies(price)
            ]
            if candidates:
                reverse = direction == "SHORT"
                candidates.sort(key=lambda x: x[0], reverse=reverse)
                return candidates[0]

        # 3-4. Конфлюэнции (1W+1D первой, затем 1M+1W) — используют стандартный min_r
        if len(pivots_data) >= 2:
            confluences = self._find_all_confluences(pivots_data, tolerance_pct)
            for ta, tb in (("1W", "1D"), ("1M", "1W")):
                for c in confluences:
                    if {c["tf_a"], c["tf_b"]} == {ta, tb}:
                        avg_price = (c["price_a"] + c["price_b"]) / 2.0
                        if direction == "LONG" and avg_price <= entry_price:
                            continue
                        if direction == "SHORT" and avg_price >= entry_price:
                            continue
                        if sl_dist and sl_dist > 0:
                            r_to_confluence = abs(avg_price - entry_price) / sl_dist
                            if r_to_confluence < min_r:
                                continue
                        src = f"confluence_{ta}+{tb}:{c['level_a']}≈{c['level_b']}"
                        return avg_price, src

        # 5. 1M — ЗАБЛОКИРОВАН (DEV-130: WR=4%, avg_R=-0.779, n=91 — слишком далёкий уровень)
        # pivot_1M как TP почти никогда не достигается → дренаж -0.779R на сделку

        # 6. Fib extension (ARCH-58): если есть данные импульса — 1.272 → 1.618
        # Откладывается от impulse_high/low за пределы импульса.
        # Используется как TP1 когда пивот не найден в диапазоне.
        if impulse_high and impulse_low and impulse_high > impulse_low:
            diff = impulse_high - impulse_low
            for ratio, label in ((1.272, "fib_1.272"), (1.618, "fib_1.618")):
                if direction == "LONG":
                    fib_tp = impulse_high + diff * (ratio - 1.0)
                else:
                    fib_tp = impulse_low - diff * (ratio - 1.0)
                if _qualifies(fib_tp):
                    return fib_tp, label

        return None

    def get_next_tp_by_hierarchy(
        self,
        tp1_price: float,
        direction: str,
        entry_price: float,
        symbol: str,
        stop_loss: Optional[float] = None,
        min_r: float = 2.0,
        tolerance_pct: float = 0.3,
        impulse_high: Optional[float] = None,
        impulse_low: Optional[float] = None,
    ) -> Optional[tuple]:
        """
        TP2 по иерархии — следующий пивот после TP1 (skip_price=tp1_price).
        Та же иерархия что у get_tp_by_hierarchy(), но пропускает уровни
        совпадающие с tp1_price (±tolerance_pct%) или ближе к точке входа.

        Returns: (tp_price, source_str) или None
        """
        if entry_price <= 0 or tp1_price <= 0:
            return None

        sl_dist: Optional[float] = None
        if stop_loss and stop_loss > 0:
            if direction == "LONG" and stop_loss < entry_price:
                sl_dist = entry_price - stop_loss
            elif direction == "SHORT" and stop_loss > entry_price:
                sl_dist = stop_loss - entry_price

        tol = tolerance_pct / 100.0

        def _qualifies(price: float) -> bool:
            # Должен быть в правильном направлении от точки входа
            if direction == "LONG" and price <= entry_price:
                return False
            if direction == "SHORT" and price >= entry_price:
                return False
            # Должен быть за пределами TP1 (не ближе к входу чем TP1)
            if direction == "LONG" and price <= tp1_price:
                return False
            if direction == "SHORT" and price >= tp1_price:
                return False
            # Не должен совпадать с TP1 по tolerance
            if abs(price - tp1_price) / max(tp1_price, 1e-9) < tol:
                return False
            # Должен удовлетворять min_r относительно SL
            if sl_dist and sl_dist > 0:
                return abs(price - entry_price) / sl_dist >= min_r
            return True

        pivots_data: Dict = {}
        for tf in ("1M", "1W", "1D"):
            cached = self.pivot_cache.get(f"{symbol}_{tf}")
            if cached:
                pivots_data[tf] = cached

        all_lvls = ["PP"] + [f"R{i}" for i in range(1, 4)] + [f"S{i}" for i in range(1, 4)]

        # 1-2. 1D затем 1W — собираем ВСЕ кандидаты и берём ближайший за TP1
        for tf in ("1D", "1W"):
            piv = self.pivot_cache.get(f"{symbol}_{tf}")
            if not piv:
                continue
            candidates = [
                (price, f"pivot_{tf}:{lk}")
                for lk in all_lvls
                if (price := piv.get(lk)) and price > 0 and _qualifies(price)
            ]
            if candidates:
                reverse = direction == "SHORT"
                candidates.sort(key=lambda x: x[0], reverse=reverse)
                return candidates[0]

        # 3-4. Конфлюэнции
        if len(pivots_data) >= 2:
            confluences = self._find_all_confluences(pivots_data, tolerance_pct)
            for ta, tb in (("1W", "1D"), ("1M", "1W")):
                for c in confluences:
                    if {c["tf_a"], c["tf_b"]} == {ta, tb}:
                        avg_price = (c["price_a"] + c["price_b"]) / 2.0
                        if not _qualifies(avg_price):
                            continue
                        src = f"confluence_{ta}+{tb}:{c['level_a']}≈{c['level_b']}"
                        return avg_price, src

        # 5. 1M — ЗАБЛОКИРОВАН (DEV-130: WR=4%, avg_R=-0.779 — слишком далёкий для TP2)

        # 6. Fib extension за пределами TP1
        if impulse_high and impulse_low and impulse_high > impulse_low:
            diff = impulse_high - impulse_low
            for ratio, label in ((1.618, "fib_1.618"), (2.0, "fib_2.0"), (2.618, "fib_2.618")):
                if direction == "LONG":
                    fib_tp = impulse_high + diff * (ratio - 1.0)
                else:
                    fib_tp = impulse_low - diff * (ratio - 1.0)
                if _qualifies(fib_tp):
                    return fib_tp, label

        return None

    def find_near_pivot(
        self,
        price: float,
        symbol: str,
        threshold_pct: float = 1.0,
    ) -> Optional[tuple]:
        """
        ARCH-23: возвращает (pivot_price, source_str) если цена в пределах threshold_pct%
        от любого пивотного уровня. Приоритет: 1M > 1W > 1D (старший ТФ важнее).
        Проверяет PP и S1-S3 / R1-R3.
        Один вызов на сигнал — переиспользует уже прогретый pivot_cache.
        """
        if not price or price <= 0:
            return None
        for tf in ("1M", "1W", "1D"):
            cached = self.pivot_cache.get(f"{symbol}_{tf}")
            if not cached:
                continue
            for lk in ["PP"] + [f"S{i}" for i in range(1, 4)] + [f"R{i}" for i in range(1, 4)]:
                lvl = cached.get(lk)
                if not lvl or lvl <= 0:
                    continue
                if abs(price - lvl) / price * 100 <= threshold_pct:
                    return lvl, f"{tf}:{lk}"
        return None

    def format_pivot_message(self, symbol: str, pivots_data: Dict, current_price: float) -> str:
        from core.ui.message_builder import tv_link
        from datetime import datetime as dt

        parts = [
            "📊 <b>ПИВОТНЫЕ УРОВНИ</b>",
            f"Пара: {tv_link(symbol, interval=240)}",
            f"💰 Цена: {current_price:.6f}" if current_price else "💰 Цена: н/д",
            "",
        ]

        def _render_tf(label: str, data: Dict):
            method = data.get("method", "")
            period = data.get("period_label", "")
            parts.append(f"<b>📅 {label} ({period})</b>")
            if method:
                parts.append(f"<i>Метод: {method}</i>")
            parts.append("")
            if not current_price:
                return
            parts.append("<b>🔴 Сопротивления:</b>")
            for i in range(5, 0, -1):
                k = f"R{i}"
                if k not in data:
                    continue
                v = data[k]
                diff = (v - current_price) / current_price * 100
                sign = "+" if diff >= 0 else ""
                parts.append(f"  {k}: {v:.6f} ({sign}{diff:.2f}%)")
            if "PP" in data:
                pp = data["PP"]
                diff = (pp - current_price) / current_price * 100
                parts.append(f"\n<b>⚪ PP: {pp:.6f} ({diff:+.2f}%)</b>\n")
            parts.append("<b>🟢 Поддержки:</b>")
            for i in range(1, 6):
                k = f"S{i}"
                if k not in data:
                    continue
                v = data[k]
                diff = (v - current_price) / current_price * 100
                sign = "+" if diff >= 0 else ""
                parts.append(f"  {k}: {v:.6f} ({sign}{diff:.2f}%)")
            parts.append("")

        for tf_key, tf_label in [("1M", "МЕСЯЧНЫЕ ПИВОТЫ"), ("1W", "НЕДЕЛЬНЫЕ ПИВОТЫ"), ("1D", "ДНЕВНЫЕ ПИВОТЫ")]:
            if tf_key in pivots_data:
                _render_tf(tf_label, pivots_data[tf_key])

        confluences = pivots_data.get("confluence", [])
        if confluences:
            # Приоритет: кросс-TF конфлюэнции (1M/1W/1D) выше чем same-TF (1D/1D_prev)
            _cross_tf = [c for c in confluences if {c["tf_a"], c["tf_b"]} not in ({"1D", "1D_prev"}, {"1W", "1W_prev"})]
            _same_tf  = [c for c in confluences if {c["tf_a"], c["tf_b"]} in ({"1D", "1D_prev"}, {"1W", "1W_prev"})]
            ordered = _cross_tf + _same_tf
            parts.append(f"<b>🎯 КОНФЛЮЭНЦИИ ({len(confluences)}):</b>")
            for i, c in enumerate(ordered[:5], 1):
                parts.append(
                    f"{i}. {c['tf_a']} {c['level_a']} ≈ {c['tf_b']} {c['level_b']}\n"
                    f"   Цена: {c['price_a']:.6f} ({c['strength']})"
                )
            parts.append("")

        # Предупреждение о близости к уровням (проверяем все ТФ)
        for tf_key in ("1W", "1M", "1D"):
            if tf_key in pivots_data:
                near = self.is_near_level(current_price, pivots_data[tf_key], 0.5)
                if near:
                    parts.append(f"⚠️ <b>ЦЕНА У {tf_key} УРОВНЯ {near['level']}!</b>")
                    parts.append(f"Расстояние: {near['distance_percent']:.3f}%")
                    parts.append("→ Жди подтверждения для входа!")
                    break

        parts.append("")
        parts.append(f"🕐 {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(parts)
