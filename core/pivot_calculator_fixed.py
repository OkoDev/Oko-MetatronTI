"""
Модуль расчета МЕСЯЧНЫХ, НЕДЕЛЬНЫХ и ДНЕВНЫХ пивотов.
Уровни фиксируются на весь период (месяц/неделю/день) по UTC:
  - Месячные: 1-е число 00:00 UTC (= 03:00 МСК)
  - Недельные: Пн 00:00 UTC (= Пн 03:00 МСК)
  - Дневные:   00:00 UTC каждый день (= 03:00 МСК)
"""
import asyncio
import logging
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

    def __init__(self):
        # {cache_key: {**pivots, "period_start": datetime, ...}}
        self.pivot_cache: Dict[str, Dict] = {}

    # ──────────────────────────────────────────────────────
    # Формулы
    # ──────────────────────────────────────────────────────

    def calculate_traditional_pivots(self, high: float, low: float, close: float) -> Dict[str, float]:
        """Traditional Pivot Points по формулам Pine Script"""
        pp = (high + low + close) / 3.0
        return {
            "PP": pp,
            "S1": pp * 2.003 - high,
            "S2": pp - (high - low),
            "S3": pp * 2 - (2 * high - low),
            "S4": pp * 3 - (3 * high - low),
            "S5": pp * 4 - (4 * high - low),
            "R1": pp * 1.997 - low,
            "R2": pp + (high - low),
            "R3": pp * 2 + (high - 2 * low),
            "R4": pp * 3 + (high - 3 * low),
            "R5": pp * 4 + (high - 4 * low),
        }

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

        # Метод 1: из дневных свечей
        pivots = await self._weekly_from_1d(symbol, data_collector, prev_week_start, prev_week_end)
        # Метод 2 (fallback): из 4h свечей
        if not pivots:
            pivots = await self._weekly_from_4h(symbol, data_collector, prev_week_start, prev_week_end)

        if pivots:
            pivots["period_start"] = week_start
            self.pivot_cache[cache_key] = pivots
            logger.info(f"✅ Недельные пивоты {symbol}: PP={pivots['PP']:.4f} ({pivots.get('period_label','')})")
            return pivots

        logger.warning(f"❌ Не удалось получить недельные пивоты для {symbol}")
        return None

    async def _weekly_from_1d(self, symbol, data_collector, week_start, week_end) -> Optional[Dict]:
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=14)
            if df is None or len(df) < 5:
                return None
            df = _df_with_datetime(df)
            week = df[(df["datetime"] >= week_start) & (df["datetime"] < week_end)]
            if len(week) < 3:
                return None
            pivots = self.calculate_traditional_pivots(
                week["high"].max(), week["low"].min(), week["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "1W",
                "method": "aggregated_from_1d",
                "period_label": week_start.strftime("%Y-W%V"),
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

        try:
            # Метод 1: из дневных свечей
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=5)
            if df is not None and len(df) >= 2:
                df = _df_with_datetime(df)
                prev = df[(df["datetime"] >= prev_day_start) & (df["datetime"] < prev_day_end)]
                if not prev.empty:
                    pivots = self.calculate_traditional_pivots(
                        prev["high"].max(), prev["low"].min(), prev["close"].iloc[-1]
                    )
                    pivots.update({
                        "timeframe": "1D",
                        "method": "direct_1d",
                        "period_start": day_start,
                        "period_label": prev_day_start.strftime("%Y-%m-%d"),
                        "timestamp": datetime.now(timezone.utc),
                    })
                    self.pivot_cache[cache_key] = pivots
                    logger.info(f"✅ Дневные пивоты {symbol}: PP={pivots['PP']:.4f} ({pivots['period_label']})")
                    return pivots

            # Метод 2 (fallback): из 1h свечей
            df_1h = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=30)
            if df_1h is None or len(df_1h) < 24:
                return None
            df_1h = _df_with_datetime(df_1h)
            prev_1h = df_1h[(df_1h["datetime"] >= prev_day_start) & (df_1h["datetime"] < prev_day_end)]
            if len(prev_1h) < 12:
                return None
            pivots = self.calculate_traditional_pivots(
                prev_1h["high"].max(), prev_1h["low"].min(), prev_1h["close"].iloc[-1]
            )
            pivots.update({
                "timeframe": "1D",
                "method": "aggregated_from_1h",
                "period_start": day_start,
                "period_label": prev_day_start.strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc),
            })
            self.pivot_cache[cache_key] = pivots
            logger.info(f"✅ Дневные пивоты {symbol} (из 1h): PP={pivots['PP']:.4f}")
            return pivots

        except Exception:
            logger.exception(f"Ошибка дневных пивотов для {symbol}")
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

        # Конфлюэнции между всеми доступными уровнями
        results["confluence"] = self._find_all_confluences(results)
        if results["confluence"]:
            logger.info(f"🎯 {len(results['confluence'])} конфлюэнций для {symbol}")

        return results

    # ──────────────────────────────────────────────────────
    # Конфлюэнции
    # ──────────────────────────────────────────────────────

    def _find_all_confluences(self, pivots_data: Dict, tolerance_percent: float = 0.3) -> List[Dict]:
        """Конфлюэнции между всеми парами таймфреймов"""
        all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
        tf_pairs = [("1M", "1W"), ("1M", "1D"), ("1W", "1D")]
        confluences = []

        for tf_a, tf_b in tf_pairs:
            piv_a = pivots_data.get(tf_a)
            piv_b = pivots_data.get(tf_b)
            if not piv_a or not piv_b:
                continue
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
                    if dist <= tolerance_percent:
                        confluences.append({
                            "tf_a": tf_a, "level_a": la, "price_a": pa,
                            "tf_b": tf_b, "level_b": lb, "price_b": pb,
                            # Для обратной совместимости с кодом, ожидающим weekly_level/daily_level
                            "weekly_level": la, "weekly_price": pa,
                            "daily_level": lb, "daily_price": pb,
                            "distance_percent": dist,
                            "strength": "VERY_STRONG" if dist < 0.1 else "STRONG",
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

    def format_pivot_message(self, symbol: str, pivots_data: Dict, current_price: float) -> str:
        from core.message_builder import tv_link
        from datetime import datetime as dt

        parts = [
            "📊 <b>ПИВОТНЫЕ УРОВНИ</b>",
            f"Пара: {tv_link(symbol, interval=240)}",
            f"💰 Цена: {current_price:.6f}",
            "",
        ]

        def _render_tf(label: str, data: Dict):
            method = data.get("method", "")
            period = data.get("period_label", "")
            parts.append(f"<b>📅 {label} ({period})</b>")
            if method:
                parts.append(f"<i>Метод: {method}</i>")
            parts.append("")
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
            parts.append(f"<b>🎯 КОНФЛЮЭНЦИИ ({len(confluences)}):</b>")
            for i, c in enumerate(confluences[:3], 1):
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
