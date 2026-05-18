CONFIRMATION_WEIGHTS = {
    # ── TRIGGERS (is_trigger=True) ──
    'atr_change_15m':         {'LONG': 8,  'SHORT': 5,  'is_trigger': True},
    'atr_change_1h':          {'LONG': 15, 'SHORT': 15, 'is_trigger': True},
    'atr_change_4h':          {'LONG': 18, 'SHORT': 18, 'is_trigger': True},

    # ── ZONE confirmations ──
    'zone_OS_1h':             {'LONG': 10, 'SHORT': 0,  'is_trigger': False},
    'zone_OB_1h':             {'LONG': 0,  'SHORT': 5,  'is_trigger': False},
    'zone_OS_4h':             {'LONG': 8,  'SHORT': 0,  'is_trigger': False},
    'zone_OB_4h':             {'LONG': 0,  'SHORT': 5,  'is_trigger': False},

    # ── CASCADE (ATR предшественники) ──
    'atr_change_15m_pre_1h':  {'LONG': 2,  'SHORT': 5,  'is_trigger': False},
    'atr_change_5m_pre_1h':   {'LONG': 1,  'SHORT': 2,  'is_trigger': False},

    # ── WT cross ──
    'wt_cross_same_dir':      {'LONG': 3,  'SHORT': 3,  'is_trigger': False},

    # ── SMC ──
    'smc_choch_1h':           {'LONG': 6,  'SHORT': 6,  'is_trigger': False},
    'smc_choch_4h':           {'LONG': 8,  'SHORT': 8,  'is_trigger': False},
    'smc_bos_1h':             {'LONG': 4,  'SHORT': 4,  'is_trigger': False},
    'smc_eql_swept':          {'LONG': 5,  'SHORT': 0,  'is_trigger': False},
    'smc_eqh_swept':          {'LONG': 0,  'SHORT': 5,  'is_trigger': False},
    'fvg_fill':               {'LONG': 4,  'SHORT': 4,  'is_trigger': False},
    'ote_zone':               {'LONG': 7,  'SHORT': 7,  'is_trigger': False},

    # ── PIVOTS ──
    'pivot_touch_within_03':  {'LONG': 4,  'SHORT': 4,  'is_trigger': False},
    'pivot_confluence_2plus': {'LONG': 6,  'SHORT': 6,  'is_trigger': False},

    # ── VOLUME ──
    'volume_spike_z25':       {'LONG': 5,  'SHORT': 5,  'is_trigger': False},

    # ── DIVERGENCES ──
    'div_regular_bull_15m':   {'LONG': 6,  'SHORT': 0,  'is_trigger': False},
    'div_regular_bear_15m':   {'LONG': 0,  'SHORT': 6,  'is_trigger': False},
    'div_hidden_bull_15m':    {'LONG': 5,  'SHORT': 0,  'is_trigger': False},
    'div_hidden_bear_15m':    {'LONG': 0,  'SHORT': 5,  'is_trigger': False},
    'div_cascade_1h_15m':     {'LONG': 8,  'SHORT': 8,  'is_trigger': False},
}


def get_weight(source: str, side: str) -> int:
    """Возвращает вес confirmation для данной стороны (LONG/SHORT)."""
    return CONFIRMATION_WEIGHTS.get(source, {}).get(side, 0)


def is_trigger(source: str) -> bool:
    """True если данный source является trigger (обязателен для сигнала)."""
    return CONFIRMATION_WEIGHTS.get(source, {}).get('is_trigger', False)


def list_triggers() -> list:
    """Список всех trigger source names."""
    return [k for k, v in CONFIRMATION_WEIGHTS.items() if v.get('is_trigger')]
