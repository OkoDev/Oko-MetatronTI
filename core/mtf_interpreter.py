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

from core.signal_models import SignalData, SignalType, SignalDirection

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
            entry_tf = "15m"  # fallback — entry без свежего кросса

        # ── Шаг 4: Zone filter ───────────────────────────────────────────────
        entry_zone = snapshot.get(entry_tf, {}).get("zone", "N")
        if direction == SignalDirection.LONG and entry_zone == "OB":
            logger.debug("[mtf_bias] LONG пропущен: entry_tf=%s в OB", entry_tf)
            return None
        if direction == SignalDirection.SHORT and entry_zone == "OS":
            logger.debug("[mtf_bias] SHORT пропущен: entry_tf=%s в OS", entry_tf)
            return None

        # ── Шаг 5: Strength ──────────────────────────────────────────────────
        base = aligned_pct
        senior_bonus = _SENIOR_FULL_BONUS if senior_matches == 3 else 0
        cross_bonus = _CROSS_BONUS if entry_tf and snapshot.get(entry_tf, {}).get("wt_cross") == cross_target else 0
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

        dir_str = "LONG ↑" if direction == SignalDirection.LONG else "SHORT ↓"
        description = f"MTF Bias {dir_str} — {senior_matches}/3 senior, entry={entry_tf}"
        interpretation = (
            f"Alignment: {aligned_pct}% {expected_trend} | "
            f"Senior: {senior_matches}/3 | "
            f"entry_tf: {entry_tf} | "
            f"regime: {regime or '?'}"
        )

        logger.info(
            "[mtf_bias] %s: score=%d bull=%d%% bear=%d%% entry=%s senior=%d/3 regime=%s",
            "<symbol>", strength, bull_pct, bear_pct, entry_tf, senior_matches, regime
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


def mtf_bias_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует TG-сообщение для MTF_BIAS сигнала."""
    from core.message_builder import tv_link
    data = sig.data or {}
    score = sig.strength
    direction = sig.direction
    is_long = direction == SignalDirection.LONG
    dir_label = "LONG ↑" if is_long else "SHORT ↓"
    dir_icon = "🟢" if is_long else "🔴"

    entry_tf = data.get("entry_tf", "15m")
    aligned_pct = data.get("aligned_pct", 0)
    senior_matches = data.get("senior_matches", 0)
    regime = data.get("regime") or "?"
    tf_table = data.get("tf_table", {})

    strength_emoji = "🔥🔥🔥" if score >= 80 else "🔥🔥" if score >= 60 else "🔥"

    # Строка ТФ-таблицы (3m→1d)
    tf_order = ["3m", "5m", "15m", "45m", "1h", "4h", "1d"]
    tf_cells = []
    for tf in tf_order:
        d = tf_table.get(tf)
        if not d:
            tf_cells.append(f"{tf}:?")
            continue
        arr = "↑" if d["trend"] == "UP" else "↓"
        zone_mark = "⚡" if d.get("wt_cross") else ("🔴" if d["zone"] == "OB" else ("🟢" if d["zone"] == "OS" else ""))
        tf_cells.append(f"{tf}{arr}{zone_mark}")

    lines = [
        "\n",
        f"📊 <b>MTF BIAS · {tv_link(symbol)} · {dir_icon} {dir_label}</b>",
        f"⏱ entry: <code>{entry_tf}</code>   {strength_emoji} <b>{score}/100</b>   senior: {senior_matches}/3",
        "",
        f"  {'  '.join(tf_cells)}",
        f"  alignment: <b>{aligned_pct}%</b> {dir_label[:4]}   режим: {regime}",
        "",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M')}",
        "\n",
    ]
    return "\n".join(lines)
