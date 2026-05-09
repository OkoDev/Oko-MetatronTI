"""
ML-улучшение анализа: OutcomePredictor (P(win) blend) и MLPredictor.
Извлечено из TradingIntelligence._enhance_analysis_with_ml и _apply_ml_corrections.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.signals.signal_models import SignalDirection

logger = logging.getLogger(__name__)


def _check_direction_match(analysis_direction: SignalDirection, ml_prediction: float) -> bool:
    """Проверяет соответствие направления анализа и ML-предсказания."""
    if analysis_direction == SignalDirection.LONG and ml_prediction > 0.5:
        return True
    if analysis_direction == SignalDirection.SHORT and ml_prediction < 0.5:
        return True
    return False


def apply_ml_corrections(
    analysis: Dict[str, Any],
    ml_predictions: List,
    market_context,
) -> Dict[str, Any]:
    """Применяет ML-корректировки к словарю анализа."""
    try:
        ml_strength_adjustment   = 0.0
        ml_confidence_adjustment = 0.0

        for prediction in ml_predictions:
            # Lazy import to avoid hard dependency when ML unavailable
            try:
                from core.ml.ml_predictor import PredictionType
            except ImportError:
                PredictionType = None

            if PredictionType and prediction.prediction_type == PredictionType.PRICE_DIRECTION:
                direction_match = _check_direction_match(analysis["direction"], prediction.predicted_value)
                if direction_match:
                    ml_strength_adjustment += prediction.confidence * 10
                else:
                    ml_strength_adjustment -= prediction.confidence * 5

            elif PredictionType and prediction.prediction_type == PredictionType.SIGNAL_STRENGTH:
                predicted_strength = prediction.predicted_value * 100
                current_strength   = analysis["strength"]
                if predicted_strength > current_strength:
                    ml_strength_adjustment += (predicted_strength - current_strength) * prediction.confidence * 0.3
                else:
                    ml_strength_adjustment -= (current_strength - predicted_strength) * prediction.confidence * 0.2

            ml_confidence_adjustment += prediction.confidence * 0.1

        analysis["strength"]   = max(0, min(100, analysis["strength"] + ml_strength_adjustment))
        analysis["confidence"] = max(0.0, min(1.0, analysis["confidence"] + ml_confidence_adjustment))
        analysis["ml_enhanced"]               = True
        analysis["ml_predictions_count"]      = len(ml_predictions)
        analysis["ml_strength_adjustment"]    = ml_strength_adjustment
        analysis["ml_confidence_adjustment"]  = ml_confidence_adjustment

        return analysis
    except Exception:
        logger.exception("Ошибка применения ML корректировок")
        return analysis


async def enhance_analysis_with_ml(
    symbol: str,
    analysis: Dict[str, Any],
    market_context,
    ml_predictor,
    outcome_predictor,
) -> Dict[str, Any]:
    """
    Улучшает анализ с помощью машинного обучения (MLPredictor + OutcomePredictor).
    Модифицирует confidence на основе P(win).

    Args:
        symbol: торговая пара
        analysis: текущий словарь анализа (будет изменён in-place)
        market_context: MarketContext
        ml_predictor: MLPredictor или None
        outcome_predictor: OutcomePredictor или None
    Returns:
        analysis dict (изменённый)
    """
    try:
        if not ml_predictor:
            return analysis

        ml_predictions = []

        price_prediction = await ml_predictor.predict_price_direction(symbol)
        if price_prediction:
            ml_predictions.append(price_prediction)

        for signal in analysis.get("supporting_signals", []):
            signal_data = {
                "strength":        signal.strength,
                "confidence":      signal.confidence,
                "signal_type":     signal.signal_type.value,
                "age":             (datetime.now() - signal.timestamp).total_seconds(),
                "volume_24h":      market_context.volume_24h,
                "price_change_24h": market_context.price_change_24h,
                "volatility":      market_context.volatility or 0,
            }
            strength_prediction = await ml_predictor.predict_signal_strength(symbol, signal_data)
            if strength_prediction:
                ml_predictions.append(strength_prediction)

        if ml_predictions:
            analysis = apply_ml_corrections(analysis, ml_predictions, market_context)

        # OutcomePredictor: блендинг P(win) в confidence
        if outcome_predictor and analysis.get("direction") != SignalDirection.NEUTRAL:
            try:
                supporting = analysis.get("supporting_signals", [])
                first_sig  = supporting[0] if supporting else None
                sig_type   = first_sig.signal_type.value if first_sig else "composite"
                direction_str = (
                    analysis["direction"].value
                    if hasattr(analysis["direction"], "value")
                    else str(analysis["direction"])
                )
                features_dict = {
                    "volatility":       market_context.volatility or 0,
                    "price_change_24h": market_context.price_change_24h or 0,
                }
                win_prob = outcome_predictor.predict_win_prob(
                    signal_type=sig_type,
                    direction=direction_str,
                    strength=analysis.get("strength", 50),
                    confidence=analysis.get("confidence", 0.5),
                    features_dict=features_dict,
                    regime=None,
                )
                if win_prob is not None:
                    orig = analysis.get("confidence", 0.5)
                    analysis["confidence"] = round(orig * 0.7 + win_prob * 0.3, 4)
                    logger.debug("OutcomePredictor: P(win)=%.2f conf %.3f→%.3f",
                                 win_prob, orig, analysis["confidence"])
            except Exception as op_err:
                logger.debug("OutcomePredictor blend: %s", op_err)

        return analysis

    except Exception:
        logger.exception("Ошибка ML улучшения анализа для %s", symbol)
        return analysis
