"""
Модели данных для торговых сигналов и рекомендаций.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalType(Enum):
    ANOMALY = "anomaly"
    WT_SIGNAL = "wt_signal"
    WT_B_SIGNAL = "wt_b_signal"   # тип B: crossover В OS/OB + дивергенция WT (WR=85%)
    MTF_SIGNAL = "mtf_signal"
    MTF_ALERT = "mtf_alert"
    TREND_SIGNAL = "trend_signal"
    DIVERGENCE = "divergence"
    MTF_DIVERGENCE = "mtf_divergence"   # каскадные дивергенции 1D+4h+1h (Этап 9)
    PIVOT_REVERSAL = "pivot_reversal"
    CONFLUENCE = "confluence"
    MTF_BIAS = "mtf_bias"
    SMC_STRUCTURE = "smc_structure"   # CHoCH / BOS — Smart Money Concepts (Этап 9)
    OTE_SIGNAL = "ote_signal"         # Optimal Trade Entry (ICT 0.618–0.786 Fibonacci + WT trigger)
    FUNDING_EXTREME = "funding_extreme"  # DEV-81: экстремальный funding rate → squeeze (shadow mode)
    LIQUIDITY_SWEEP = "liquidity_sweep"  # DEV-82: вынос стопов за swing_low/high → разворот
    WT_SIDEWAYS = "wt_sideways"          # Sideways Mode: WT OS/OB на 30m при RANGE-режиме
    ATR_CHANGE  = "atr_change"           # DEV-199/sprintCA: Supertrend cross → прямой вход в тренд


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


def to_direction(value) -> str:
    """Нормализация направления к "LONG"|"SHORT"|"NEUTRAL".

    Принимает: SignalDirection enum, строки ("LONG"/"long"/"BUY"/"SELL"/...),
    None, любые объекты с .value. Единственный источник правды — раньше
    эта функция дублировалась как _direction_str в trade_simulator и trade_router.
    """
    if value is None:
        return "NEUTRAL"
    raw = getattr(value, "value", None) or str(value)
    val = raw.upper()
    if "LONG" in val or val == "BUY":
        return "LONG"
    if "SHORT" in val or val == "SELL":
        return "SHORT"
    return "NEUTRAL"


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
class MTFSMCSnapshot:
    """
    ARCH-51: Лёгкий торговый срез SMC для одного старшего TF.
    Хранит только торгово-значимые факты: "Bull OB рядом? CHoCH был?"
    Полный SMCContext не кешируем — только нужное.
    """
    bull_ob_nearby: bool = False      # цена в proximity_pct% от Bull OB (поддержка LONG)
    bear_ob_nearby: bool = False      # цена в proximity_pct% от Bear OB (сопротивление LONG)
    fvg_support: bool = False         # незакрытый Bull FVG ПОД ценой (магнит / поддержка)
    fvg_resistance: bool = False      # незакрытый Bear FVG НАД ценой (магнит / сопротивление)
    choch_direction: str = "none"     # "bullish"|"bearish"|"none" — последний CHoCH
    bos_direction: str = "none"       # "bullish"|"bearish"|"none" — последний BOS
    ob_proximity_pct: float = 0.0     # % от цены до ближайшего OB (для score Фаза 2)


@dataclass
class MTFContext:
    """
    ARCH-12: Аналитический контекст от MTF Interpreter.
    Говорит "куда смотреть", не "входи". Это КОНТЕКСТ, не сигнал.

    ARCH-12.5: Коэффициенты multipliers автокалибруются из реальных исходов.
    Калиброванные значения передаются через calibration_params.
    """
    direction_bias: SignalDirection       # куда смотрит рынок (от старших ТФ)
    bias_strength: float                  # 0.0-1.0
    price_zone: float                     # 0.0=S5, 0.5=PP, 1.0=R5 (weekly пивоты)
    aligned_pct: int                      # % ТФ в одном направлении
    senior_matches: int                   # 2 или 3
    senior_reversal: Optional[Dict[str, Any]]  # разворот старшего ТФ
    wt_spreads: Dict[str, float]          # {tf: |wt1-wt2|} — сила тренда по ТФ
    regime: Optional[str] = None          # TREND_UP/DOWN/RANGE/HIGH_VOL
    bull_pct: int = 0
    bear_pct: int = 0
    # ARCH-12.5: калиброванные параметры (None = defaults)
    calibration_params: Optional[Dict[str, float]] = None
    # ARCH-51: SMC снэпшоты старших TF (shadow mode — только логирование)
    smc_h4: Optional["MTFSMCSnapshot"] = None
    smc_d1: Optional["MTFSMCSnapshot"] = None
    # ARCH-56 Phase B: фаза рынка, зональное состояние, мягкий блок, паттерн
    phase: Optional[str] = None
    # impulse_up | impulse_down | correction_down_in_bull | correction_up_in_bear |
    # reversal_up | reversal_down | range
    zone_state: Optional[str] = None
    # cascade_os | cascade_ob | partial_os | partial_ob | neutral
    avoid_reason: Optional[str] = None
    # correction_active | cascade_ob_short_only | cascade_os_long_only |
    # high_vol_no_trade | None (торговать можно)
    pattern_name: Optional[str] = None
    # IMPULSE_UP | IMPULSE_DOWN | WAVE_3_RELOAD | BEARISH_CORRECTION_FADE |
    # CASCADE_OS_REVERSAL | CASCADE_OB_REVERSAL | REVERSAL_UP | REVERSAL_DOWN | RANGE_PLAY
    pattern_confidence: float = 0.0
    unswept_highs: List[float] = field(default_factory=list)  # sell-side liquidity 1h/4h
    unswept_lows: List[float] = field(default_factory=list)   # buy-side liquidity 1h/4h
    # DEV-137: Reversal Mode Detector (shadow — только логирование)
    reversal_mode: Optional[str] = None  # "REVERSAL" | "TREND" | "UNCLEAR"
    # DEV-138: MTF WT Specialist snapshot (для predict и features_json)
    wt_snap: Optional[Dict[str, Any]] = None  # {tf: {wt1, wt2, zone, wt_cross, trend}}
    # DEV-139: MTF SMC Specialist snapshot
    smc_snap: Optional[Dict[str, Any]] = None  # {tf: {ob_bull, fvg_open, choch, bos, ...}}

    def direction_multiplier(self, signal_direction: SignalDirection) -> float:
        """
        Множитель для strength сигнала на основе контекста.
        Сигнал ПО направлению bias → усиление, ПРОТИВ → ослабление.
        Коэффициенты берутся из calibration_params (если есть) или defaults.
        """
        if self.direction_bias == SignalDirection.NEUTRAL:
            return 1.0

        cp = self.calibration_params or {}
        aligned_boost = cp.get("aligned_boost", 0.5)
        counter_penalty = cp.get("counter_penalty", 0.7)
        counter_floor = cp.get("counter_floor", 0.3)

        aligned = (signal_direction == self.direction_bias)
        bs = self.bias_strength  # 0.0-1.0

        if aligned:
            return 1.0 + bs * aligned_boost
        else:
            return max(counter_floor, 1.0 - bs * counter_penalty)

    def zone_multiplier(self, signal_direction: SignalDirection) -> float:
        """
        Множитель на основе ценовой зоны (пивоты).
        LONG у S5 (zone=0.0) → усиление, LONG у R5 (zone=1.0) → ослабление.
        Коэффициенты берутся из calibration_params (если есть) или defaults.
        """
        if self.price_zone < 0 or self.price_zone > 1:
            return 1.0

        cp = self.calibration_params or {}
        zone_base_high = cp.get("zone_base_high", 1.4)
        zone_range = cp.get("zone_range", 0.8)
        zone_base_low = cp.get("zone_base_low", 0.6)

        if signal_direction == SignalDirection.LONG:
            # LONG: zone=0.0 (S5) → zone_base_high, zone=1.0 (R5) → zone_base_low
            return zone_base_high - zone_range * self.price_zone
        elif signal_direction == SignalDirection.SHORT:
            # SHORT: zone=1.0 (R5) → zone_base_high, zone=0.0 (S5) → zone_base_low
            return zone_base_low + zone_range * self.price_zone
        return 1.0


@dataclass
class MarketContext:
    symbol: str
    current_price: float
    # 🔴 29.09 ДЕФОЛТЫ, А НЕ ОБЯЗАТЕЛЬНЫЕ ПОЛЯ. Пока они были обязательными, каждый луп был
    # вынужден что-то передать — и передавал 0.0, потому что источника не было. Итог: оборот
    # нулевой во ВСЕХ 922 боевых сделках. Теперь единственная точка сборки —
    # `core/context/context_factory.build_market_context()`, которая читает оборот из шины;
    # ручное конструирование остаётся возможным, но нуль больше не навязан
    # ([[signal_volume24h_is_always_zero]]).
    volume_24h: float = 0.0
    volume_change_24h: float = 0.0
    price_change_24h: float = 0.0
    market_cap: Optional[float] = None
    volatility: Optional[float] = None
    trend_strength: Optional[float] = None
    atr: Optional[float] = None
    atr_slow: Optional[float] = None     # ATR(28) для анализа динамики волатильности
    tsl_trendup: Optional[float] = None    # TSL support-линия (SL для LONG)
    tsl_trenddown: Optional[float] = None  # TSL resistance-линия (SL для SHORT)
    swing_low: Optional[float] = None      # ближайший свинг-лоу ниже цены (20 баров)
    swing_high: Optional[float] = None     # ближайший свинг-хай выше цены (20 баров)
    # ARCH-12: MTF Context fields
    mtf_context: Optional['MTFContext'] = None
    # ARCH-17: SMC Context fields
    smc_context: Optional['SMCContext'] = None  # полный MTFContext объект
    # ARCH-55: RANGE BOUNCE — режим рынка + пивотный кеш для calculate_levels()
    regime: str = ""                           # TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
    pivot_cache_1d_1w: Dict[str, Any] = field(default_factory=dict)  # {symbol_1D: {PP,R1,...}, symbol_1W: {}}


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
    tp2_price: Optional[float] = None   # ARCH-113: HTF магнит для пирамидинга (dist 1-3R)
    sl_source: str = ""   # "tsl_line" | "swing_low" | "structural" | "atr_14" | "fallback"
    tp_source: str = ""   # "pivot_1M" | "pivot_1W" | "pivot_1D" | "atr_rr_3.0" | "fallback"
    tp2_source: str = ""  # ARCH-113: источник HTF TP2: "fvg_4h+pwh@47200" | ""
    atr_entry_tf: Optional[float] = None  # ATR(entry_tf) для ATR-based TP1 (DEV-40)
    reasoning: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # DEV-49
    metadata: Optional[Dict[str, Any]] = None
