"""
Narrative Builder — DEV-141 / ARCH-68 Фаза 2.

Собирает человекочитаемый торговый нарратив из всех специалистов.
По умолчанию выключен (config: trading.narrative.enabled: false).

Shadow mode: пишется в recommendation.metadata["narrative"].
Не заменяет TG-сообщения пока не активирован явно в config.

Шаблон:
  "{symbol} {action}: {mode} mode. {factor_1}, {factor_2}. P(win)={p_win:.0%}."
  Пример: "BTC LONG: REVERSAL mode. WT 4h OS + OB 1h active. P(win)=64%."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradingNarrative:
    """Результат Narrative Builder."""
    text: str             # человекочитаемый нарратив 2-3 предложения
    action: str           # BUY / SELL / HOLD / WATCH
    strategy: str         # SINGLE / DUAL_TP / DUAL_TSL
    confidence: float     # взвешенная уверенность 0.0–1.0
    p_win: float          # P(win) из взвешенного ансамбля специалистов
    key_factors: List[str] = field(default_factory=list)  # топ-3 фактора
    mode: str = "UNCLEAR"  # TREND / REVERSAL / UNCLEAR


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

    # Перераспределяем недоступные веса на outcome_predictor
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


def _extract_key_factors(
    recommendation: Any,
    wt_verdict: Any,   # WTVerdict | None
    smc_verdict: Any,  # SMCVerdict | None
    reversal_mode: str,
    btc_regime: Optional[str],
) -> List[str]:
    """Формирует топ-3 ключевых фактора для нарратива."""
    factors: List[str] = []

    # Фактор 1: Reversal Mode
    if reversal_mode == "REVERSAL":
        factors.append(f"mode=REVERSAL")
    elif reversal_mode == "TREND":
        factors.append(f"mode=TREND")

    # Фактор 2: WT verdict
    if wt_verdict is not None:
        label = getattr(wt_verdict, "label", None)
        if label and label != "UNCLEAR":
            factors.append(f"WT={label}")

    # Фактор 3: SMC verdict
    if smc_verdict is not None:
        label = getattr(smc_verdict, "label", None)
        if label and label not in ("NEUTRAL", "WEAK_ZONE"):
            factors.append(f"SMC={label}")

    # Фактор 4: BTC regime (если есть)
    if btc_regime and btc_regime not in (None, "RANGE"):
        factors.append(f"BTC={btc_regime}")

    # Фактор 5: Cascade
    meta = getattr(recommendation, "metadata", {}) or {}
    cascade = meta.get("cascade_count") or 0
    if cascade >= 2:
        factors.append(f"cascade×{cascade}")

    # Топ-3
    return factors[:3]


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
    Строит TradingNarrative из всех доступных источников.

    Args:
        symbol: торговая пара
        recommendation: TradingRecommendation
        pair_state: PairState из PairContextBus (может быть None)
        wt_verdict: WTVerdict из MTFWTSpecialist (может быть None)
        smc_verdict: SMCVerdict из MTFSMCSpecialist (может быть None)
        reversal_mode: "TREND" / "REVERSAL" / "UNCLEAR"
        btc_regime: режим BTC 4h (TREND_UP / TREND_DOWN / RANGE / HIGH_VOL)
        p_outcome: P(win) из OutcomePredictor (0.0–1.0)
    """
    # Извлекаем базовые поля из recommendation
    action    = str(getattr(recommendation, "action", "WATCH") or "WATCH")
    direction = str(getattr(recommendation, "direction", "") or "")
    strength  = float(getattr(recommendation, "overall_strength", 0) or 0)
    meta      = getattr(recommendation, "metadata", {}) or {}

    # Стратегия из metadata или дефолт
    strategy = str(meta.get("strategy_name", "SINGLE") or "SINGLE")

    # P(win) взвешенный
    p_wt  = getattr(wt_verdict,  "confidence", None)
    p_smc = getattr(smc_verdict, "confidence", None)
    p_win = _weighted_p_win(p_outcome, p_wt, p_smc)

    # Уверенность — берём из recommendation или из p_win
    rec_conf = float(getattr(recommendation, "confidence", 0.5) or 0.5)
    confidence = round((rec_conf * 0.6 + p_win * 0.4), 3)

    # Ключевые факторы
    key_factors = _extract_key_factors(
        recommendation, wt_verdict, smc_verdict, reversal_mode, btc_regime,
    )

    # Текст нарратива по шаблону
    base_sym = symbol.split("/")[0]
    action_dir = direction if direction not in ("", "NEUTRAL") else action
    factors_text = ", ".join(key_factors) if key_factors else "нет подтверждений"
    text = (
        f"{base_sym} {action_dir}: {reversal_mode} mode. "
        f"{factors_text}. P(win)={p_win:.0%}."
    )

    return TradingNarrative(
        text=text,
        action=action,
        strategy=strategy,
        confidence=confidence,
        p_win=p_win,
        key_factors=key_factors,
        mode=reversal_mode,
    )


class NarrativeBuilder:
    """
    Stateful wrapper над build_narrative().
    Хранит ссылки на PairContextBus и специалистов — не требует передавать их при каждом вызове.

    Использование:
        nb = NarrativeBuilder(pair_context_bus)
        narrative = nb.build(symbol, recommendation, wt_verdict, smc_verdict)
        # → TradingNarrative
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
        """Удобный метод — берёт PairState из bus автоматически."""
        pair_state = None
        if self._bus is not None:
            try:
                pair_state = self._bus.get(symbol)
            except Exception:
                pass

        return build_narrative(
            symbol=symbol,
            recommendation=recommendation,
            pair_state=pair_state,
            wt_verdict=wt_verdict,
            smc_verdict=smc_verdict,
            reversal_mode=reversal_mode,
            btc_regime=btc_regime,
            p_outcome=p_outcome,
        )
