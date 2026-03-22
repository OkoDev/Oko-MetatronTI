"""
Тесты Multi-TF Conflict Resolver (ARCH-13).

Покрывает:
- Дубликаты (один move на нескольких ТФ)
- Противоречия (LONG vs SHORT на разных ТФ)
- Приоритет старшего ТФ
- Окно дедупликации
- Валидация конфигурации
- Граничные случаи
"""

import pytest
from datetime import datetime, timedelta
from core.multi_tf_resolver import (
    TFSignal, MultiTFResolver, ResolverDecision,
    validate_multi_tf_config, TF_PRIORITY,
)


# ---------------------------------------------------------------------------
# Фабрика сигналов
# ---------------------------------------------------------------------------

def _sig(symbol="BTCUSDT", tf="15m", direction="LONG", strength=70,
         rr=3.0, signal_type="wt_signal", entry=100.0, sl=95.0, tp=110.0,
         ts=None):
    return TFSignal(
        symbol=symbol, timeframe=tf, direction=direction,
        signal_type=signal_type, strength=strength,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        rr_ratio=rr, timestamp=ts or datetime.now(),
    )


# ---------------------------------------------------------------------------
# TestTFSignal
# ---------------------------------------------------------------------------

class TestTFSignal:
    def test_priority_known_tf(self):
        s = _sig(tf="1h")
        assert s.tf_priority == 8

    def test_priority_unknown_tf(self):
        s = _sig(tf="2h")
        assert s.tf_priority == 0

    def test_priority_ordering(self):
        tfs = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]
        priorities = [_sig(tf=t).tf_priority for t in tfs]
        assert priorities == sorted(priorities)


# ---------------------------------------------------------------------------
# TestSingleSignal — один сигнал, нет конфликтов
# ---------------------------------------------------------------------------

class TestSingleSignal:
    def test_single_signal_accepted(self):
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG"))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.conflict_type == "clean"
        assert d.chosen_signal.timeframe == "15m"

    def test_empty_buffer_rejected(self):
        r = MultiTFResolver()
        d = r.resolve("BTCUSDT")
        assert d.action == "REJECT"


# ---------------------------------------------------------------------------
# TestDuplicates — один move, сигналы на нескольких ТФ, одно направление
# ---------------------------------------------------------------------------

class TestDuplicates:
    def test_same_direction_different_tf_chooses_senior(self):
        """5m LONG + 15m LONG → 15m побеждает (старший)."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="5m", direction="LONG", strength=80, rr=4.0))
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70, rr=3.0))
        d = r.resolve("BTCUSDT")
        assert d.action == "UPGRADE"  # совпадение = усиление
        assert d.chosen_signal.timeframe == "15m"
        assert len(d.rejected_signals) == 1
        assert d.conflict_type == "duplicate"

    def test_three_tf_all_long(self):
        """5m + 15m + 1h LONG → 1h побеждает."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="5m", direction="LONG", strength=80))
        r.add_signal(_sig(tf="15m", direction="LONG", strength=75))
        r.add_signal(_sig(tf="1h", direction="LONG", strength=60))
        d = r.resolve("BTCUSDT")
        assert d.action == "UPGRADE"
        assert d.chosen_signal.timeframe == "1h"
        assert len(d.rejected_signals) == 2

    def test_same_tf_same_direction_chooses_better_rr(self):
        """Два сигнала на 15m LONG с разным RR → лучший RR побеждает."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG", rr=2.5, strength=70))
        r.add_signal(_sig(tf="15m", direction="LONG", rr=4.0, strength=65))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"  # same TF → not UPGRADE
        assert d.chosen_signal.rr_ratio == 4.0

    def test_upgrade_includes_reason_with_tfs(self):
        r = MultiTFResolver()
        r.add_signal(_sig(tf="5m", direction="SHORT"))
        r.add_signal(_sig(tf="1h", direction="SHORT"))
        d = r.resolve("BTCUSDT")
        assert "5m" in d.reason
        assert "1h" in d.reason


# ---------------------------------------------------------------------------
# TestContradictions — LONG vs SHORT на разных ТФ
# ---------------------------------------------------------------------------

class TestContradictions:
    def test_senior_tf_wins_long(self):
        """5m SHORT vs 1h LONG → 1h LONG побеждает."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="5m", direction="SHORT", strength=90))
        r.add_signal(_sig(tf="1h", direction="LONG", strength=60))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.chosen_signal.direction == "LONG"
        assert d.chosen_signal.timeframe == "1h"
        assert d.conflict_type == "contradiction"

    def test_senior_tf_wins_short(self):
        """15m LONG vs 1h SHORT → 1h SHORT побеждает."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG", strength=85))
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=65))
        d = r.resolve("BTCUSDT")
        assert d.chosen_signal.direction == "SHORT"
        assert d.conflict_type == "contradiction"

    def test_same_tf_contradiction_rejected(self):
        """15m LONG vs 15m SHORT → REJECT (неопределённость)."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=70))
        d = r.resolve("BTCUSDT")
        assert d.action == "REJECT"
        assert d.conflict_type == "contradiction"
        assert "неопределённость" in d.reason

    def test_three_tf_mixed(self):
        """5m LONG + 15m SHORT + 1h SHORT → 1h SHORT побеждает."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="5m", direction="LONG", strength=90))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=75))
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=60))
        d = r.resolve("BTCUSDT")
        assert d.chosen_signal.direction == "SHORT"
        assert d.chosen_signal.timeframe == "1h"


# ---------------------------------------------------------------------------
# TestMTFBiasIntegration — Resolver + MTF Bias арбитраж
# ---------------------------------------------------------------------------

class TestMTFBiasIntegration:
    def test_same_tf_contradiction_resolved_by_bias_long(self):
        """15m LONG vs 15m SHORT + MTF Bias LONG 80% → LONG побеждает."""
        r = MultiTFResolver()
        r.set_mtf_bias("BTCUSDT", "LONG", 80)
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=70))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.chosen_signal.direction == "LONG"
        assert d.conflict_type == "contradiction_bias_resolved"
        assert "MTF Bias LONG" in d.reason

    def test_same_tf_contradiction_resolved_by_bias_short(self):
        """15m LONG vs 15m SHORT + MTF Bias SHORT 75% → SHORT побеждает."""
        r = MultiTFResolver()
        r.set_mtf_bias("BTCUSDT", "SHORT", 75)
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=70))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.chosen_signal.direction == "SHORT"

    def test_weak_bias_does_not_resolve(self):
        """MTF Bias 50% (< 60% порог) → REJECT остаётся."""
        r = MultiTFResolver()
        r.set_mtf_bias("BTCUSDT", "LONG", 50)
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=70))
        d = r.resolve("BTCUSDT")
        assert d.action == "REJECT"

    def test_neutral_bias_does_not_resolve(self):
        """MTF Bias NEUTRAL 90% → REJECT (нет направления)."""
        r = MultiTFResolver()
        r.set_mtf_bias("BTCUSDT", "NEUTRAL", 90)
        r.add_signal(_sig(tf="15m", direction="LONG", strength=70))
        r.add_signal(_sig(tf="15m", direction="SHORT", strength=70))
        d = r.resolve("BTCUSDT")
        assert d.action == "REJECT"

    def test_bias_ignored_when_different_tf_priority(self):
        """5m LONG vs 1h SHORT → 1h побеждает даже если Bias=LONG."""
        r = MultiTFResolver()
        r.set_mtf_bias("BTCUSDT", "LONG", 90)
        r.add_signal(_sig(tf="5m", direction="LONG", strength=80))
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=60))
        d = r.resolve("BTCUSDT")
        # Старший ТФ побеждает — Bias НЕ переворачивает иерархию ТФ
        assert d.chosen_signal.direction == "SHORT"
        assert d.conflict_type == "contradiction"

    def test_no_bias_set_still_rejects(self):
        """Без set_mtf_bias → обычный REJECT при равном приоритете."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG"))
        r.add_signal(_sig(tf="15m", direction="SHORT"))
        d = r.resolve("BTCUSDT")
        assert d.action == "REJECT"


# ---------------------------------------------------------------------------
# TestDedupWindow — старые сигналы вне окна очищаются
# ---------------------------------------------------------------------------

class TestDedupWindow:
    def test_old_signal_evicted(self):
        """Сигнал старше окна дедупликации не учитывается."""
        r = MultiTFResolver(config={"multi_tf.dedup_window_sec": 60})
        old_ts = datetime.now() - timedelta(seconds=120)
        r.add_signal(_sig(tf="5m", direction="LONG", ts=old_ts))
        # При добавлении нового — старый будет отфильтрован
        r.add_signal(_sig(tf="15m", direction="SHORT"))
        d = r.resolve("BTCUSDT")
        # Только 15m SHORT осталось (5m LONG был отфильтрован)
        assert d.action == "ACCEPT"
        assert d.chosen_signal.direction == "SHORT"

    def test_fresh_signals_kept(self):
        r = MultiTFResolver(config={"multi_tf.dedup_window_sec": 600})
        r.add_signal(_sig(tf="5m", direction="LONG"))
        r.add_signal(_sig(tf="15m", direction="LONG"))
        d = r.resolve("BTCUSDT")
        assert d.action == "UPGRADE"


# ---------------------------------------------------------------------------
# TestResolveAndClear
# ---------------------------------------------------------------------------

class TestResolveAndClear:
    def test_clears_buffer(self):
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m"))
        d = r.resolve_and_clear("BTCUSDT")
        assert d.action == "ACCEPT"
        # Буфер очищен
        d2 = r.resolve("BTCUSDT")
        assert d2.action == "REJECT"

    def test_stats_tracked(self):
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m"))
        r.resolve_and_clear("BTCUSDT")
        stats = r.get_stats()
        assert stats["total"] == 1
        assert stats["by_type"]["clean"] == 1

    def test_multiple_symbols_independent(self):
        """Сигналы разных символов не конфликтуют."""
        r = MultiTFResolver()
        r.add_signal(_sig(symbol="BTCUSDT", tf="5m", direction="LONG"))
        r.add_signal(_sig(symbol="ETHUSDT", tf="15m", direction="SHORT"))
        d_btc = r.resolve("BTCUSDT")
        d_eth = r.resolve("ETHUSDT")
        assert d_btc.chosen_signal.direction == "LONG"
        assert d_eth.chosen_signal.direction == "SHORT"


# ---------------------------------------------------------------------------
# TestValidateConfig
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def test_single_tf_ok(self):
        ok, msg = validate_multi_tf_config(["15m"])
        assert ok

    def test_three_tf_ok(self):
        ok, msg = validate_multi_tf_config(["5m", "15m", "1h"])
        assert ok

    def test_empty_fails(self):
        ok, msg = validate_multi_tf_config([])
        assert not ok

    def test_unknown_tf_fails(self):
        ok, msg = validate_multi_tf_config(["5m", "2h"])
        assert not ok
        assert "2h" in msg

    def test_wrong_order_fails(self):
        ok, msg = validate_multi_tf_config(["1h", "15m", "5m"])
        assert not ok
        assert "младшего к старшему" in msg

    def test_too_many_fails(self):
        ok, msg = validate_multi_tf_config(["1m", "5m", "15m", "1h"])
        assert not ok

    def test_too_close_1m_3m_fails(self):
        ok, msg = validate_multi_tf_config(["1m", "3m"])
        assert not ok
        assert "близки" in msg

    def test_too_close_30m_45m_fails(self):
        ok, msg = validate_multi_tf_config(["30m", "45m"])
        assert not ok

    def test_valid_pair_5m_1h(self):
        ok, msg = validate_multi_tf_config(["5m", "1h"])
        assert ok


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_clear_all(self):
        r = MultiTFResolver()
        r.add_signal(_sig(symbol="BTCUSDT"))
        r.add_signal(_sig(symbol="ETHUSDT"))
        r.clear()
        assert r.resolve("BTCUSDT").action == "REJECT"
        assert r.resolve("ETHUSDT").action == "REJECT"

    def test_clear_single_symbol(self):
        r = MultiTFResolver()
        r.add_signal(_sig(symbol="BTCUSDT"))
        r.add_signal(_sig(symbol="ETHUSDT"))
        r.clear("BTCUSDT")
        assert r.resolve("BTCUSDT").action == "REJECT"
        assert r.resolve("ETHUSDT").action == "ACCEPT"

    def test_strength_tiebreaker(self):
        """При одинаковом ТФ и RR → побеждает более сильный."""
        r = MultiTFResolver()
        r.add_signal(_sig(tf="15m", direction="LONG", rr=3.0, strength=60))
        r.add_signal(_sig(tf="15m", direction="LONG", rr=3.0, strength=85))
        d = r.resolve("BTCUSDT")
        assert d.chosen_signal.strength == 85

    def test_stats_limit_50(self):
        r = MultiTFResolver()
        for i in range(60):
            r.add_signal(_sig(symbol=f"SYM{i}"))
            r.resolve_and_clear(f"SYM{i}")
        assert len(r._last_decisions) == 50
