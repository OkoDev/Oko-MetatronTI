"""
Тесты для стратегий торговли (Этап 8.5).
"""

import pytest
import logging
from typing import List

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies import get_strategy, list_strategies, BaseStrategy

logger = logging.getLogger(__name__)

# Fixtures для создания тестовых данных


@pytest.fixture
def market_context():
    """Контекст рынка для тестов."""
    return MarketContext(
        symbol="BTC/USDT",
        current_price=45000.0,
        volume_24h=5000000000,  # 5B
        volume_change_24h=10.0,
        price_change_24h=2.5,
        volatility=15.0,
        atr=450.0,
    )


def create_signal(signal_type: SignalType, direction: SignalDirection,
                 strength: int, confidence: float) -> SignalData:
    """Вспомогательная функция для создания сигнала."""
    from datetime import datetime
    return SignalData(
        symbol="BTC/USDT",
        signal_type=signal_type,
        direction=direction,
        strength=strength,
        confidence=confidence,
        timestamp=datetime.utcnow(),
        data={},
    )


# Параметризованные тесты для всех стратегий


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_strategy_exists(strategy_name):
    """Проверяет что стратегия может быть создана."""
    strategy = get_strategy(strategy_name)
    assert strategy is not None
    assert isinstance(strategy, BaseStrategy)
    logger.info(f"✓ Strategy '{strategy_name}' created successfully")


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_strategy_analyze_empty_signals(strategy_name, market_context):
    """Проверяет что стратегия возвращает None на пустых сигналах."""
    strategy = get_strategy(strategy_name)
    recommendation = strategy.analyze([], market_context)
    assert recommendation is None
    logger.info(f"✓ Strategy '{strategy_name}' returns None for empty signals")


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_strategy_calculate_sl_tp(strategy_name, market_context):
    """Проверяет расчет SL/TP."""
    strategy = get_strategy(strategy_name)
    sl, tp, pos_size = strategy.calculate_sl_tp(
        entry_price=45000.0,
        direction="LONG",
        atr=450.0,
        market_context=market_context
    )
    
    # LONG: SL < entry < TP
    assert sl < 45000.0
    assert tp > 45000.0
    assert pos_size > 0
    
    logger.info(f"✓ Strategy '{strategy_name}': LONG SL={sl:.2f}, TP={tp:.2f}, size={pos_size}")


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_strategy_calculate_sl_tp_short(strategy_name, market_context):
    """Проверяет расчет SL/TP для SHORT."""
    strategy = get_strategy(strategy_name)
    sl, tp, pos_size = strategy.calculate_sl_tp(
        entry_price=45000.0,
        direction="SHORT",
        atr=450.0,
        market_context=market_context
    )
    
    # SHORT: TP < entry < SL
    assert tp < 45000.0
    assert sl > 45000.0
    assert pos_size > 0
    
    logger.info(f"✓ Strategy '{strategy_name}': SHORT SL={sl:.2f}, TP={tp:.2f}, size={pos_size}")


# Специфичные тесты для каждой стратегии


def test_confluence_strategy_requires_min_signals(market_context):
    """Confluence требует минимум 2 сигнала."""
    strategy = get_strategy("confluence")
    
    # Один сигнал
    single_signal = [create_signal(SignalType.MTF_SIGNAL, SignalDirection.LONG, 70, 0.8)]
    rec = strategy.analyze(single_signal, market_context)
    assert rec is None
    
    # Два сигнала
    two_signals = [
        create_signal(SignalType.MTF_SIGNAL, SignalDirection.LONG, 70, 0.8),
        create_signal(SignalType.WT_SIGNAL, SignalDirection.LONG, 60, 0.7),
    ]
    rec = strategy.analyze(two_signals, market_context)
    assert rec is not None
    assert rec.action == "BUY"
    
    logger.info("✓ Confluence requires minimum 2 signals")


def test_confluence_strategy_detects_conflicts(market_context):
    """Confluence отвергает конфликтующие сигналы."""
    strategy = get_strategy("confluence")
    
    # Примерно равные сигналы LONG и SHORT
    conflicting_signals = [
        create_signal(SignalType.MTF_SIGNAL, SignalDirection.LONG, 50, 0.8),
        create_signal(SignalType.WT_SIGNAL, SignalDirection.SHORT, 48, 0.8),
    ]
    rec = strategy.analyze(conflicting_signals, market_context)
    assert rec is None
    
    logger.info("✓ Confluence detects and rejects conflicting signals")


def test_mtf_bias_strategy_only_mtf(market_context):
    """MTF Bias использует только MTF сигналы."""
    strategy = get_strategy("mtf_bias")
    
    # Только non-MTF сигналы
    non_mtf = [
        create_signal(SignalType.ANOMALY, SignalDirection.LONG, 70, 0.8),
        create_signal(SignalType.DIVERGENCE, SignalDirection.LONG, 60, 0.7),
    ]
    rec = strategy.analyze(non_mtf, market_context)
    assert rec is None
    
    # MTF_BIAS сигнал с высокой силой (стратегия фильтрует именно MTF_BIAS)
    mtf_signal = [create_signal(SignalType.MTF_BIAS, SignalDirection.LONG, 70, 0.8)]
    rec = strategy.analyze(mtf_signal, market_context)
    assert rec is not None
    assert rec.action == "BUY"
    
    logger.info("✓ MTF Bias strategy only accepts MTF alerts")


def test_conservative_strategy_requires_high_confidence(market_context):
    """Conservative требует 3+ сигналов и высокой уверенности."""
    strategy = get_strategy("conservative")

    # Два сигнала — не достаточно
    weak_signals = [
        create_signal(SignalType.MTF_SIGNAL, SignalDirection.LONG, 50, 0.6),
        create_signal(SignalType.WT_SIGNAL, SignalDirection.LONG, 50, 0.6),
    ]
    rec = strategy.analyze(weak_signals, market_context)
    assert rec is None

    # Три сигнала с хорошей уверенностью — используем низкую волатильность
    low_vol_ctx = MarketContext(
        symbol="BTC/USDT",
        current_price=45000.0,
        volume_24h=5000000000,
        volume_change_24h=10.0,
        price_change_24h=2.5,
        volatility=5.0,   # <= 10, нет штрафа за волатильность
        atr=450.0,
    )
    strong_signals = [
        create_signal(SignalType.MTF_SIGNAL, SignalDirection.LONG, 75, 0.9),
        create_signal(SignalType.WT_SIGNAL, SignalDirection.LONG, 70, 0.85),
        create_signal(SignalType.DIVERGENCE, SignalDirection.LONG, 75, 0.88),
    ]
    rec = strategy.analyze(strong_signals, low_vol_ctx)
    assert rec is not None
    assert rec.action == "BUY"
    
    logger.info("✓ Conservative strategy requires 3+ signals and high confidence")


def test_strategy_info():
    """Проверяет что все стратегии возвращают info."""
    for strategy_name in list_strategies():
        strategy = get_strategy(strategy_name)
        info = strategy.get_info()
        assert "name" in info
        assert isinstance(info["name"], str) and len(info["name"]) > 0
        logger.info(f"✓ Strategy '{strategy_name}' info: {info}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
