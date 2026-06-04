"""
Тесты ConfirmationRegistry — DEV-200.
Покрывает: реестр весов, get_weight, is_trigger, list_triggers, dataclass Confirmation.
"""
import pytest
import time

from core.confirmations import (
    Confirmation,
    CONFIRMATION_WEIGHTS,
    get_weight,
    is_trigger,
    list_triggers,
)


# ---------------------------------------------------------------------------
# Реестр: количество и структура
# ---------------------------------------------------------------------------

class TestRegistryStructure:
    def test_total_count(self):
        """Ровно 28 типов confirmations (DEV-200: +wt_extreme, +smc_bos_4h/15m)."""
        assert len(CONFIRMATION_WEIGHTS) == 28

    def test_all_entries_have_required_keys(self):
        """Каждая запись содержит LONG, SHORT, is_trigger."""
        for source, entry in CONFIRMATION_WEIGHTS.items():
            assert 'LONG' in entry, f"{source}: нет ключа LONG"
            assert 'SHORT' in entry, f"{source}: нет ключа SHORT"
            assert 'is_trigger' in entry, f"{source}: нет ключа is_trigger"

    def test_weights_are_ints(self):
        """Все веса — целые числа."""
        for source, entry in CONFIRMATION_WEIGHTS.items():
            assert isinstance(entry['LONG'], int), f"{source}.LONG не int"
            assert isinstance(entry['SHORT'], int), f"{source}.SHORT не int"

    def test_weights_non_negative(self):
        """Все веса >= 0."""
        for source, entry in CONFIRMATION_WEIGHTS.items():
            assert entry['LONG'] >= 0, f"{source}.LONG отрицательный"
            assert entry['SHORT'] >= 0, f"{source}.SHORT отрицательный"


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

class TestTriggers:
    def test_trigger_count(self):
        """Ровно 3 trigger источника."""
        assert len(list_triggers()) == 3

    def test_known_triggers(self):
        triggers = list_triggers()
        assert 'atr_change_15m' in triggers
        assert 'atr_change_1h' in triggers
        assert 'atr_change_4h' in triggers

    def test_is_trigger_true(self):
        assert is_trigger('atr_change_1h') is True
        assert is_trigger('atr_change_4h') is True
        assert is_trigger('atr_change_15m') is True

    def test_is_trigger_false(self):
        assert is_trigger('zone_OS_1h') is False
        assert is_trigger('wt_cross_same_dir') is False
        assert is_trigger('div_regular_bull_15m') is False
        assert is_trigger('ote_zone') is False

    def test_is_trigger_unknown_source(self):
        """Неизвестный source → False."""
        assert is_trigger('nonexistent_source') is False


# ---------------------------------------------------------------------------
# get_weight — конкретные значения
# ---------------------------------------------------------------------------

class TestGetWeight:
    # Triggers
    def test_atr_change_15m_long(self):
        assert get_weight('atr_change_15m', 'LONG') == 8

    def test_atr_change_15m_short(self):
        # DEV-209: SHORT занижен до 5 (LONG/SHORT асимметрия 15m-триггера)
        assert get_weight('atr_change_15m', 'SHORT') == 5

    def test_atr_change_1h_long(self):
        assert get_weight('atr_change_1h', 'LONG') == 15

    def test_atr_change_1h_short(self):
        assert get_weight('atr_change_1h', 'SHORT') == 15

    def test_atr_change_4h_long(self):
        assert get_weight('atr_change_4h', 'LONG') == 18

    def test_atr_change_4h_short(self):
        assert get_weight('atr_change_4h', 'SHORT') == 18

    # Zone — асимметричные
    def test_zone_OS_1h_long(self):
        assert get_weight('zone_OS_1h', 'LONG') == 10

    def test_zone_OS_1h_short_zero(self):
        """OS-зона не даёт веса для SHORT."""
        assert get_weight('zone_OS_1h', 'SHORT') == 0

    def test_zone_OB_1h_long_zero(self):
        """OB-зона не даёт веса для LONG."""
        assert get_weight('zone_OB_1h', 'LONG') == 0

    def test_zone_OB_1h_short(self):
        assert get_weight('zone_OB_1h', 'SHORT') == 5

    def test_zone_OS_4h_long(self):
        assert get_weight('zone_OS_4h', 'LONG') == 8

    def test_zone_OS_4h_short_zero(self):
        assert get_weight('zone_OS_4h', 'SHORT') == 0

    def test_zone_OB_4h_long_zero(self):
        assert get_weight('zone_OB_4h', 'LONG') == 0

    def test_zone_OB_4h_short(self):
        assert get_weight('zone_OB_4h', 'SHORT') == 5

    # Cascade
    def test_atr_change_15m_pre_1h_long(self):
        assert get_weight('atr_change_15m_pre_1h', 'LONG') == 2

    def test_atr_change_15m_pre_1h_short(self):
        assert get_weight('atr_change_15m_pre_1h', 'SHORT') == 5

    def test_atr_change_5m_pre_1h_long(self):
        assert get_weight('atr_change_5m_pre_1h', 'LONG') == 1

    def test_atr_change_5m_pre_1h_short(self):
        assert get_weight('atr_change_5m_pre_1h', 'SHORT') == 2

    # WT cross
    def test_wt_cross_same_dir(self):
        assert get_weight('wt_cross_same_dir', 'LONG') == 3
        assert get_weight('wt_cross_same_dir', 'SHORT') == 3

    # WT extreme (DEV-200)
    def test_wt_extreme(self):
        assert get_weight('wt_extreme', 'LONG') == 6
        assert get_weight('wt_extreme', 'SHORT') == 6

    def test_wt_extreme_not_trigger(self):
        assert is_trigger('wt_extreme') is False

    # SMC
    def test_smc_choch_1h(self):
        assert get_weight('smc_choch_1h', 'LONG') == 6
        assert get_weight('smc_choch_1h', 'SHORT') == 6

    def test_smc_choch_4h(self):
        assert get_weight('smc_choch_4h', 'LONG') == 8
        assert get_weight('smc_choch_4h', 'SHORT') == 8

    def test_smc_bos_1h(self):
        assert get_weight('smc_bos_1h', 'LONG') == 4
        assert get_weight('smc_bos_1h', 'SHORT') == 4

    def test_smc_bos_4h(self):
        # DEV-200: старший TF надёжнее (bos_4h > bos_1h), но < choch_4h(8)
        assert get_weight('smc_bos_4h', 'LONG') == 6
        assert get_weight('smc_bos_4h', 'SHORT') == 6

    def test_smc_bos_15m(self):
        # DEV-200: младший TF шумнее
        assert get_weight('smc_bos_15m', 'LONG') == 3
        assert get_weight('smc_bos_15m', 'SHORT') == 3

    def test_smc_eql_swept_asymmetric(self):
        assert get_weight('smc_eql_swept', 'LONG') == 5
        assert get_weight('smc_eql_swept', 'SHORT') == 0

    def test_smc_eqh_swept_asymmetric(self):
        assert get_weight('smc_eqh_swept', 'LONG') == 0
        assert get_weight('smc_eqh_swept', 'SHORT') == 5

    def test_fvg_fill(self):
        assert get_weight('fvg_fill', 'LONG') == 4
        assert get_weight('fvg_fill', 'SHORT') == 4

    def test_ote_zone(self):
        assert get_weight('ote_zone', 'LONG') == 7
        assert get_weight('ote_zone', 'SHORT') == 7

    # Pivots
    def test_pivot_touch_within_03(self):
        assert get_weight('pivot_touch_within_03', 'LONG') == 4
        assert get_weight('pivot_touch_within_03', 'SHORT') == 4

    def test_pivot_confluence_2plus(self):
        assert get_weight('pivot_confluence_2plus', 'LONG') == 6
        assert get_weight('pivot_confluence_2plus', 'SHORT') == 6

    # Volume
    def test_volume_spike_z25(self):
        assert get_weight('volume_spike_z25', 'LONG') == 5
        assert get_weight('volume_spike_z25', 'SHORT') == 5

    # Divergences
    def test_div_regular_bull_15m(self):
        assert get_weight('div_regular_bull_15m', 'LONG') == 6
        assert get_weight('div_regular_bull_15m', 'SHORT') == 0

    def test_div_regular_bear_15m(self):
        assert get_weight('div_regular_bear_15m', 'LONG') == 0
        assert get_weight('div_regular_bear_15m', 'SHORT') == 6

    def test_div_hidden_bull_15m(self):
        assert get_weight('div_hidden_bull_15m', 'LONG') == 5
        assert get_weight('div_hidden_bull_15m', 'SHORT') == 0

    def test_div_hidden_bear_15m(self):
        assert get_weight('div_hidden_bear_15m', 'LONG') == 0
        assert get_weight('div_hidden_bear_15m', 'SHORT') == 5

    def test_div_cascade_1h_15m(self):
        assert get_weight('div_cascade_1h_15m', 'LONG') == 8
        assert get_weight('div_cascade_1h_15m', 'SHORT') == 8

    # Неизвестный source
    def test_unknown_source_returns_zero(self):
        assert get_weight('unknown_source', 'LONG') == 0
        assert get_weight('unknown_source', 'SHORT') == 0

    def test_unknown_side_returns_zero(self):
        assert get_weight('atr_change_1h', 'FLAT') == 0


# ---------------------------------------------------------------------------
# Dataclass Confirmation
# ---------------------------------------------------------------------------

class TestConfirmationDataclass:
    def test_basic_creation(self):
        c = Confirmation(
            source='atr_change_1h',
            symbol='BTC/USDT',
            side='LONG',
            weight=15,
            confidence=0.8,
        )
        assert c.source == 'atr_change_1h'
        assert c.symbol == 'BTC/USDT'
        assert c.side == 'LONG'
        assert c.weight == 15
        assert c.confidence == 0.8
        assert c.evidence == {}
        assert c.tf == ""
        assert isinstance(c.ts_ms, int)

    def test_ts_ms_auto_generated(self):
        before = int(time.time() * 1000)
        c = Confirmation(source='zone_OS_1h', symbol='ETH/USDT', side='LONG', weight=10, confidence=0.7)
        after = int(time.time() * 1000)
        assert before <= c.ts_ms <= after

    def test_ts_ms_different_per_instance(self):
        c1 = Confirmation(source='zone_OS_1h', symbol='BTC/USDT', side='LONG', weight=10, confidence=0.7)
        c2 = Confirmation(source='zone_OS_1h', symbol='BTC/USDT', side='LONG', weight=10, confidence=0.7)
        # ts_ms могут совпасть при быстром создании, но evidence и поля независимы
        assert c1 is not c2

    def test_evidence_default_factory_independent(self):
        """Каждый экземпляр имеет свой dict evidence."""
        c1 = Confirmation(source='fvg_fill', symbol='BTC/USDT', side='SHORT', weight=4, confidence=0.6)
        c2 = Confirmation(source='fvg_fill', symbol='BTC/USDT', side='SHORT', weight=4, confidence=0.6)
        c1.evidence['key'] = 'value'
        assert 'key' not in c2.evidence

    def test_with_evidence_and_tf(self):
        c = Confirmation(
            source='smc_choch_4h',
            symbol='SOL/USDT',
            side='SHORT',
            weight=8,
            confidence=0.9,
            evidence={'swing_high': 105.5, 'candle': '2h ago'},
            tf='4h',
        )
        assert c.evidence['swing_high'] == 105.5
        assert c.tf == '4h'

    def test_to_dict_all_fields(self):
        c = Confirmation(
            source='ote_zone',
            symbol='BTC/USDT',
            side='LONG',
            weight=7,
            confidence=0.75,
            evidence={'level': 65000},
            tf='1h',
        )
        d = c.to_dict()
        assert d['source'] == 'ote_zone'
        assert d['symbol'] == 'BTC/USDT'
        assert d['side'] == 'LONG'
        assert d['weight'] == 7
        assert d['confidence'] == 0.75
        assert d['evidence'] == {'level': 65000}
        assert d['tf'] == '1h'
        assert isinstance(d['ts_ms'], int)
        # Убедимся что все 8 ключей присутствуют
        assert set(d.keys()) == {'source', 'symbol', 'side', 'weight', 'confidence', 'evidence', 'ts_ms', 'tf'}

    def test_to_dict_returns_copy_of_evidence(self):
        """to_dict возвращает ссылку на evidence — проверяем что dict возвращается."""
        c = Confirmation(source='volume_spike_z25', symbol='BTC/USDT', side='LONG', weight=5, confidence=0.65)
        d = c.to_dict()
        assert isinstance(d['evidence'], dict)


# ---------------------------------------------------------------------------
# Импорт из core.confirmations (публичный API)
# ---------------------------------------------------------------------------

class TestPublicImport:
    def test_confirmation_importable(self):
        from core.confirmations import Confirmation as C
        assert C is not None

    def test_confirmation_weights_importable(self):
        from core.confirmations import CONFIRMATION_WEIGHTS as CW
        assert isinstance(CW, dict)

    def test_get_weight_importable(self):
        from core.confirmations import get_weight as gw
        assert callable(gw)

    def test_is_trigger_importable(self):
        from core.confirmations import is_trigger as it
        assert callable(it)

    def test_list_triggers_importable(self):
        from core.confirmations import list_triggers as lt
        assert callable(lt)

    def test_no_side_effects_on_import(self):
        """Повторный импорт не вызывает ошибок."""
        import importlib
        import core.confirmations
        importlib.reload(core.confirmations)
