"""Тест дедупа master↔sub в PairContextBus.all_positions() (27.06).

Корень: мастер-ключ (acc1) тянет позиции И суб-аккаунтов через ACCOUNT_UPDATE →
одна позиция попадает в шину дважды (acc1-фантом + acc2-реал). all_positions()
дедупит: суб авторитетен для своих позиций, его (symbol, side) вытесняет копию мастера.
"""
from core.context.pair_context import PairContextBus


def test_master_sub_dedup_drops_master_phantom():
    """21 = 11 уникальных + 10 дублей → all_positions() отдаёт 11, дубли = суб (acc2)."""
    bus = PairContextBus()
    # acc1 (master) тянет ВСЁ: своя ETH + 10 позиций суба (фантомы)
    bus.update_position(1, "ETH/USDT:USDT", qty=1.0, side="LONG")
    sub_syms = [f"S{i}/USDT:USDT" for i in range(10)]
    for s in sub_syms:
        bus.update_position(1, s, qty=2.0, side="SHORT")   # фантом мастера
        bus.update_position(2, s, qty=2.0, side="SHORT")   # реал суба (свой ключ)

    out = bus.all_positions()
    assert len(out) == 11, f"ожидали 11 уникальных, получили {len(out)}"
    # все 10 суб-позиций атрибутированы acc2 (реальный владелец), не acc1
    for p in out:
        if p["symbol"] in sub_syms:
            assert p["account_id"] == 2, f"{p['symbol']} должна быть acc2, не {p['account_id']}"
    # своя позиция мастера осталась за acc1
    eth = [p for p in out if p["symbol"] == "ETH/USDT:USDT"]
    assert len(eth) == 1 and eth[0]["account_id"] == 1


def test_no_sub_keeps_all_master_positions():
    """Single-account (только master) — дедуп ничего не режет."""
    bus = PairContextBus()
    bus.update_position(1, "BTC/USDT:USDT", qty=0.1, side="LONG")
    bus.update_position(1, "ETH/USDT:USDT", qty=1.0, side="SHORT")
    out = bus.all_positions()
    assert len(out) == 2
    assert all(p["account_id"] == 1 for p in out)


def test_opposite_sides_not_deduped():
    """acc1 BTC-SHORT (своя) + acc2 BTC-LONG (своя) — разные side → обе остаются."""
    bus = PairContextBus()
    bus.update_position(1, "BTC/USDT:USDT", qty=0.1, side="SHORT")  # своя acc1
    bus.update_position(2, "BTC/USDT:USDT", qty=0.2, side="LONG")   # своя acc2
    out = bus.all_positions()
    assert len(out) == 2, "разные стороны не должны дедупиться"
    by_acc = {p["account_id"]: p["side"] for p in out}
    assert by_acc == {1: "SHORT", 2: "LONG"}
