"""
Confluence State Machine — Шаг 2 (ARCH-03).

Заменяет Lookback Scanner на покадровый State Machine per symbol.
Условия проверяются последовательно по мере поступления новых баров.

Переходы состояний:
  LONG:   IDLE → WT_ZONE → TSL_CROSS → NEAR_PIVOT → DIVERGENCE → SIGNAL
  SHORT:  IDLE → WT_ZONE → TSL_CROSS → NEAR_PIVOT → DIVERGENCE → SIGNAL

Таймаут: 48 часов с момента входа в первое не-IDLE состояние.
Хранение: in-memory dict + опционально SQLite таблица confluence_states.
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

from core.indicators.indicators import calculate_trend, calculate_wt
from core.signals.signal_models import SignalData, SignalType, SignalDirection
from core.confluence.confluence_scanner import (  # ARCH-54: прямой путь (stub не экспортирует _private)
    _check_near_support, _check_near_resistance,
    _check_bullish_divergence_wt, _check_bearish_divergence_wt,
    _make_signal, _get_cfg,
    _DEFAULT_WT_OS, _DEFAULT_WT_OB,
    _DEFAULT_MIN_STRENGTH, _DEFAULT_DIV_MIN_BARS,
    _SCORE_WT_ZONE,
)
from core.signals.wt_15m_reversal_scanner import (  # ARCH-54: прямой путь (stub не экспортирует _private)
    _SCORE_WT_CROSS_IN_ZONE, _SCORE_WT_CROSS_OUT_ZONE,
    _SCORE_TSL_CROSS, _SCORE_PIVOT_TOUCH, _SCORE_DIVERGENCE,
    _DEFAULT_PIVOT_TOUCH_PCT,
)

logger = logging.getLogger(__name__)

STATE_TIMEOUT_HOURS = 48


class ConfluenceState(str, Enum):
    IDLE = "IDLE"
    WT_ZONE = "WT_ZONE"        # WT вошёл в OS (LONG) или OB (SHORT)
    TSL_CROSS = "TSL_CROSS"    # TSL пересёк в нужном направлении
    NEAR_PIVOT = "NEAR_PIVOT"  # Цена касалась pivot-уровня
    DIVERGENCE = "DIVERGENCE"  # Дивергенция WT подтверждена
    SIGNAL = "SIGNAL"          # Сигнал выдан → сбрасываем в IDLE


@dataclass
class SymbolDirectionState:
    """Состояние State Machine для одного символа + направления."""
    symbol: str
    direction: str           # "LONG" | "SHORT"
    state: ConfluenceState = ConfluenceState.IDLE
    entered_at: Optional[datetime] = None   # когда вошли в WT_ZONE (старт таймаута)
    factors: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    score: int = 0
    last_bar_time: Optional[int] = None    # ms, для идемпотентности

    def is_timed_out(self, now: Optional[datetime] = None) -> bool:
        if self.state == ConfluenceState.IDLE or self.entered_at is None:
            return False
        now = now or datetime.now(tz=timezone.utc)
        entered = self.entered_at
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)
        return (now - entered) > timedelta(hours=STATE_TIMEOUT_HOURS)

    def reset(self) -> None:
        self.state = ConfluenceState.IDLE
        self.entered_at = None
        self.factors = []
        self.data = {}
        self.score = 0

    def add_factor(self, name: str, pts: int, extra: Dict[str, Any] = None) -> None:
        if name not in self.factors:
            self.factors.append(name)
            self.score += pts
        if extra:
            self.data.update(extra)


class ConfluenceStateMachine:
    """
    Покадровый State Machine для confluence-сетапов.

    Использование:
        sm = ConfluenceStateMachine(db_path="confluence_states.db")
        signal = sm.update(symbol, df_15m, df_1h, pivot_cache, cfg)
        if signal:
            # отправить алерт
    """

    def __init__(self, db_path: Optional[str] = None):
        # {symbol: {"LONG": SymbolDirectionState, "SHORT": SymbolDirectionState}}
        self._states: Dict[str, Dict[str, SymbolDirectionState]] = {}
        self._db_path = db_path
        if db_path:
            self._init_db(db_path)

    # ── Публичный API ──────────────────────────────────────────────────────────

    def update(
        self,
        symbol: str,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame],
        pivot_cache: Dict[str, Any],
        cfg=None,
    ) -> List[SignalData]:
        """
        Обновляет состояние для символа на основе текущих данных.
        Возвращает список SignalData (обычно пустой или 1 сигнал).
        """
        results: List[SignalData] = []

        conf_cfg = _get_cfg(cfg)
        if not conf_cfg.get("enabled", True):
            return results

        if df_15m is None or len(df_15m) < 55:
            return results

        # Рассчитываем индикаторы один раз для обоих направлений
        _factor = 1.0
        if cfg is not None and hasattr(cfg, "get"):
            _factor = float(cfg.get("analysis.indicators.trend.factor", 1.0))
        _atr_p = 43
        if cfg is not None and hasattr(cfg, "get"):
            _atr_p = int(cfg.get("analysis.indicators.trend.atr_period", 43))

        try:
            df = calculate_wt(df_15m.copy(), n1=10, n2=21)
            df = calculate_trend(df, atr_period=_atr_p, factor=_factor)
        except Exception as e:
            logger.debug("[csm] indicator error %s: %s", symbol, e)
            return results

        bar_time = int(df["time"].iloc[-1]) if "time" in df.columns else 0

        # Тренд 1h
        trend_1h = 0
        if df_1h is not None and len(df_1h) >= 50:
            try:
                df_1h_t = calculate_trend(df_1h.copy(), atr_period=_atr_p, factor=_factor)
                trend_1h = int(df_1h_t["trend"].iloc[-1])
            except Exception:
                pass

        # Параметры из конфига
        wt_os_thr    = float(conf_cfg.get("wt_os_threshold", _DEFAULT_WT_OS))
        wt_ob_thr    = float(conf_cfg.get("wt_ob_threshold", _DEFAULT_WT_OB))
        pivot_pct    = float(conf_cfg.get("pivot_touch_pct", _DEFAULT_PIVOT_TOUCH_PCT))
        min_strength = int(conf_cfg.get("min_strength", _DEFAULT_MIN_STRENGTH))
        div_min_bars = int(conf_cfg.get("div_min_bars", _DEFAULT_DIV_MIN_BARS))
        cross_fresh  = int(conf_cfg.get("cross_fresh_bars", 8))

        daily_pivots = pivot_cache.get(f"{symbol}_1D") or {}
        current_price = float(df["close"].iloc[-1])

        for direction in ("LONG", "SHORT"):
            st = self._get_state(symbol, direction)

            # Идемпотентность: не пересчитываем дважды на одном баре
            if bar_time and st.last_bar_time == bar_time:
                continue
            st.last_bar_time = bar_time

            # Таймаут → сброс
            if st.is_timed_out():
                logger.info("[csm] %s %s timeout → IDLE", symbol, direction)
                st.reset()

            sig = self._step(
                st, df, symbol, direction,
                wt_os_thr, wt_ob_thr, pivot_pct, min_strength, div_min_bars,
                cross_fresh, daily_pivots, pivot_cache,
                current_price, trend_1h, cfg,
            )
            if sig:
                results.append(sig)
                if self._db_path:
                    self._persist(st)

        return results

    def get_state(self, symbol: str, direction: str) -> ConfluenceState:
        return self._get_state(symbol, direction).state

    def get_all_states(self) -> Dict[str, Dict[str, str]]:
        """Возвращает текущие состояния всех символов (для мониторинга)."""
        return {
            sym: {d: s.state.value for d, s in dirs.items()}
            for sym, dirs in self._states.items()
        }

    # ── Шаг State Machine ──────────────────────────────────────────────────────

    def _step(
        self,
        st: SymbolDirectionState,
        df: pd.DataFrame,
        symbol: str,
        direction: str,
        wt_os_thr: float, wt_ob_thr: float, pivot_pct: float,
        min_strength: int, div_min_bars: int, cross_fresh: int,
        daily_pivots: Dict, pivot_cache: Dict,
        current_price: float, trend_1h: int, cfg,
    ) -> Optional[SignalData]:
        """
        Один шаг автомата для direction. Возвращает SignalData или None.

        Новая логика (DEV-19): 4 фактора, 8 баров, gate WT+TSL обязательны.
          Gate 1 (WT_ZONE): wt1 < wt_os_thr (LONG) или > wt_ob_thr (SHORT)
          Gate 2 (TSL_CROSS): TSL пересекает в нужном направлении
          Опционально: PIVOT_TOUCH (+25) и DIVERGENCE (+20) накапливаются
          Триггер: WT_CROSS — вычисляем итоговый score, если >= min → SIGNAL
        """
        is_long = direction == "LONG"
        # Большое окно для divergence/pivot detection
        window = df.iloc[-min(len(df), 50):].reset_index(drop=True)
        # Малое окно для TSL/WT кроссов (cross_fresh баров)
        cross_window = df.iloc[-min(len(df), cross_fresh + 1):].reset_index(drop=True)

        wt1_arr = cross_window["wt1"].values if "wt1" in cross_window.columns else np.array([])
        wt2_arr = cross_window["wt2"].values if "wt2" in cross_window.columns else np.array([])
        trend_arr = cross_window["trend"].values if "trend" in cross_window.columns else np.array([])
        trendup_arr = cross_window["trendup"].values if "trendup" in cross_window.columns else np.array([])
        trenddown_arr = cross_window["trenddown"].values if "trenddown" in cross_window.columns else np.array([])
        close_arr = cross_window["close"].values if "close" in cross_window.columns else np.array([])

        wt1_last = float(wt1_arr[-1]) if len(wt1_arr) else 0.0

        # ── IDLE: ждём входа в OS/OB зону ─────────────────────────────────────
        if st.state == ConfluenceState.IDLE:
            in_zone = (is_long and wt1_last < wt_os_thr) or \
                      (not is_long and wt1_last > wt_ob_thr)
            if in_zone:
                st.state = ConfluenceState.WT_ZONE
                st.entered_at = datetime.now(tz=timezone.utc)
                st.factors = []
                st.data = {}
                st.score = 0
                factor = "WT_OS" if is_long else "WT_OB"
                st.add_factor(factor, _SCORE_WT_ZONE, {
                    "wt_min" if is_long else "wt_max": round(wt1_last, 1)
                })
                logger.debug("[csm] %s %s: IDLE→WT_ZONE wt1=%.1f", symbol, direction, wt1_last)
            return None

        # ── WT_ZONE: ждём TSL_CROSS (gate 2) ──────────────────────────────────
        if st.state == ConfluenceState.WT_ZONE:
            # Вышли в противоположную зону → сброс
            if is_long and wt1_last > wt_ob_thr:
                st.reset()
                return None
            if not is_long and wt1_last < wt_os_thr:
                st.reset()
                return None

            tsl_cross = self._detect_tsl_cross(
                trend_arr, trenddown_arr, trendup_arr, close_arr, cross_fresh
            )
            if (is_long and tsl_cross == "UP") or (not is_long and tsl_cross == "DOWN"):
                st.state = ConfluenceState.TSL_CROSS
                factor = "TSL_CROSS_UP" if is_long else "TSL_CROSS_DOWN"
                st.add_factor(factor, _SCORE_TSL_CROSS)
                logger.debug("[csm] %s %s: WT_ZONE→TSL_CROSS", symbol, direction)
            return None

        # ── TSL_CROSS / NEAR_PIVOT / DIVERGENCE: накапливаем, ждём WT_CROSS ───
        if st.state in (
            ConfluenceState.TSL_CROSS,
            ConfluenceState.NEAR_PIVOT,
            ConfluenceState.DIVERGENCE,
        ):
            # Опциональный фактор: PIVOT_TOUCH (0.15%, однократно)
            piv_factor = "NEAR_SUPPORT" if is_long else "NEAR_RESISTANCE"
            if piv_factor not in st.factors:
                if is_long:
                    hit, desc = _check_near_support(window, daily_pivots, pivot_cache, symbol, pivot_pct)
                else:
                    hit, desc = _check_near_resistance(window, daily_pivots, pivot_cache, symbol, pivot_pct)
                if hit:
                    st.add_factor(piv_factor, _SCORE_PIVOT_TOUCH, {"pivot_hit": desc})
                    if st.state == ConfluenceState.TSL_CROSS:
                        st.state = ConfluenceState.NEAR_PIVOT
                        logger.debug("[csm] %s %s: TSL_CROSS→NEAR_PIVOT %s", symbol, direction, desc)

            # Опциональный фактор: DIVERGENCE (однократно)
            if "WT_DIVERGENCE" not in st.factors:
                if is_long:
                    div_ok, div_desc = _check_bullish_divergence_wt(window, div_min_bars)
                else:
                    div_ok, div_desc = _check_bearish_divergence_wt(window, div_min_bars)
                if div_ok:
                    st.add_factor("WT_DIVERGENCE", _SCORE_DIVERGENCE, {"div_desc": div_desc})
                    if st.state in (ConfluenceState.TSL_CROSS, ConfluenceState.NEAR_PIVOT):
                        st.state = ConfluenceState.DIVERGENCE
                        logger.debug("[csm] %s %s: →DIVERGENCE", symbol, direction)

            # Финальный триггер: WT_CROSS
            wt_cross = self._detect_wt_cross(wt1_arr, wt2_arr, wt_os_thr, wt_ob_thr, cross_fresh)
            cross_ok = (is_long and wt_cross == "UP") or (not is_long and wt_cross == "DOWN")

            if not cross_ok:
                return None

            # WT_CROSS в зоне OS/OB → более высокий балл
            # _detect_wt_cross возвращает UP/DOWN только при in_os/in_ob → всегда IN_ZONE
            factor = "WT_CROSS_UP" if is_long else "WT_CROSS_DOWN"
            st.add_factor(factor, _SCORE_WT_CROSS_IN_ZONE)

            total_score = st.score
            logger.info(
                "[csm] %s %s: →SIGNAL score=%d factors=%s",
                symbol, direction, total_score, st.factors,
            )

            if total_score < min_strength:
                logger.debug(
                    "[csm] %s %s: score %d < min %d, reset",
                    symbol, direction, total_score, min_strength,
                )
                st.reset()
                return None

            sig = _make_signal(
                symbol,
                SignalDirection.LONG if is_long else SignalDirection.SHORT,
                total_score,
                list(st.factors),
                dict(st.data),
                lookback_bars=cross_fresh,
                current_price=current_price,
            )
            if sig.data:
                sig.data["source"] = "state_machine"

            st.state = ConfluenceState.SIGNAL
            st.reset()  # сигнал выдан → возвращаемся в IDLE
            return sig

        return None

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _get_state(self, symbol: str, direction: str) -> SymbolDirectionState:
        if symbol not in self._states:
            self._states[symbol] = {}
        if direction not in self._states[symbol]:
            self._states[symbol][direction] = SymbolDirectionState(symbol=symbol, direction=direction)
        return self._states[symbol][direction]

    @staticmethod
    def _detect_tsl_cross(
        trend_arr: np.ndarray,
        trenddown_arr: np.ndarray,
        trendup_arr: np.ndarray,
        close_arr: np.ndarray,
        fresh_bars: int,
    ) -> Optional[str]:
        """Последний подтверждённый TSL кросс в fresh_bars барах. Возвращает "UP"|"DOWN"|None."""
        n = len(trend_arr)
        start = max(1, n - fresh_bars)
        result = None
        for i in range(start, n):
            prev = trend_arr[i - 1]
            curr = trend_arr[i]
            if prev == -1 and curr == 1:
                prev_td = trenddown_arr[i - 1] if not np.isnan(trenddown_arr[i - 1]) else None
                if prev_td and not np.isnan(close_arr[i]) and close_arr[i] > prev_td:
                    result = "UP"
            elif prev == 1 and curr == -1:
                prev_tu = trendup_arr[i - 1] if not np.isnan(trendup_arr[i - 1]) else None
                if prev_tu and not np.isnan(close_arr[i]) and close_arr[i] < prev_tu:
                    result = "DOWN"
        return result

    @staticmethod
    def _detect_wt_cross(
        wt1_arr: np.ndarray,
        wt2_arr: np.ndarray,
        wt_os_thr: float,
        wt_ob_thr: float,
        fresh_bars: int,
    ) -> Optional[str]:
        """Последний WT кросс в OS/OB зоне в fresh_bars барах. Возвращает "UP"|"DOWN"|None."""
        if len(wt1_arr) < 2 or len(wt2_arr) < 2:
            return None
        n = len(wt1_arr)
        start = max(1, n - fresh_bars)
        result = None
        for i in range(start, n):
            in_os = wt1_arr[i - 1] < wt_os_thr
            in_ob = wt1_arr[i - 1] > wt_ob_thr
            cross_up   = wt1_arr[i - 1] <= wt2_arr[i - 1] and wt1_arr[i] > wt2_arr[i]
            cross_down = wt1_arr[i - 1] >= wt2_arr[i - 1] and wt1_arr[i] < wt2_arr[i]
            if cross_up and in_os:
                result = "UP"
            elif cross_down and in_ob:
                result = "DOWN"
        return result

    # ── SQLite persistence ─────────────────────────────────────────────────────

    def _init_db(self, db_path: str) -> None:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confluence_states (
                        symbol      TEXT NOT NULL,
                        direction   TEXT NOT NULL,
                        state       TEXT NOT NULL,
                        entered_at  TEXT,
                        score       INTEGER DEFAULT 0,
                        factors     TEXT DEFAULT '',
                        data_json   TEXT DEFAULT '{}',
                        updated_at  TEXT NOT NULL,
                        PRIMARY KEY (symbol, direction)
                    )
                """)
                conn.commit()
            logger.debug("[csm] SQLite инициализирован: %s", db_path)
        except Exception as e:
            logger.warning("[csm] Не удалось инициализировать SQLite: %s", e)

    def _persist(self, st: SymbolDirectionState) -> None:
        if not self._db_path:
            return
        import json
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO confluence_states
                        (symbol, direction, state, entered_at, score, factors, data_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    st.symbol,
                    st.direction,
                    st.state.value,
                    st.entered_at.isoformat() if st.entered_at else None,
                    st.score,
                    "|".join(st.factors),
                    json.dumps(st.data, default=str),
                    datetime.now(tz=timezone.utc).isoformat(),
                ))
                conn.commit()
        except Exception as e:
            logger.warning("[csm] Ошибка записи состояния в SQLite: %s", e)

    def load_from_db(self) -> int:
        """Загружает состояния из SQLite в память. Возвращает кол-во загруженных записей."""
        if not self._db_path:
            return 0
        import json
        count = 0
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT symbol, direction, state, entered_at, score, factors, data_json FROM confluence_states"
                ).fetchall()
            for sym, d, state_str, entered_at_str, score, factors_str, data_json_str in rows:
                try:
                    st = self._get_state(sym, d)
                    st.state = ConfluenceState(state_str)
                    st.entered_at = datetime.fromisoformat(entered_at_str).replace(tzinfo=timezone.utc) \
                        if entered_at_str else None
                    st.score = score or 0
                    st.factors = [f for f in factors_str.split("|") if f] if factors_str else []
                    st.data = json.loads(data_json_str) if data_json_str else {}
                    # Проверяем таймаут при загрузке
                    if st.is_timed_out():
                        st.reset()
                    count += 1
                except Exception as e:
                    logger.debug("[csm] Ошибка загрузки строки %s %s: %s", sym, d, e)
        except Exception as e:
            logger.warning("[csm] Ошибка загрузки из SQLite: %s", e)
        logger.info("[csm] Загружено %d состояний из %s", count, self._db_path)
        return count
