"""
Narrative Builder — Сфера 9 / Куб Метатрона.

Читает ПОЛНОЕ состояние пары из PairContextBus (все 13 сфер) →
строит человекочитаемый торговый нарратив → публикует обратно в bus.

Это Decision Core: единственное место где все данные сходятся в решение.

Shadow mode: пишется в recommendation.metadata["narrative"].
Не заменяет TG-сообщения пока не активирован явно в config.

Шаблон:
  "{symbol} {action}: {mode} mode. {factor_1}, {factor_2}. P(win)={p_win:.0%}."
  Пример: "BTC LONG: REVERSAL mode. WT 4h OS + cascade×3 avg+2.1R. P(win)=64%."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NarrativeBuilder")


@dataclass
class TradingNarrative:
    """Результат Narrative Builder — полный нарратив со всех сфер."""
    text: str             # человекочитаемый нарратив 2-3 предложения
    action: str           # BUY / SELL / HOLD / WATCH
    strategy: str         # SINGLE / DUAL_TP / DUAL_TSL
    confidence: float     # взвешенная уверенность 0.0–1.0
    p_win: float          # P(win) из взвешенного ансамбля специалистов
    key_factors: List[str] = field(default_factory=list)  # топ-5 факторов
    mode: str = "UNCLEAR"  # TREND / REVERSAL / UNCLEAR
    spheres_used: int = 0  # сколько сфер дали данные для нарратива
    # ARCH-90: SMC структурный контекст из state.smc_snap
    smc_factors: List[str] = field(default_factory=list)           # человекочитаемые SMC-строки
    smc_flat: Dict[str, Any] = field(default_factory=dict)         # плоские поля для OutcomePredictor


def _weighted_p_win(
    p_outcome: Optional[float],   # OutcomePredictor (0.40 веса)
    p_wt: Optional[float],        # WTSpecialist (0.35 веса)
    p_smc: Optional[float],       # SMCSpecialist (0.25 веса)
) -> float:
    """
    Взвешенное P(win) из трёх источников.
    Если специалист недоступен — его вес перераспределяется на outcome_predictor.
    """
    w_outcome = 0.40
    w_wt      = 0.35
    w_smc     = 0.25

    if p_wt is None:
        w_outcome += w_wt
        w_wt = 0.0
    if p_smc is None:
        w_outcome += w_smc
        w_smc = 0.0

    total = 0.0
    total += (p_outcome or 0.50) * w_outcome
    if p_wt is not None:
        total += p_wt * w_wt
    if p_smc is not None:
        total += p_smc * w_smc

    return round(min(max(total, 0.0), 1.0), 3)


def _extract_smc_narrative(
    smc_snap: Optional[Dict[str, Any]],
    direction: str,
) -> tuple[List[str], Dict[str, Any]]:
    """ARCH-90: из state.smc_snap → список факторов + плоские поля для ML.

    direction: "LONG" / "SHORT" / "" — нужен для выбора bull/bear OB и BOS alignment.
    Возвращает (smc_factors, smc_flat):
      smc_factors — 0-4 строки для нарратива (приоритет: OTE → OB → BOS → CHoCH → FVG)
      smc_flat    — {nearest_ob_strength, price_in_ote, current_retracement, last_bos_direction}
    """
    factors: List[str] = []
    flat: Dict[str, Any] = {
        "nearest_ob_strength": None,
        "price_in_ote": False,
        "current_retracement": 0.0,
        "last_bos_direction": None,
    }
    if not smc_snap or not isinstance(smc_snap, dict):
        return factors, flat

    is_long = direction.upper() == "LONG"
    is_short = direction.upper() == "SHORT"

    # Плоские поля (всегда заполняются если snap валиден)
    flat["price_in_ote"] = bool(smc_snap.get("price_in_ote", False))
    flat["current_retracement"] = float(smc_snap.get("current_retracement", 0.0) or 0.0)
    last_bos = smc_snap.get("last_bos") or {}
    flat["last_bos_direction"] = last_bos.get("direction")  # "UP" / "DOWN" / None

    # Выбор OB по направлению (bull для LONG, bear для SHORT)
    if is_long:
        primary_ob = smc_snap.get("nearest_bull_ob")
    elif is_short:
        primary_ob = smc_snap.get("nearest_bear_ob")
    else:
        primary_ob = smc_snap.get("nearest_bull_ob") or smc_snap.get("nearest_bear_ob")
    if primary_ob:
        try:
            flat["nearest_ob_strength"] = int(primary_ob.get("strength", 0))
        except Exception:
            flat["nearest_ob_strength"] = None

    # Фактор 1: цена в OTE
    if flat["price_in_ote"]:
        retr = flat["current_retracement"]
        factors.append(f"цена в OTE 0.705–0.79 (ретрейс {retr:.0f}% от swing)")

    # Фактор 2: ближайший OB по направлению
    if primary_ob:
        dist = primary_ob.get("distance_pct")
        stg = primary_ob.get("strength")
        tf = primary_ob.get("tf", "?")
        ob_side = "bull" if is_long or not is_short else "bear"
        if dist is not None and stg is not None:
            try:
                if abs(float(dist)) < 3.0:
                    factors.append(
                        f"{ob_side} OB на {tf} в {float(dist):+.2f}% (strength={int(stg)})"
                    )
            except Exception:
                pass

    # Фактор 3: последний BOS
    bos_dir = flat["last_bos_direction"]
    if bos_dir and last_bos.get("tf"):
        age = last_bos.get("age_bars", "?")
        tf = last_bos.get("tf", "?")
        aligned = (is_long and bos_dir == "UP") or (is_short and bos_dir == "DOWN")
        marker = "✓" if aligned else "⚠"
        factors.append(f"{marker} BOS {bos_dir} {tf} ({age} баров)")

    # Фактор 4: CHoCH против направления
    last_choch = smc_snap.get("last_choch") or {}
    choch_dir = last_choch.get("direction")
    if choch_dir and (is_long or is_short):
        against = (is_long and choch_dir == "DOWN") or (is_short and choch_dir == "UP")
        if against:
            factors.append(f"⚠ CHoCH {choch_dir} {last_choch.get('tf','?')} против направления")

    # Фактор 5: FVG митигация на стороне
    fvg_side_key = "bull_fvg_active" if is_long else ("bear_fvg_active" if is_short else None)
    if fvg_side_key:
        fvgs = smc_snap.get(fvg_side_key) or []
        if fvgs:
            try:
                max_mit = max(float(f.get("mitigation_pct", 0) or 0) for f in fvgs)
                if max_mit > 60.0:
                    factors.append(f"⚠ FVG mitigated {max_mit:.0f}% — support слабеет")
            except Exception:
                pass

    return factors[:4], flat


def _extract_key_factors(
    recommendation: Any,
    pair_state: Any,       # PairState from bus
    wt_verdict: Any,       # WTVerdict | None
    smc_verdict: Any,      # SMCVerdict | None
    reversal_mode: str,
    btc_regime: Optional[str],
) -> List[str]:
    """Формирует топ-5 ключевых факторов из ВСЕХ сфер Куба."""
    factors: List[str] = []

    # Сфера 6: Reversal Mode
    if reversal_mode == "REVERSAL":
        factors.append("mode=REVERSAL")
    elif reversal_mode == "TREND":
        factors.append("mode=TREND")

    # Сфера 3: WT verdict
    if wt_verdict is not None:
        label = getattr(wt_verdict, "label", None)
        if label and label != "UNCLEAR":
            conf = getattr(wt_verdict, "confidence", 0)
            factors.append(f"WT={label}({conf:.0%})" if conf else f"WT={label}")

    # Сфера 4: SMC verdict
    if smc_verdict is not None:
        label = getattr(smc_verdict, "label", None)
        if label and label not in ("NEUTRAL", "WEAK_ZONE"):
            factors.append(f"SMC={label}")

    # Сфера 5: BTC regime
    if btc_regime and btc_regime not in (None, "RANGE"):
        factors.append(f"BTC={btc_regime}")

    # Сфера 11: Cascade из PairState
    if pair_state is not None:
        cascade = getattr(pair_state, "cascade_count", 0)
        avg_r = getattr(pair_state, "avg_r_cascade", 0)
        if cascade >= 2:
            factors.append(f"cascade x{cascade} avg+{avg_r:.1f}R")

        # Post-TSL OTE зона
        ptd = getattr(pair_state, "post_tsl_data", None)
        if ptd:
            factors.append("OTE active")

    # Сфера 7: Активная дивергенция из PairState
    if pair_state is not None:
        div = getattr(pair_state, "active_divergence", None)
        if div:
            factors.append(f"div:{div.get('type', '?')} {div.get('tf', '?')}")

        # Аномалия объёма
        if getattr(pair_state, "anomaly_active", False):
            factors.append("volume_anomaly")

    # Сфера 8: Near pivot
    if pair_state is not None:
        near_piv = getattr(pair_state, "near_pivot", None)
        if near_piv:
            factors.append(f"near_{near_piv.get('source', 'pivot')}")

    # Сфера 3: WT snap на 4h (OB/OS зона)
    if pair_state is not None:
        wt_snap = getattr(pair_state, "wt_snap", None)
        if wt_snap and "4h" in wt_snap:
            zone_4h = wt_snap["4h"].get("zone", "N")
            if zone_4h != "N":
                wt1_4h = wt_snap["4h"].get("wt1", 0)
                factors.append(f"WT4h={zone_4h}({wt1_4h:+.0f})")

    # Сфера 10: Открытая позиция (tsl active)
    if pair_state is not None and getattr(pair_state, "tsl_active", False):
        factors.append("TSL active")

    return factors[:5]


def _extract_past_outcome_line(pair_state: Any) -> Optional[str]:
    """ARCH-91: прошлый исход на паре — одна строка для TG/нарратива.

    Возвращает строку вида «Прошлый вход: SL (TSL_LATE) R=-1.0, 2ч назад»
    только если closed_at < 4ч назад. Иначе None.
    """
    if pair_state is None:
        return None
    outcome = getattr(pair_state, "last_narrative_outcome", None)
    if not outcome or not isinstance(outcome, dict):
        return None
    try:
        from datetime import datetime, timezone
        closed_raw = outcome.get("closed_at")
        if not closed_raw:
            return None
        if isinstance(closed_raw, str):
            closed_at = datetime.fromisoformat(closed_raw)
        elif isinstance(closed_raw, datetime):
            closed_at = closed_raw
        else:
            return None
        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone.utc)
        age_min = int((datetime.now(timezone.utc) - closed_at).total_seconds() / 60)
        if age_min > 240:  # старше 4ч — не показываем
            return None
        status = outcome.get("status", "?")
        r_val = outcome.get("R", 0)
        lost = outcome.get("lost_reason")
        reason_str = f" ({lost})" if lost else ""
        age_str = f"{age_min}мин" if age_min < 60 else f"{age_min // 60}ч{age_min % 60:02d}мин"
        return f"Прошлый вход: {status}{reason_str} R={r_val:+.1f}, {age_str} назад"
    except Exception:
        return None


def build_narrative(
    symbol: str,
    recommendation: Any,           # TradingRecommendation
    pair_state: Optional[Any],     # PairState | None
    wt_verdict: Optional[Any],     # WTVerdict | None
    smc_verdict: Optional[Any],    # SMCVerdict | None
    reversal_mode: str = "UNCLEAR",
    btc_regime: Optional[str] = None,
    p_outcome: Optional[float] = None,
) -> TradingNarrative:
    """
    Строит TradingNarrative из ВСЕХ доступных сфер Куба.
    Читает PairState с данными от всех 13 сфер.
    """
    action    = str(getattr(recommendation, "action", "WATCH") or "WATCH")
    direction = str(getattr(recommendation, "direction", "") or "")
    strength  = float(getattr(recommendation, "overall_strength", 0) or 0)
    meta      = getattr(recommendation, "metadata", {}) or {}

    strategy = str(meta.get("strategy_name", "SINGLE") or "SINGLE")

    # P(win) взвешенный из трёх ML-специалистов
    p_wt  = getattr(wt_verdict,  "confidence", None)
    p_smc = getattr(smc_verdict, "confidence", None)
    p_win = _weighted_p_win(p_outcome, p_wt, p_smc)

    rec_conf = float(getattr(recommendation, "confidence", 0.5) or 0.5)
    confidence = round((rec_conf * 0.6 + p_win * 0.4), 3)

    # Ключевые факторы из ВСЕХ сфер
    key_factors = _extract_key_factors(
        recommendation, pair_state, wt_verdict, smc_verdict, reversal_mode, btc_regime,
    )

    # ARCH-90: SMC-факторы из state.smc_snap (Сфера 4 → Сфера 9)
    smc_snap = getattr(pair_state, "smc_snap", None) if pair_state is not None else None
    smc_factors, smc_flat = _extract_smc_narrative(smc_snap, direction)

    # Считаем сколько сфер дали данные
    spheres_used = 1  # минимум Сфера 7 (детекторы) всегда
    if wt_verdict is not None:
        spheres_used += 1
    if smc_verdict is not None:
        spheres_used += 1
    if btc_regime:
        spheres_used += 1
    if pair_state is not None:
        if getattr(pair_state, "regime", None):
            spheres_used += 1
        if getattr(pair_state, "wt_snap", None):
            spheres_used += 1
        if getattr(pair_state, "pivot_snap", None):
            spheres_used += 1
        if getattr(pair_state, "cascade_count", 0) > 0:
            spheres_used += 1
        if getattr(pair_state, "tick_price", None):
            spheres_used += 1

    # Текст нарратива: rich формат со всеми факторами
    base_sym = symbol.split("/")[0]
    action_dir = direction if direction not in ("", "NEUTRAL") else action
    factors_text = ", ".join(key_factors) if key_factors else "нет подтверждений"

    # Regime info
    regime_text = ""
    if pair_state and getattr(pair_state, "regime", None):
        regime_text = f" [{pair_state.regime}]"

    text = (
        f"{base_sym} {action_dir}: {reversal_mode} mode{regime_text}. "
        f"{factors_text}. P(win)={p_win:.0%}. [{spheres_used} сфер]"
    )

    return TradingNarrative(
        text=text,
        action=action,
        strategy=strategy,
        confidence=confidence,
        p_win=p_win,
        key_factors=key_factors,
        mode=reversal_mode,
        spheres_used=spheres_used,
        smc_factors=smc_factors,
        smc_flat=smc_flat,
    )


class NarrativeBuilder:
    """
    Stateful wrapper над build_narrative().
    Хранит ссылки на PairContextBus — читает ПОЛНОЕ состояние всех сфер.

    Использование:
        nb = NarrativeBuilder(pair_context_bus)
        narrative = nb.build(symbol, recommendation, wt_verdict, smc_verdict)
        # → TradingNarrative с данными от всех 13 сфер
    """

    def __init__(self, pair_context_bus: Optional[Any] = None) -> None:
        self._bus = pair_context_bus

    def build(
        self,
        symbol: str,
        recommendation: Any,
        wt_verdict: Optional[Any] = None,
        smc_verdict: Optional[Any] = None,
        reversal_mode: str = "UNCLEAR",
        btc_regime: Optional[str] = None,
        p_outcome: Optional[float] = None,
    ) -> TradingNarrative:
        """Строит нарратив, читая полный PairState из bus."""
        pair_state = None
        if self._bus is not None:
            try:
                pair_state = self._bus.get(symbol)
                # Обогащаем из PairState если не переданы явно
                if reversal_mode == "UNCLEAR" and pair_state.reversal_mode:
                    reversal_mode = pair_state.reversal_mode
                if btc_regime is None and pair_state.btc_regime:
                    btc_regime = pair_state.btc_regime
            except Exception:
                pass

        narrative = build_narrative(
            symbol=symbol,
            recommendation=recommendation,
            pair_state=pair_state,
            wt_verdict=wt_verdict,
            smc_verdict=smc_verdict,
            reversal_mode=reversal_mode,
            btc_regime=btc_regime,
            p_outcome=p_outcome,
        )

        # Куб: Сфера 9 → bus: NARRATIVE_BUILT
        if self._bus is not None:
            try:
                from core.context.pair_context import SphereEvent
                self._bus.publish(symbol, SphereEvent.NARRATIVE_BUILT, {
                    "text": narrative.text,
                    "action": narrative.action,
                    "p_win": narrative.p_win,
                    "key_factors": narrative.key_factors,
                    "spheres_used": narrative.spheres_used,
                    "smc_factors": narrative.smc_factors,
                    "smc_flat": narrative.smc_flat,
                })
            except Exception:
                pass

        return narrative
