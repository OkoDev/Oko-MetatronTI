"""09.10 аудит TG (Егор «перенастраивай»): журнал отправок, маршрут типа бота в канал, смена повестки в пульсе."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import market_pulse as MP  # noqa: E402
from oko_feed import tg_journal as J  # noqa: E402


def test_journal_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "DIR", tmp_path)
    J.log("feed", True, "⚡ <b>ЛИКВИДАЦИИ</b>\nBTC", source="liq_ws")
    J.log("dm", False, "x", kind="confluence", source="oko-bot", to=0)
    R = J.read(1)
    assert [r["ch"] for r in R] == ["feed", "dm"]
    assert R[0]["head"].startswith("⚡ <b>ЛИКВИДАЦИИ</b> BTC") and R[1]["kind"] == "confluence"
    assert "неудачных 1" in J.summary(1)


class _Cfg(dict):
    def get(self, k, d=None):
        return {"telegram.route_to_channel": {"health_alert": "system"}}.get(k, d)


def test_bot_type_routed_to_channel(monkeypatch):
    import oko_feed.alerts as A
    from bot.monitoring import broadcast_with_subscription_check
    sent = []
    monkeypatch.setattr(A, "send_tg", lambda text, channel="main", reply_to=None: sent.append((channel, text)) or 1)
    bot = SimpleNamespace(config=_Cfg(), subscribers={1, 2})     # подписчики есть, но в личку не идёт
    asyncio.run(broadcast_with_subscription_check(bot, "🩺 health", "health_alert"))
    assert sent == [("system", "🩺 health")]


def test_agenda_change_needs_two_polls(monkeypatch):
    seq = iter([{"mode": "A", "light": "yellow"}, {"mode": "A", "light": "green"},
                {"mode": "A", "light": "green"}, {"mode": "A", "light": "green"}])

    def fake():
        d = next(seq)
        return {**d, "reason": "r", "ts": 1e10, "long": ["HBAR"], "short": []}
    monkeypatch.setattr(MP, "fetch_agenda", fake)
    prev, m = {}, {"liq": None}
    assert MP.agenda_step(prev, m, "НОРМА", 1e10) is None          # база
    assert MP.agenda_step(prev, m, "НОРМА", 1e10) is None          # новое увидено 1 раз
    msg = MP.agenda_step(prev, m, "НОРМА", 1e10)                    # 2 раза подряд → сообщение
    assert msg and "ПОВЕСТКА: A" in msg and "Работаем" in msg and "HBAR" in msg
    assert MP.agenda_step(prev, m, "НОРМА", 1e10) is None          # то же самое не повторяем


def test_facts_by_definition():
    assert any("4/4 лет" in f for f in MP.facts({}, "СЛИВ"))
    assert MP.facts({}, "НОРМА") == []
    assert any("широкий слив" in f for f in MP.facts({"6h": {"dn": 0.6}}, "НОРМА"))
    assert any("не мерился" in f for f in MP.facts({}, "ВЫНОС"))
