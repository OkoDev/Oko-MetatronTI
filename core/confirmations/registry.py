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

    # ── WT extreme (DEV-200) ── HTF WT вошёл в экстремум OS/OB (EXT_OS→LONG, EXT_OB→SHORT)
    'wt_extreme':             {'LONG': 6,  'SHORT': 6,  'is_trigger': False},

    # ── SMC ──
    'smc_choch_1h':           {'LONG': 6,  'SHORT': 6,  'is_trigger': False},
    'smc_choch_4h':           {'LONG': 8,  'SHORT': 8,  'is_trigger': False},
    'smc_bos_1h':             {'LONG': 4,  'SHORT': 4,  'is_trigger': False},
    'smc_bos_4h':             {'LONG': 6,  'SHORT': 6,  'is_trigger': False},  # DEV-200: старший = надёжнее
    'smc_bos_15m':            {'LONG': 3,  'SHORT': 3,  'is_trigger': False},  # DEV-200: младший = шумнее
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


# ── DEV-200.2: combinator-флаги → aggregator (веса из research Клода 04.06) ──
# Базовые веса per-flag (без TF — TF добавляется при публикации: {base}_{tf})
_COMBINATOR_BASE_WEIGHTS = {
    # SMC (не-Claude: fvg/bos/choch/eql/eqh — исключены)
    'bull_ob':              {'LONG': 5, 'SHORT': 0},
    'bear_ob':              {'LONG': 0, 'SHORT': 5},
    'bull_ob_near':         {'LONG': 5, 'SHORT': 0},
    'bear_ob_near':         {'LONG': 0, 'SHORT': 5},
    'bull_ob_mitigated':    {'LONG': 2, 'SHORT': 0},
    'bear_ob_mitigated':    {'LONG': 0, 'SHORT': 2},
    'ote_long':             {'LONG': 7, 'SHORT': 0},
    'ote_short':            {'LONG': 0, 'SHORT': 7},
    'premium':              {'LONG': 0, 'SHORT': 7},
    'discount':             {'LONG': 7, 'SHORT': 0},
    'bull_fvg_overlap':     {'LONG': 6, 'SHORT': 0},
    'bear_fvg_overlap':     {'LONG': 0, 'SHORT': 6},
    'bull_fvg_overlap_held':{'LONG': 6, 'SHORT': 0},
    'bear_fvg_overlap_held':{'LONG': 0, 'SHORT': 6},
    # Elliott
    'elliott_bull_impulse': {'LONG': 6, 'SHORT': 0},
    'elliott_bear_impulse': {'LONG': 0, 'SHORT': 6},
    'elliott_textbook':     {'LONG': 6, 'SHORT': 6},
    # Structure (HH/HL/LH/LL)
    'hh':                   {'LONG': 5, 'SHORT': 0},
    'hl':                   {'LONG': 5, 'SHORT': 0},
    'lh':                   {'LONG': 0, 'SHORT': 5},
    'll':                   {'LONG': 0, 'SHORT': 5},
    # WT
    'wt_os':                {'LONG': 6, 'SHORT': 0},
    'wt_ob':                {'LONG': 0, 'SHORT': 6},
    'wt_cross_up':          {'LONG': 6, 'SHORT': 0},
    'wt_cross_down':        {'LONG': 0, 'SHORT': 6},
    'wt_state_up':          {'LONG': 4, 'SHORT': 0},
    'wt_state_down':        {'LONG': 0, 'SHORT': 4},
    'wt_div_bull_regular':  {'LONG': 6, 'SHORT': 0},
    'wt_div_bear_regular':  {'LONG': 0, 'SHORT': 6},
    'wt_div_bull_hidden':   {'LONG': 6, 'SHORT': 0},
    'wt_div_bear_hidden':   {'LONG': 0, 'SHORT': 6},
    # RSI
    'rsi_os':               {'LONG': 4, 'SHORT': 0},
    'rsi_ob':               {'LONG': 0, 'SHORT': 4},
    'rsi_cross50_up':       {'LONG': 4, 'SHORT': 0},
    'rsi_cross50_down':     {'LONG': 0, 'SHORT': 4},
    'rsi_div_bull_regular': {'LONG': 6, 'SHORT': 0},
    'rsi_div_bear_regular': {'LONG': 0, 'SHORT': 6},
    'rsi_div_bull_hidden':  {'LONG': 6, 'SHORT': 0},
    'rsi_div_bear_hidden':  {'LONG': 0, 'SHORT': 6},
    # ATR
    'atr_up':               {'LONG': 5, 'SHORT': 0},
    'atr_down':             {'LONG': 0, 'SHORT': 5},
    'atr_cross_up':         {'LONG': 5, 'SHORT': 0},
    'atr_cross_down':       {'LONG': 0, 'SHORT': 5},
    # EMA
    'above_ema50':          {'LONG': 3, 'SHORT': 0},
    'above_ema200':         {'LONG': 3, 'SHORT': 0},
    'below_ema50':          {'LONG': 0, 'SHORT': 3},
    'below_ema200':         {'LONG': 0, 'SHORT': 3},
    'ema50_above_ema200':   {'LONG': 3, 'SHORT': 0},
    'ema50_below_ema200':   {'LONG': 0, 'SHORT': 3},
    # CMA (Фибо-MA магниты)
    'cma21_above':          {'LONG': 3, 'SHORT': 0},
    'cma55_above':          {'LONG': 3, 'SHORT': 0},
    'cma89_above':          {'LONG': 3, 'SHORT': 0},
    'cma144_above':         {'LONG': 3, 'SHORT': 0},
    'cma233_above':         {'LONG': 3, 'SHORT': 0},
    'cma_near':             {'LONG': 3, 'SHORT': 3},
    'cma_cluster':          {'LONG': 3, 'SHORT': 3},
    # Dynamic Channel
    'dc_slope_up':          {'LONG': 2, 'SHORT': 0},
    'dc_slope_down':        {'LONG': 0, 'SHORT': 2},
    'dc_at_upper':          {'LONG': 0, 'SHORT': 2},
    'dc_at_lower':          {'LONG': 2, 'SHORT': 0},
    # Momentum
    'bull_mom':             {'LONG': 2, 'SHORT': 0},
    'bear_mom':             {'LONG': 0, 'SHORT': 2},
    # Volume
    'vol_spike':            {'LONG': 5, 'SHORT': 5},
}

# Авто-расширение: для каждого базового веса генерируем TF-специфичные записи
# Формат: {base}_{tf} → тот же вес. get_weight() сначала ищет точное совпадение,
# потом отрезает _{tf} и ищет базу.
_COMBINATOR_TF_EXPANDED = {}
for _base, _w in _COMBINATOR_BASE_WEIGHTS.items():
    for _tf in ('15m', '1h', '4h', '1d'):
        _COMBINATOR_TF_EXPANDED[f'{_base}_{_tf}'] = _w

CONFIRMATION_WEIGHTS.update(_COMBINATOR_TF_EXPANDED)


def get_weight(source: str, side: str) -> int:
    """Возвращает вес confirmation для данной стороны (LONG/SHORT).

    Ищет точное совпадение в CONFIRMATION_WEIGHTS. Если нет — пробует
    отрезать TF-суффикс (_{15m,1h,4h,1d}) и ищет базу в
    _COMBINATOR_BASE_WEIGHTS (DEV-200.2).
    """
    w = CONFIRMATION_WEIGHTS.get(source, {}).get(side, 0)
    if w > 0:
        return w
    # fallback: strip TF suffix
    for _tf in ('_15m', '_1h', '_4h', '_1d'):
        if source.endswith(_tf):
            base = source[:-len(_tf)]
            return _COMBINATOR_BASE_WEIGHTS.get(base, {}).get(side, 0)
    return 0


def is_trigger(source: str) -> bool:
    """True если данный source является trigger (обязателен для сигнала)."""
    return CONFIRMATION_WEIGHTS.get(source, {}).get('is_trigger', False)


def list_triggers() -> list:
    """Список всех trigger source names."""
    return [k for k, v in CONFIRMATION_WEIGHTS.items() if v.get('is_trigger')]
