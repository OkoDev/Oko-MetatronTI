"""
Тесты ConfirmationAggregator.observe() — DEV-200.

Ключевой инвариант: observe() отдаёт ВСЕ confirmations в окне без требования
trigger, тогда как aggregate() (gate) прячет их пока нет atr_change-trigger.
Это и есть причина «пустого агрегатора» из DEV-238 для wt_signal/pivot_reversal.
"""
from core.intelligence.signal_aggregator import ConfirmationAggregator, attach_confirmations
from core.confirmations.models import Confirmation
from core.confirmations.registry import get_weight


def _conf(source, side, sym="BTC/USDT", tf="1h"):
    return Confirmation(
        source=source, symbol=sym, side=side,
        weight=get_weight(source, side), confidence=1.0, tf=tf,
    )


class TestObserveWithoutTrigger:
    def test_observe_returns_confs_no_trigger(self):
        """observe() отдаёт SMC/wt confirmations даже без atr_change-trigger."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("smc_choch_1h", "LONG"))
        agg.on_confirmation(_conf("wt_extreme", "LONG"))

        obs = agg.observe("BTC/USDT", "LONG")
        sources = {c["source"] for c in obs["confirmations"]}
        assert sources == {"smc_choch_1h", "wt_extreme"}
        assert obs["confirm_count"] == 2
        assert obs["has_trigger"] is False

    def test_aggregate_hides_confs_without_trigger(self):
        """aggregate() (gate) — пусто без trigger (контраст с observe)."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("smc_choch_1h", "LONG"))
        agg.on_confirmation(_conf("wt_extreme", "LONG"))

        res = agg.aggregate("BTC/USDT", "LONG")
        assert res["confirmations"] == []
        assert res["has_trigger"] is False
        assert res["strength"] == 0

    def test_observe_has_trigger_when_atr_present(self):
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("atr_change_1h", "LONG"))
        agg.on_confirmation(_conf("smc_choch_1h", "LONG"))

        obs = agg.observe("BTC/USDT", "LONG")
        assert obs["has_trigger"] is True
        assert obs["confirm_count"] == 2

    def test_observe_empty_for_unknown_key(self):
        agg = ConfirmationAggregator()
        obs = agg.observe("ETH/USDT", "SHORT")
        assert obs["confirmations"] == []
        assert obs["confirm_count"] == 0
        assert obs["has_trigger"] is False

    def test_observe_side_isolated(self):
        """LONG и SHORT буферы независимы."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("smc_eql_swept", "LONG"))
        assert agg.observe("BTC/USDT", "SHORT")["confirm_count"] == 0
        assert agg.observe("BTC/USDT", "LONG")["confirm_count"] == 1


class TestAttachConfirmations:
    """DEV-200 Phase 2: единый helper aggregate→observe→flag для всех путей."""

    def test_trigger_path_flag_false(self):
        """Есть trigger → confirmations из aggregate, флаг False."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("atr_change_1h", "LONG"))
        agg.on_confirmation(_conf("fvg_fill", "LONG"))
        extra = attach_confirmations(agg, "BTC/USDT", "LONG", {})
        srcs = {c["source"] for c in extra["confirmations"]}
        assert srcs == {"atr_change_1h", "fvg_fill"}
        assert extra["confirmations_no_trigger"] is False

    def test_no_trigger_observe_surfaces_flag_true(self):
        """Нет trigger → observe достаёт буфер, флаг True."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("smc_choch_1h", "LONG"))
        agg.on_confirmation(_conf("fvg_fill", "LONG"))
        extra = attach_confirmations(agg, "BTC/USDT", "LONG", {})
        srcs = {c["source"] for c in extra["confirmations"]}
        assert srcs == {"smc_choch_1h", "fvg_fill"}
        assert extra["confirmations_no_trigger"] is True

    def test_flag_set_on_existing_confluence_no_buffer(self):
        """КЛЮЧЕВОЙ ФИКС: extra уже с DEV-201 confluence, буфер пуст →
        флаг ставится по существующим (pivot_touch не trigger → True)."""
        agg = ConfirmationAggregator()  # пустой буфер
        extra = {"confirmations": [
            Confirmation(source="pivot_touch_within_03", symbol="BTC/USDT",
                         side="LONG", weight=4, confidence=0.9).to_dict()
        ]}
        extra = attach_confirmations(agg, "BTC/USDT", "LONG", extra)
        assert extra["confirmations_no_trigger"] is True
        assert len(extra["confirmations"]) == 1

    def test_merge_dedup_by_source(self):
        """observe не дублирует source, уже лежащий в extra."""
        agg = ConfirmationAggregator()
        agg.on_confirmation(_conf("fvg_fill", "LONG"))
        extra = {"confirmations": [
            Confirmation(source="fvg_fill", symbol="BTC/USDT", side="LONG",
                         weight=4, confidence=1.0).to_dict()
        ]}
        extra = attach_confirmations(agg, "BTC/USDT", "LONG", extra)
        assert len([c for c in extra["confirmations"] if c["source"] == "fvg_fill"]) == 1

    def test_none_aggregator_returns_extra(self):
        extra = {"foo": 1}
        out = attach_confirmations(None, "BTC/USDT", "LONG", extra)
        assert out == {"foo": 1}
        assert "confirmations_no_trigger" not in out

    def test_empty_no_keys_added(self):
        """Нет confirmations нигде → флаг не пишется (sparse)."""
        agg = ConfirmationAggregator()
        extra = attach_confirmations(agg, "ETH/USDT", "SHORT", {})
        assert "confirmations_no_trigger" not in extra
        assert "confirmations" not in extra
