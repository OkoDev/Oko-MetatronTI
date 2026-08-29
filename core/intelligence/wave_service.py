# -*- coding: utf-8 -*-
"""
WaveService — волновая сфера Куба (ARCH-132, поглощает ARCH-121 и ARCH-127).

Задача поставлена 08.06.2026 и провисела 11 недельных дайджестов подряд с пометкой
«готово»: панель Куба рисовала сферу рабочей, а кода не было НИКОГДА
(`git log --diff-filter=A -- '*wave_service*'` пуст). Реализуется написанная
спецификация `docs/CUBE_SUBCUBES.md` §«Sub-куб 2: Elliott-Pivot», а не новая выдумка.

ЧТО ЭТО ДЕЛАЕТ. Считает волновую фазу на трёх ТФ и публикует её в шину, чтобы остальные
сферы могли на неё опереться: сейчас волновое состояние не видит никто, и каждый
потребитель пересчитывает разметку с нуля.

🔑 ТРЕБОВАНИЕ ЕГОРА (29.08), которого в спецификации не было:
«волны нужно в памяти держать, чтобы знать историю и иметь возможность прогнозировать
по теории». Отсюда два отличия от спеки:
  1. `history` — последние снимки разметки по символу, а не только текущий;
  2. **факт ПЕРЕСЧЁТА разметки** — отдельное событие. По канону Эллиотта слом счёта
     означает, что предыдущая разметка была неверной, и это сигнал сам по себе. Сейчас
     его не видит никто, потому что каждый прогон стирает прошлое.

🔴 ПРИЧИННОСТЬ. `find_swing_highs(series, period)` подтверждает пивот только через
`period` баров с каждой стороны (цикл идёт по `range(period, n - period)`). Значит
последние `period` баров разметки НЕ ОКОНЧАТЕЛЬНЫ. Замер лагов подтвердил это как
алгоритмическую константу, а не рыночную статистику
([[detector_lag_is_a_parameter_not_statistics]]). Сервис поэтому не выдаёт свинги
с хвоста ряда за окончательные и хранит `unconfirmed_bars` в снимке.

Синхронный вызов из scan_loop — ordering гарантирован (решение роя 4/4, 29.05.2026).
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Периоды пивотов по ТФ — из спецификации CUBE_SUBCUBES.md §Sub-куб 2
SWING_PERIOD_4H = 5
SWING_PERIOD_1H = 5
SWING_PERIOD_LTF = 3
MIN_BARS = 15
HISTORY_LEN = 64          # сколько снимков держим на символ


@dataclass
class WavePhase:
    """Фаза волнового цикла и уверенность в ней."""
    phase: str
    confidence: float


@dataclass
class WaveSnapshot:
    """Снимок разметки на момент времени — единица ПАМЯТИ волн."""
    ts: datetime
    n_down: int = 0
    n_up: int = 0
    n_down_1h: int = 0
    n_up_1h: int = 0
    n_down_ltf: int = 0
    n_up_ltf: int = 0
    phase: str = "undefined"
    confidence: float = 0.0
    unconfirmed_bars: int = 0     # сколько последних баров HTF ещё не подтверждены
    recount: bool = False         # на этом снимке счёт СЛОМАЛСЯ

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts.isoformat(), "n_down": self.n_down, "n_up": self.n_up,
            "n_down_1h": self.n_down_1h, "n_up_1h": self.n_up_1h,
            "n_down_ltf": self.n_down_ltf, "n_up_ltf": self.n_up_ltf,
            "phase": self.phase, "conf": round(self.confidence, 3),
            "unconfirmed_bars": self.unconfirmed_bars, "recount": self.recount,
        }


class WaveService:
    """
    Волновая сфера. Держит разметку ВО ВРЕМЕНИ, а не только «сейчас».

        svc = WaveService()
        phase = svc.compute_and_publish("BTC/USDT", df_4h, df_1h, df_5m, ctx_bus)
    """

    def __init__(self) -> None:
        self._history: Dict[str, deque] = {}
        self._recounts: Dict[str, int] = {}

    # ── ПАМЯТЬ ──────────────────────────────────────────────────────────
    def history(self, symbol: str) -> list[WaveSnapshot]:
        """Снимки разметки от старых к новым. Пусто, если символ ещё не считался."""
        return list(self._history.get(symbol, ()))

    def last(self, symbol: str) -> Optional[WaveSnapshot]:
        h = self._history.get(symbol)
        return h[-1] if h else None

    def recount_count(self, symbol: str) -> int:
        """Сколько раз разметка ломалась. Рост счётчика — сигнал сам по себе."""
        return self._recounts.get(symbol, 0)

    @staticmethod
    def _is_recount(prev: WaveSnapshot, cur: WaveSnapshot) -> bool:
        """
        Счёт СЛОМАЛСЯ — предыдущая разметка была неверной.

        Считаем сломом ровно две вещи, обе следуют из канона, а не из вкуса:
          · номер волны УПАЛ больше чем на 1 за такт — значит вершины, на которых он
            держался, пересчитаны (нормальное развитие даёт +1 или сброс в 0);
          · фаза сменилась «через голову» — из финала волны 5 сразу в середину волны 3
            без промежуточной коррекции.
        """
        if cur.n_down < prev.n_down - 1 or cur.n_up < prev.n_up - 1:
            return True
        return prev.phase == "wave5_final" and cur.phase == "wave3_mid"

    # ── РАСЧЁТ ──────────────────────────────────────────────────────────
    def compute_and_publish(self, sym: str, df_4h, df_1h, df_ltf,
                            ctx_bus, event_bus=None) -> WavePhase:
        from core.indicators.indicators import (calculate_n_down, calculate_n_up,
                                                find_swing_highs, find_swing_lows)

        snap: Dict[str, Any] = {}
        unconfirmed = 0

        def _pair(df, period: int) -> tuple[int, int]:
            sh = find_swing_highs(df["high"], period=period)
            sl = find_swing_lows(df["low"], period=period)
            return calculate_n_down(sh), calculate_n_up(sl)

        if df_4h is not None and len(df_4h) >= MIN_BARS:
            snap["n_down"], snap["n_up"] = _pair(df_4h, SWING_PERIOD_4H)
            unconfirmed = SWING_PERIOD_4H      # хвост HTF ещё не подтверждён
        if df_1h is not None and len(df_1h) >= MIN_BARS:
            snap["n_down_1h"], snap["n_up_1h"] = _pair(df_1h, SWING_PERIOD_1H)
        if df_ltf is not None and len(df_ltf) >= MIN_BARS:
            snap["n_down_ltf"], snap["n_up_ltf"] = _pair(df_ltf, SWING_PERIOD_LTF)

        prev_state = ctx_bus.get(sym) if ctx_bus is not None else None
        # 🔴 Спецификация берёт `htf_price_dir` из шины, но такого поля НЕ СУЩЕСТВУЕТ
        # нигде в проекте (проверено грепом 29.08: единственное упоминание — здесь).
        # По спеке сервис всегда возвращал бы `undefined` — тот же класс, что панель
        # Куба, рисующая несуществующие сферы. Считаем направление САМИ, по определению
        # из `docs/ENCYCLOPEDIA.md`: «направление HTF последних 5 баров: up/down/flat».
        snap["htf_dir"] = self._htf_dir(df_4h if df_4h is not None else df_1h)
        phase = self._detect_phase(snap, prev_state)

        cur = WaveSnapshot(ts=datetime.now(timezone.utc),
                           n_down=snap.get("n_down", 0), n_up=snap.get("n_up", 0),
                           n_down_1h=snap.get("n_down_1h", 0), n_up_1h=snap.get("n_up_1h", 0),
                           n_down_ltf=snap.get("n_down_ltf", 0),
                           n_up_ltf=snap.get("n_up_ltf", 0),
                           phase=phase.phase, confidence=phase.confidence,
                           unconfirmed_bars=unconfirmed)

        prev = self.last(sym)
        if prev is not None and self._is_recount(prev, cur):
            cur.recount = True
            self._recounts[sym] = self._recounts.get(sym, 0) + 1
            logger.info("[Wave] %s СЧЁТ ПЕРЕСЧИТАН: n_down %d→%d · фаза %s→%s (всего %d)",
                        sym, prev.n_down, cur.n_down, prev.phase, cur.phase,
                        self._recounts[sym])

        self._history.setdefault(sym, deque(maxlen=HISTORY_LEN)).append(cur)

        if ctx_bus is not None:
            fields = dict(elliott_n_down=cur.n_down, elliott_n_up=cur.n_up,
                          elliott_phase=cur.phase, elliott_conf=cur.confidence,
                          wave_snap=cur.as_dict(),
                          wave_recounts=self._recounts.get(sym, 0),
                          wave_updated_at=cur.ts)
            if cur.recount:
                fields["wave_recount_ts"] = cur.ts
            ctx_bus.update(sym, **fields)

        prev_phase = getattr(prev_state, "elliott_phase", None) if prev_state else None
        if event_bus is not None and phase.phase != prev_phase:
            try:
                event_bus.publish_nowait("wave_phase_changed",
                                         {"sym": sym, "phase": phase.phase,
                                          "conf": phase.confidence,
                                          "recount": cur.recount})
            except Exception:                       # noqa: BLE001
                logger.debug("[Wave] event_bus недоступен, фаза только в шине")
        return phase

    @staticmethod
    def _htf_dir(df, bars: int = 5) -> str:
        """
        Направление старшего ТФ за последние `bars` баров: up / down / flat.

        Порог — 0.5 ATR за окно, а не фиксированный процент: иначе на спокойной монете
        любой шорох читается как тренд, а на волатильной настоящий ход теряется
        ([[twins_15m_stabilized_by_measure]] — константа в одних единицах не переносится
        между инструментами).
        """
        if df is None or len(df) < bars + 2:
            return "flat"
        try:
            c = df["close"].values
            hi, lo = df["high"].values, df["low"].values
            move = float(c[-1] - c[-1 - bars])
            rng = float(np.mean(hi[-bars:] - lo[-bars:]))
            if rng <= 0:
                return "flat"
            if move > 0.5 * rng:
                return "up"
            if move < -0.5 * rng:
                return "down"
        except Exception:                       # noqa: BLE001
            return "flat"
        return "flat"

    # ── ФАЗА ────────────────────────────────────────────────────────────
    def _detect_phase(self, snap: Dict[str, Any], prev_state) -> WavePhase:
        """
        Правила из спецификации CUBE_SUBCUBES.md §Sub-куб 2 (эмпирика ретробэктеста
        n=367 ATRChange SHORT, май 2026): n_down 2-3 = волна 3 (лучший вход),
        n_down ≥ 4 = волна 5 или ловушка, CHoCH при n_down ≥ 3 = конец импульса → ABC.
        """
        n_down = int(snap.get("n_down", 0))
        htf_dir = snap.get("htf_dir") or getattr(prev_state, "htf_price_dir", None) or "flat"
        smc = getattr(prev_state, "smc_snap", None) or {}
        has_choch = bool(smc.get("choch"))
        has_div = bool(getattr(prev_state, "active_divergence", None))

        if htf_dir == "up" and has_choch and n_down >= 3:
            return WavePhase("ABC_waveB", 0.80)
        if htf_dir == "down" and has_div and n_down >= 3:
            return WavePhase("wave5_final", 0.75 + (0.10 if has_choch else 0.0))
        if htf_dir == "down" and n_down == 0:
            return WavePhase("impulse_start", 0.65)
        if htf_dir == "down" and 1 <= n_down <= 3 and not has_div:
            return WavePhase("wave3_mid", 0.55 + n_down * 0.05)
        if htf_dir == "down" and n_down >= 4 and not has_div:
            return WavePhase("wave3_mid", 0.50)
        return WavePhase("undefined", 0.30)
