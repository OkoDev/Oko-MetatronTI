"""
MTF Interpreter — автономный интерпретатор мульти-таймфреймовых данных.

Анализирует согласованность всех 7 ТФ (3m/5m/15m/45m/1h/4h/1d) и принимает
решение о направлении и точке входа на основе:
  1. TF Alignment Score — взвешенная доля ТФ в одном направлении
  2. Senior TF gate — минимум 2 из 3 старших ТФ (1h/4h/1d) подтверждают
  3. Entry TF selection — самый быстрый ТФ с WT cross в нужном направлении
  4. Zone filter — не входим в экстремальную зону на entry TF
  5. Strength = base + senior_bonus + cross_bonus - regime_penalty

Использует данные из collect_mtf_data() (mtf_checker.py):
  snapshot[tf] = {trend: "UP"/"DOWN", wt1: float, wt2: float, zone: "OB"/"OS"/"N", wt_cross: -1/0/1}

Phase 1: rule-based.
Phase 2 (будущее): ML RandomForest на 28 фичах (4 фичи × 7 ТФ) после накопления MTF-снапшотов.
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.signal_models import SignalData, SignalType, SignalDirection, MTFContext

logger = logging.getLogger(__name__)

# ── Веса ТФ (сумма = 73) ──────────────────────────────────────────────────────
_TF_WEIGHTS: Dict[str, int] = {
    "1d":  20,
    "4h":  15,
    "1h":  12,
    "45m": 10,
    "15m":  8,
    "5m":   5,
    "3m":   3,
}
_TOTAL_WEIGHT = sum(_TF_WEIGHTS.values())  # 73

# ── Старшие ТФ (gate) ─────────────────────────────────────────────────────────
_SENIOR_TFS = ("1h", "4h", "1d")

# ── Кандидаты для entry_tf (от быстрого к медленному, 3m слишком шумный) ──────
_ENTRY_TF_CANDIDATES = ("5m", "15m", "45m", "1h")

# ── Пороги ────────────────────────────────────────────────────────────────────
_ALIGNMENT_THRESHOLD = 65    # % согласованных ТФ для сигнала
_MIN_SENIOR_MATCH = 2        # минимум совпадений среди senior TFs
_SENIOR_FULL_BONUS = 10      # бонус если все 3 старших согласны
_CROSS_BONUS = 10            # бонус за WT cross на entry_tf
_RANGE_PENALTY = 15          # штраф за RANGE режим


def interpret(
    snapshot: Dict[str, Dict[str, Any]],
    regime: Optional[str] = None,
    cfg=None,
) -> Optional[SignalData]:
    """
    Интерпретирует MTF-снапшот и возвращает SignalData или None.

    Args:
        snapshot: dict из collect_mtf_data() → {tf: {trend, wt1, wt2, zone, wt_cross}}
        regime:   строка режима из MarketRegimeClassifier ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL")
        cfg:      объект конфига (не используется в Phase 1, зарезервирован для ML)

    Returns:
        SignalData с signal_type=MTF_BIAS или None если условия не выполнены
    """
    if not snapshot:
        return None

    try:
        # ── Шаг 1: TF Alignment Score ────────────────────────────────────────
        bull_weight = 0
        bear_weight = 0
        available_weight = 0

        for tf, weight in _TF_WEIGHTS.items():
            tf_data = snapshot.get(tf)
            if not tf_data:
                continue
            available_weight += weight
            trend = tf_data.get("trend", "")
            if trend == "UP":
                bull_weight += weight
            elif trend == "DOWN":
                bear_weight += weight

        if available_weight == 0:
            return None

        bull_pct = round(bull_weight / available_weight * 100)
        bear_pct = round(bear_weight / available_weight * 100)

        if bull_pct >= _ALIGNMENT_THRESHOLD:
            direction = SignalDirection.LONG
            aligned_pct = bull_pct
        elif bear_pct >= _ALIGNMENT_THRESHOLD:
            direction = SignalDirection.SHORT
            aligned_pct = bear_pct
        else:
            logger.debug(
                "[mtf_bias] выравнивание слабое: bull=%d%% bear=%d%% (порог %d%%)",
                bull_pct, bear_pct, _ALIGNMENT_THRESHOLD
            )
            return None

        # ── Шаг 2: Senior TF gate ────────────────────────────────────────────
        expected_trend = "UP" if direction == SignalDirection.LONG else "DOWN"
        senior_matches = sum(
            1 for tf in _SENIOR_TFS
            if snapshot.get(tf, {}).get("trend") == expected_trend
        )
        if senior_matches < _MIN_SENIOR_MATCH:
            logger.debug(
                "[mtf_bias] senior gate не пройден: %d/%d (%s)",
                senior_matches, _MIN_SENIOR_MATCH, expected_trend
            )
            return None

        # ── Шаг 3: Entry TF selection ────────────────────────────────────────
        cross_target = 1 if direction == SignalDirection.LONG else -1
        entry_tf = None
        for tf in _ENTRY_TF_CANDIDATES:
            tf_data = snapshot.get(tf)
            if tf_data and tf_data.get("wt_cross") == cross_target:
                entry_tf = tf
                break
        if entry_tf is None:
            # Без кросса на entry TF — не торгуем.
            # Принцип: "торгуем то что рынок показывает", а не угадываем.
            logger.debug(
                "[mtf_bias] пропущен: нет WT кросса на entry TF (%s)",
                "UP" if direction == SignalDirection.LONG else "DOWN",
            )
            return None

        # ── Шаг 4: Zone filter ───────────────────────────────────────────────
        entry_zone = snapshot.get(entry_tf, {}).get("zone", "N")
        if direction == SignalDirection.LONG and entry_zone == "OB":
            logger.debug("[mtf_bias] LONG пропущен: entry_tf=%s в OB", entry_tf)
            return None
        if direction == SignalDirection.SHORT and entry_zone == "OS":
            logger.debug("[mtf_bias] SHORT пропущен: entry_tf=%s в OS", entry_tf)
            return None

        # ── Шаг 5: Strength ──────────────────────────────────────────────────
        # Нормализуем base из диапазона [_ALIGNMENT_THRESHOLD..100] → [0..70]
        # aligned_pct=65 → 0, aligned_pct=100 → 70
        base = round((aligned_pct - _ALIGNMENT_THRESHOLD) / (100 - _ALIGNMENT_THRESHOLD) * 70)
        senior_bonus = _SENIOR_FULL_BONUS if senior_matches == 3 else 0
        cross_bonus = _CROSS_BONUS  # кросс всегда есть (обязательное условие выше)
        regime_penalty = _RANGE_PENALTY if regime == "RANGE" else 0

        strength = max(0, min(100, base + senior_bonus + cross_bonus - regime_penalty))

        # ── Шаг 6: Сборка SignalData ──────────────────────────────────────────
        # Компактная таблица ТФ для data
        tf_table = {}
        for tf in ("1d", "4h", "1h", "45m", "15m", "5m", "3m"):
            d = snapshot.get(tf)
            if d:
                tf_table[tf] = {
                    "trend": d.get("trend", "?"),
                    "wt1": d.get("wt1", 0),
                    "zone": d.get("zone", "N"),
                    "wt_cross": d.get("wt_cross", 0),
                }

        # ── ARCH-77: Миникуб WTMTF — три ребра (shadow, не влияют на strength) ──
        _zone_depth   = _compute_zone_depth(snapshot, direction)
        _cross_tf_div = _compute_cross_tf_divergence(snapshot, direction)
        _momentum_flow = _compute_momentum_flow(snapshot, direction)

        dir_str = "LONG ↑" if direction == SignalDirection.LONG else "SHORT ↓"
        description = f"MTF Bias {dir_str} — {senior_matches}/3 senior, entry={entry_tf}"
        interpretation = (
            f"Alignment: {aligned_pct}% {expected_trend} | "
            f"Senior: {senior_matches}/3 | "
            f"entry_tf: {entry_tf} | "
            f"regime: {regime or '?'} | "
            f"flow={_momentum_flow['flow']} div={_cross_tf_div['type']} depth={_zone_depth:.2f}"
        )

        logger.info(
            "[mtf_bias] %s: score=%d bull=%d%% bear=%d%% entry=%s senior=%d/3 regime=%s",
            "<symbol>", strength, bull_pct, bear_pct, entry_tf, senior_matches, regime
        )
        logger.debug(
            "[ARCH-77] flow=%s(%d/3) div=%s(%.2f) depth=%.2f",
            _momentum_flow["flow"], _momentum_flow["score"],
            _cross_tf_div["type"], _cross_tf_div["strength"],
            _zone_depth,
        )

        return SignalData(
            symbol="",  # заполняется в check_mtf_bias_signal
            signal_type=SignalType.MTF_BIAS,
            direction=direction,
            strength=strength,
            confidence=round(strength / 100.0, 2),
            timestamp=datetime.now(),
            timeframe=entry_tf,
            data={
                "bull_pct": bull_pct,
                "bear_pct": bear_pct,
                "aligned_pct": aligned_pct,
                "senior_matches": senior_matches,
                "entry_tf": entry_tf,
                "cross_found": entry_tf if cross_bonus > 0 else None,
                "regime": regime,
                "tf_table": tf_table,
                "senior_reversal": detect_senior_reversal(snapshot),
                # ARCH-77: три новых ребра Куба (shadow — сбор данных)
                "zone_depth":    _zone_depth,
                "cross_tf_div":  _cross_tf_div,
                "momentum_flow": _momentum_flow,
            },
            description=description,
            interpretation=interpretation,
        )

    except Exception:
        logger.exception("[mtf_bias] Ошибка interpret()")
        return None


def detect_senior_reversal(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Обнаруживает потенциальный разворот на старших TF (1d, 4h, 1h).

    Признак разворота DOWN: тренд UP + WT в зоне OB.
    Признак разворота UP:   тренд DOWN + WT в зоне OS.

    Возвращает словарь с полями:
        direction: "UP" | "DOWN"   — куда разворачивается цена
        tf:        "1d" | "4h" | "1h"
        wt1:       float            — текущий WT
        zone:      "OB" | "OS"
        strength:  int              — 1d=85, 4h=80, 1h=75
    Или None если признаков разворота нет.
    """
    senior_tfs = [("1d", 1.0), ("4h", 0.8), ("1h", 0.6)]
    reversals = []

    for tf, weight in senior_tfs:
        d = snapshot.get(tf)
        if not d:
            continue
        trend = d.get("trend", "")
        zone = d.get("zone", "N")
        wt1 = d.get("wt1", 0)

        if trend == "UP" and zone == "OB":
            reversals.append({"direction": "DOWN", "tf": tf, "wt1": wt1,
                               "zone": zone, "weight": weight})
        elif trend == "DOWN" and zone == "OS":
            reversals.append({"direction": "UP", "tf": tf, "wt1": wt1,
                               "zone": zone, "weight": weight})

    if not reversals:
        return None

    best = reversals[0]  # самый старший TF первый в списке
    strength = int(60 + best["weight"] * 25)  # 1d=85, 4h=80, 1h=75
    return {
        "direction": best["direction"],
        "tf": best["tf"],
        "wt1": best["wt1"],
        "zone": best["zone"],
        "strength": strength,
    }


# ── ARCH-77: Миникуб WTMTF — три новых ребра (shadow, данные для анализа) ─────

def _compute_zone_depth(snapshot: Dict[str, Any], direction: "SignalDirection") -> float:
    """
    Ребро 1: Zone Depth — глубина OS/OB зоны в направлении сигнала.

    LONG:  берём TF с wt1 < -60 (OS), считаем среднее (|wt1| - 60) / 40 → 0.0–1.0
    SHORT: берём TF с wt1 > +60 (OB), считаем среднее (wt1 - 60) / 40 → 0.0–1.0

    0.0 = зона едва достигнута (-60/+60)
    1.0 = экстремальная зона (-100/+100)
    """
    LONG = SignalDirection.LONG
    depths = []
    for tf in _TF_WEIGHTS:
        d = snapshot.get(tf)
        if not d:
            continue
        wt1 = d.get("wt1", 0)
        if direction == LONG and wt1 < -60:
            depths.append(min(1.0, (abs(wt1) - 60) / 40))
        elif direction != LONG and wt1 > 60:
            depths.append(min(1.0, (wt1 - 60) / 40))
    return round(sum(depths) / len(depths), 3) if depths else 0.0


def _compute_cross_tf_divergence(snapshot: Dict[str, Any], direction: "SignalDirection") -> dict:
    """
    Ребро 2: Cross-TF WT Divergence — расхождение между старшим и младшим TF.

    Паттерны:
      Bullish: 4h в OS (wt1<-60) + 1h тренд UP → смена структуры вверх
      Bearish: 4h в OB (wt1>+60) + 1h тренд DOWN → смена структуры вниз

    Возвращает:
      type:     "bullish" | "bearish" | "none"
      strength: 0.0 (нет) / 0.5 (частичная) / 1.0 (полная)
      detail:   строка для лога
    """
    LONG = SignalDirection.LONG
    is_long = (direction == LONG)

    d4h = snapshot.get("4h", {})
    d1h = snapshot.get("1h", {})
    if not d4h or not d1h:
        return {"type": "none", "strength": 0.0, "detail": "no 4h/1h data"}

    wt1_4h   = d4h.get("wt1", 0)
    trend_4h = d4h.get("trend", "")
    wt1_1h   = d1h.get("wt1", 0)
    trend_1h = d1h.get("trend", "")

    if is_long:
        # Полная bullish дивергенция: 4h OS + 1h уже UP
        if wt1_4h < -60 and trend_1h == "UP":
            strength = 1.0 if trend_4h == "DOWN" else 0.5
            return {"type": "bullish", "strength": strength,
                    "detail": f"4h_wt1={wt1_4h:.1f}(OS) 4h_trend={trend_4h} 1h_trend=UP"}
        # Частичная: 4h OS, 1h ещё DOWN (но разворот в процессе)
        if wt1_4h < -60 and trend_1h == "DOWN":
            return {"type": "bullish_forming", "strength": 0.25,
                    "detail": f"4h_wt1={wt1_4h:.1f}(OS) 1h_trend=DOWN (формируется)"}
    else:
        # Полная bearish дивергенция: 4h OB + 1h уже DOWN
        if wt1_4h > 60 and trend_1h == "DOWN":
            strength = 1.0 if trend_4h == "UP" else 0.5
            return {"type": "bearish", "strength": strength,
                    "detail": f"4h_wt1={wt1_4h:.1f}(OB) 4h_trend={trend_4h} 1h_trend=DOWN"}
        if wt1_4h > 60 and trend_1h == "UP":
            return {"type": "bearish_forming", "strength": 0.25,
                    "detail": f"4h_wt1={wt1_4h:.1f}(OB) 1h_trend=UP (формируется)"}

    return {"type": "none", "strength": 0.0,
            "detail": f"4h_wt1={wt1_4h:.1f} 1h_trend={trend_1h}"}


def _compute_momentum_flow(snapshot: Dict[str, Any], direction: "SignalDirection") -> dict:
    """
    Ребро 3: Momentum Flow — порядок смены тренда по TF (4h→1h→15m).

    Здоровый сигнал:  4h тренд в направлении + 1h тренд в направлении + 15m триггер
    Ранний сигнал:    15m/1h уже в направлении, но 4h ещё нет → риск ложного входа
    Расходящийся:     смешанные направления без иерархии

    Возвращает:
      flow:    "healthy" | "early" | "diverging" | "weak"
      score:   0–3 (сколько из 3 TF совпадают: 4h/1h/15m)
      detail:  строка
    """
    LONG = SignalDirection.LONG
    expected = "UP" if direction == LONG else "DOWN"

    t4h  = snapshot.get("4h",  {}).get("trend", "")
    t1h  = snapshot.get("1h",  {}).get("trend", "")
    t15m = snapshot.get("15m", {}).get("trend", "")

    match_4h  = (t4h  == expected)
    match_1h  = (t1h  == expected)
    match_15m = (t15m == expected)
    score = sum([match_4h, match_1h, match_15m])

    if score == 3:
        flow = "healthy"
    elif match_4h and match_1h and not match_15m:
        flow = "healthy"   # 4h+1h достаточно, 15m запаздывает
    elif not match_4h and match_1h and match_15m:
        flow = "early"     # мелкие ТФ опережают старшие — риск
    elif match_4h and not match_1h and match_15m:
        flow = "diverging" # 1h против — конфликт в середине иерархии
    elif score <= 1:
        flow = "weak"
    else:
        flow = "partial"

    return {
        "flow":   flow,
        "score":  score,
        "detail": f"4h={t4h} 1h={t1h} 15m={t15m} → {flow}({score}/3)",
    }


# ── ARCH-56 Phase B: вспомогательные функции ──────────────────────────────────

def _detect_phase(snapshot: Dict[str, Any]) -> tuple:
    """
    Определяет фазу рынка по иерархии TF.
    Returns: (phase_str, confidence: 0.0-1.0)
    """
    d1 = snapshot.get("1d", {}).get("trend")
    h4 = snapshot.get("4h", {}).get("trend")
    h1 = snapshot.get("1h", {}).get("trend")

    if d1 == "UP" and h4 == "UP" and h1 == "UP":
        return "impulse_up", 0.9
    if d1 == "DOWN" and h4 == "DOWN" and h1 == "DOWN":
        return "impulse_down", 0.9
    if d1 == "UP" and h4 == "UP" and h1 == "DOWN":
        return "correction_down_in_bull", 0.8
    if d1 == "DOWN" and h4 == "DOWN" and h1 == "UP":
        return "correction_up_in_bear", 0.8
    if d1 == "DOWN" and h4 == "UP" and h1 == "UP":
        return "reversal_up", 0.6
    if d1 == "UP" and h4 == "DOWN" and h1 == "DOWN":
        return "reversal_down", 0.6
    return "range", 0.4


def _detect_zone_cascade(snapshot: Dict[str, Any]) -> str:
    """
    Состояние WT-зон на старших TF.
    cascade_os/ob = 1D+4H оба в OS/OB.
    """
    d1z = snapshot.get("1d", {}).get("zone", "N")
    h4z = snapshot.get("4h", {}).get("zone", "N")
    if d1z == "OS" and h4z == "OS":
        return "cascade_os"
    if d1z == "OB" and h4z == "OB":
        return "cascade_ob"
    if d1z == "OS" or h4z == "OS":
        return "partial_os"
    if d1z == "OB" or h4z == "OB":
        return "partial_ob"
    return "neutral"


def _detect_avoid_reason(
    phase: str,
    zone_state: str,
    direction_bias: "SignalDirection",
    regime: Optional[str],
) -> Optional[str]:
    """
    Soft-block: причина НЕ торговать сейчас (только лог, не hard-block).
    Вернуть None = торговать можно.
    """
    LONG = SignalDirection.LONG
    SHORT = SignalDirection.SHORT
    if phase == "correction_up_in_bear" and direction_bias == LONG:
        return "correction_active"
    if phase == "correction_down_in_bull" and direction_bias == SHORT:
        return "correction_active"
    if zone_state == "cascade_ob" and direction_bias == LONG:
        return "cascade_ob_short_only"
    if zone_state == "cascade_os" and direction_bias == SHORT:
        return "cascade_os_long_only"
    if regime == "HIGH_VOL":
        return "high_vol_no_trade"
    return None


def _detect_pattern(phase: str, zone_state: str, senior_matches: int) -> tuple:
    """
    Named pattern для сигнала.
    Returns: (pattern_name, confidence)
    """
    if phase == "impulse_up" and senior_matches == 3:
        return "IMPULSE_UP", 0.85
    if phase == "impulse_down" and senior_matches == 3:
        return "IMPULSE_DOWN", 0.85
    if phase == "correction_down_in_bull" and zone_state in ("cascade_os", "partial_os"):
        return "WAVE_3_RELOAD", 0.75
    if phase == "correction_up_in_bear" and zone_state in ("cascade_ob", "partial_ob"):
        return "BEARISH_CORRECTION_FADE", 0.70
    if zone_state == "cascade_os" and phase != "impulse_up":
        return "CASCADE_OS_REVERSAL", 0.65
    if zone_state == "cascade_ob" and phase != "impulse_down":
        return "CASCADE_OB_REVERSAL", 0.65
    if phase == "reversal_up":
        return "REVERSAL_UP", 0.60
    if phase == "reversal_down":
        return "REVERSAL_DOWN", 0.60
    return "RANGE_PLAY", 0.40


def _extract_unswept_liquidity(
    df_1h=None, df_4h=None, lookback: int = 20
) -> tuple:
    """
    Нетронутые уровни ликвидности с 1h/4h.
    Unswept high = max за предыдущие lookback баров, которого нет в последних 10 барах.
    Unswept low  = min за предыдущие lookback баров, которого нет в последних 10 барах.
    """
    highs: list = []
    lows: list = []
    for df in (df_1h, df_4h):
        if df is None or len(df) < lookback + 10:
            continue
        try:
            window = df.tail(lookback + 10)
            prior  = window.iloc[:-10]
            recent = window.iloc[-10:]
            h_max = float(prior["high"].max()) if "high" in prior.columns else 0.0
            l_min = float(prior["low"].min())  if "low"  in prior.columns else 0.0
            r_max = float(recent["high"].max()) if "high" in recent.columns else 0.0
            r_min = float(recent["low"].min())  if "low"  in recent.columns else 0.0
            if h_max > r_max > 0:
                highs.append(round(h_max, 8))
            if 0 < l_min < r_min:
                lows.append(round(l_min, 8))
        except Exception:
            pass
    return sorted(set(highs), reverse=True), sorted(set(lows))


def analyze_context(
    snapshot: Dict[str, Dict[str, Any]],
    current_price: float = 0.0,
    weekly_pivots: Optional[Dict[str, float]] = None,
    regime: Optional[str] = None,
    df_1h=None,   # ARCH-56: для unswept liquidity
    df_4h=None,   # ARCH-56: для unswept liquidity
) -> MTFContext:
    """
    ARCH-12: Строит MTFContext — аналитический фундамент для всех сигналов.

    Это НЕ сигнал, а контекст: "куда смотрит рынок", "в какой зоне цена",
    "насколько сильный тренд по ТФ". Используется для модификации strength
    сигналов через direction_multiplier() и zone_multiplier().

    ARCH-56 Phase B (новые поля): phase, zone_state, avoid_reason, pattern_name,
    pattern_confidence, unswept_highs, unswept_lows.

    Args:
        snapshot: dict из collect_mtf_data() → {tf: {trend, wt1, wt2, zone, wt_cross}}
        current_price: текущая цена (для price_zone)
        weekly_pivots: dict с ключами PP, S1-S5, R1-R5 (для price_zone)
        regime: режим рынка (TREND_UP/DOWN/RANGE/HIGH_VOL)
        df_1h: OHLCV 1h DataFrame (для unswept liquidity, опционально)
        df_4h: OHLCV 4h DataFrame (для unswept liquidity, опционально)

    Returns:
        MTFContext (всегда, даже при слабых данных — direction_bias=NEUTRAL)
    """
    # ── 1. TF Alignment ─────────────────────────────────────────────
    bull_weight = 0
    bear_weight = 0
    available_weight = 0

    for tf, weight in _TF_WEIGHTS.items():
        tf_data = snapshot.get(tf)
        if not tf_data:
            continue
        available_weight += weight
        trend = tf_data.get("trend", "")
        if trend == "UP":
            bull_weight += weight
        elif trend == "DOWN":
            bear_weight += weight

    if available_weight > 0:
        bull_pct = round(bull_weight / available_weight * 100)
        bear_pct = round(bear_weight / available_weight * 100)
    else:
        bull_pct = bear_pct = 0

    # Направление bias
    if bull_pct >= _ALIGNMENT_THRESHOLD:
        direction_bias = SignalDirection.LONG
        aligned_pct = bull_pct
    elif bear_pct >= _ALIGNMENT_THRESHOLD:
        direction_bias = SignalDirection.SHORT
        aligned_pct = bear_pct
    else:
        direction_bias = SignalDirection.NEUTRAL
        aligned_pct = max(bull_pct, bear_pct)

    # bias_strength: 0.0 при aligned=50% (нет bias), 1.0 при aligned=100%
    bias_strength = round(max(0.0, (aligned_pct - 50) / 50.0), 2)

    # ── 2. Senior TF gate ────────────────────────────────────────────
    if direction_bias != SignalDirection.NEUTRAL:
        expected = "UP" if direction_bias == SignalDirection.LONG else "DOWN"
        senior_matches = sum(
            1 for tf in _SENIOR_TFS
            if snapshot.get(tf, {}).get("trend") == expected
        )
    else:
        senior_matches = 0

    # ── 3. Senior reversal ───────────────────────────────────────────
    senior_reversal = detect_senior_reversal(snapshot) if snapshot else None

    # ── 4. WT spreads (|wt1-wt2| по каждому ТФ) ─────────────────────
    wt_spreads: Dict[str, float] = {}
    for tf in ("3m", "5m", "15m", "45m", "1h", "4h", "1d"):
        d = snapshot.get(tf)
        if d and "wt1" in d and "wt2" in d:
            wt_spreads[tf] = round(abs(d["wt1"] - d["wt2"]), 2)

    # ── 5. Price zone (0.0=S5 .. 0.5=PP .. 1.0=R5) ──────────────────
    price_zone = 0.5  # default = PP (нейтраль)
    if current_price > 0 and weekly_pivots:
        s5 = weekly_pivots.get("S5") or weekly_pivots.get("S3", 0)
        r5 = weekly_pivots.get("R5") or weekly_pivots.get("R3", 0)
        pp = weekly_pivots.get("PP", 0)
        if s5 > 0 and r5 > s5:
            # Линейная интерполяция: S5=0.0, PP=0.5, R5=1.0
            price_zone = round(max(0.0, min(1.0, (current_price - s5) / (r5 - s5))), 3)

    # ── 6. ARCH-56 Phase B: фаза, зона, avoid_reason, паттерн ────────
    _phase, _phase_conf = _detect_phase(snapshot)
    _zone_state = _detect_zone_cascade(snapshot)
    _avoid_reason = _detect_avoid_reason(_phase, _zone_state, direction_bias, regime)
    _pattern_name, _pattern_conf = _detect_pattern(_phase, _zone_state, senior_matches)
    _unswept_h, _unswept_l = _extract_unswept_liquidity(df_1h, df_4h)

    ctx = MTFContext(
        direction_bias=direction_bias,
        bias_strength=bias_strength,
        price_zone=price_zone,
        aligned_pct=aligned_pct,
        senior_matches=senior_matches,
        senior_reversal=senior_reversal,
        wt_spreads=wt_spreads,
        regime=regime,
        bull_pct=bull_pct,
        bear_pct=bear_pct,
        phase=_phase,
        zone_state=_zone_state,
        avoid_reason=_avoid_reason,
        pattern_name=_pattern_name,
        pattern_confidence=round(_pattern_conf, 2),
        unswept_highs=_unswept_h,
        unswept_lows=_unswept_l,
    )

    logger.info(
        "[mtf_context] bias=%s str=%.2f zone=%.2f aligned=%d%% senior=%d/3 regime=%s "
        "phase=%s zone_state=%s pattern=%s avoid=%s",
        direction_bias.value, bias_strength, price_zone,
        aligned_pct, senior_matches, regime,
        _phase, _zone_state, _pattern_name, _avoid_reason,
    )

    return ctx


def mtf_bias_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует TG-сообщение для MTF_BIAS сигнала. Thin wrapper над format_signal_message."""
    from core.intelligence_formatter import format_signal_message
    return format_signal_message(symbol, sig, signal_type="mtf_bias")
