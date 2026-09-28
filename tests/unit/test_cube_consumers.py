# -*- coding: utf-8 -*-
"""Потребители шины вместо заглушек (28.09.2026): Сфера 9 (нарратив) и теневые «режим ↔ WT»."""
import sqlite3
from types import SimpleNamespace

from core.context.pair_context import PairContextBus, SphereEvent
from core.context.shadow_consumers import Onset, wire
from core.intelligence.narrative_builder import narrative_consumer

SYM = "ETH/USDT:USDT"


def _rec():
    return SimpleNamespace(action="BUY", direction="LONG", overall_strength=65, confidence=0.7,
                           metadata={"strategy_name": "pivot_reversal"})


def test_narrative_written_inside_publish():
    """Синхронный подписчик: нарратив в metadata ДО возврата из publish (нужно для features_json)."""
    bus = PairContextBus()
    bus.subscribe(SphereEvent.RECOMMENDATION_BUILT, narrative_consumer(bus))
    rec = _rec()
    bus.publish(SYM, SphereEvent.RECOMMENDATION_BUILT, {"recommendation": rec})
    narr = rec.metadata.get("narrative")
    assert narr and narr["text"]
    assert {"p_win", "mode", "key_factors", "confidence", "smc_factors", "smc_flat"} <= set(narr)
    assert bus.get(SYM).last_narrative == narr["text"]          # Сфера 9 опубликовала NARRATIVE_BUILT


def test_without_subscriber_metadata_left_for_fallback():
    """Нет подписчика (скрипты без бота) → metadata пуст → анализ строит нарратив сам, как раньше."""
    bus = PairContextBus()
    rec = _rec()
    bus.publish(SYM, SphereEvent.RECOMMENDATION_BUILT, {"recommendation": rec})
    assert "narrative" not in rec.metadata
    narrative_consumer(bus)(SYM, {"recommendation": rec})       # запасной путь trading_intelligence
    assert rec.metadata["narrative"]["text"]


def test_onset_counts_only_false_to_true():
    o = Onset()
    assert not o("k", True)       # первое наблюдение после старта — не возникновение
    assert not o("k", True)
    assert not o("k", False)
    assert o("k", True)           # было ложно → стало истинно
    assert not o("k", True)


def test_shadow_consumers_journal_onsets_with_price(tmp_path):
    db = tmp_path / "journal.db"
    bus = PairContextBus()
    assert wire(bus, db) == 2
    bus.publish(SYM, SphereEvent.OHLCV_UPDATED, {"tf": "15m", "rows": 1, "close": 100.0})
    bus.publish(SYM, SphereEvent.REGIME_UPDATED, {"regime": "TREND_UP", "mode": "TREND"})      # старт: ложно
    bus.publish(SYM, SphereEvent.WT_SNAP_UPDATED, {"4h": {"wt1": 10}})                         # старт: ложно
    bus.publish(SYM, SphereEvent.WT_VERDICT, {"label": "TREND_CONTINUATION", "confidence": 0.6})
    bus.publish(SYM, SphereEvent.WT_SNAP_UPDATED, {"4h": {"wt1": 75}})       # возникло → wt→regime
    bus.publish(SYM, SphereEvent.WT_SNAP_UPDATED, {"4h": {"wt1": 80}})       # держится → без записи
    bus.publish(SYM, SphereEvent.REGIME_UPDATED, {"regime": "TREND_UP", "mode": "REVERSAL"})   # → regime→wt
    rows = sqlite3.connect(db).execute(
        "SELECT consumer, px, decision FROM cube_reactions_shadow ORDER BY rowid").fetchall()
    assert [r[0] for r in rows] == ["wt→regime", "regime→wt"]
    assert rows[0][1] == 100.0
    assert "WT 4h +75" in rows[0][2]
