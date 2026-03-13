"""
Модели данных для торговых сигналов и рекомендаций.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalType(Enum):
    ANOMALY = "anomaly"
    WT_SIGNAL = "wt_signal"
    MTF_SIGNAL = "mtf_signal"
    MTF_ALERT = "mtf_alert"
    TREND_SIGNAL = "trend_signal"
    DIVERGENCE = "divergence"
    MTF_DIVERGENCE = "mtf_divergence"   # каскадные дивергенции 1D+4h+1h (Этап 9)
    PIVOT_REVERSAL = "pivot_reversal"
    CONFLUENCE = "confluence"
    MTF_BIAS = "mtf_bias"


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class SignalStrength(Enum):
    VERY_HIGH = "VERY_HIGH"  # 80-100
    HIGH = "HIGH"            # 60-79
    MEDIUM = "MEDIUM"        # 40-59
    LOW = "LOW"              # 20-39
    VERY_LOW = "VERY_LOW"    # 0-19


@dataclass
class SignalData:
    symbol: str
    signal_type: SignalType
    direction: SignalDirection
    strength: int        # 0-100
    confidence: float    # 0.0-1.0
    timestamp: datetime
    data: Dict[str, Any]
    timeframe: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    description: str = ""        # что нашёл детектор: "Двойная бычья дивергенция (WT)"
    interpretation: str = ""     # что это значит: "Цена LL→LL, индикатор HL→HL — продавцы выдохлись"


@dataclass
class MarketContext:
    symbol: str
    current_price: float
    volume_24h: float
    volume_change_24h: float
    price_change_24h: float
    market_cap: Optional[float] = None
    volatility: Optional[float] = None
    trend_strength: Optional[float] = None
    atr: Optional[float] = None
    atr_slow: Optional[float] = None     # ATR(28) для анализа динамики волатильности
    tsl_trendup: Optional[float] = None    # TSL support-линия (SL для LONG)
    tsl_trenddown: Optional[float] = None  # TSL resistance-линия (SL для SHORT)
    swing_low: Optional[float] = None      # ближайший свинг-лоу ниже цены (20 баров)
    swing_high: Optional[float] = None     # ближайший свинг-хай выше цены (20 баров)


@dataclass
class TradingRecommendation:
    symbol: str
    action: str              # "BUY", "SELL", "HOLD", "WATCH"
    direction: SignalDirection
    overall_strength: int    # 0-100
    confidence: float        # 0.0-1.0
    risk_level: str          # "LOW", "MEDIUM", "HIGH"
    signals_count: int
    supporting_signals: List[SignalData]
    conflicting_signals: List[SignalData]
    market_context: MarketContext
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    tp1_price: Optional[float] = None   # уровень частичного TP (50% позиции при 3R)
    sl_source: str = ""   # "tsl_line" | "swing_low" | "structural" | "atr_14" | "fallback"
    tp_source: str = ""   # "pivot_1M" | "pivot_1W" | "pivot_1D" | "atr_rr_3.0" | "fallback"
    reasoning: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None
