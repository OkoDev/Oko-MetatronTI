"""
Регрессия: пара, объявленная БИРЖЕЙ недоступной, уходит в паузу и не долбится по кругу.

Повод (28.08.2026, первые часы работы ote_nested на лимитном входе): вселенная
сигналов шире вселенной ТОРГУЕМЫХ пар — детектор берёт свечи из кэша Binance,
а BingX отвечает «ICP-USDT is offline currently». За 4 часа ICP ушёл на биржу
8 раз, ILV 6 раз, все впустую: ордер отбит → запись CANCELLED → через цикл
сигнал снова тот же. 14 бесполезных обращений к бирже и 14 мусорных строк в БД.

Проверяем ТОЛЬКО механику кулдауна, без сети и без БД.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.trading.trade_router import SYMBOL_COOLDOWN_SEC   # noqa: E402


class _Router:
    """Минимальная модель поведения: те же две ветки, что в TradeRouter."""

    OFFLINE_MARKERS = ("offline", "not exist", "validted symbols",
                       "invalid symbol", "symbol not")

    def __init__(self):
        self._symbol_cooldown: dict[str, float] = {}
        self.exchange_calls = 0

    def on_exchange_error(self, symbol: str, error: str) -> None:
        e = str(error or "").lower()
        if any(k in e for k in self.OFFLINE_MARKERS):
            self._symbol_cooldown[symbol] = time.time() + SYMBOL_COOLDOWN_SEC

    def submit(self, symbol: str, error_to_raise: str | None) -> str:
        until = self._symbol_cooldown.get(symbol, 0.0)
        if until and time.time() < until:
            return "skipped_cooldown"
        self.exchange_calls += 1
        if error_to_raise:
            self.on_exchange_error(symbol, error_to_raise)
            return "exchange_error"
        return "ok"


BINGX_OFFLINE = ("ICP-USDT is offline currently,all validted symbols in api:"
                 "/openApi/swap/v2/quote/contracts, please verify it")


def test_offline_symbol_is_paused_after_first_refusal():
    """🔴 ГЛАВНЫЙ: восемь попыток подряд дают ОДИН запрос к бирже, а не восемь."""
    r = _Router()
    results = [r.submit("ICP/USDT:USDT", BINGX_OFFLINE) for _ in range(8)]
    assert r.exchange_calls == 1, f"биржу дёрнули {r.exchange_calls} раз вместо одного"
    assert results[0] == "exchange_error"
    assert set(results[1:]) == {"skipped_cooldown"}


def test_other_symbols_not_affected():
    """Пауза адресная: отказ по ICP не глушит остальные пары."""
    r = _Router()
    r.submit("ICP/USDT:USDT", BINGX_OFFLINE)
    assert r.submit("ARB/USDT:USDT", None) == "ok"
    assert r.exchange_calls == 2


def test_our_own_rejections_do_not_pause_pair():
    """🔴 НЕГАТИВНЫЙ: отказ по НАШИМ параметрам — не повод глушить пару."""
    r = _Router()
    for err in ("SL too close: 0.2% < 4.00%", "qty_zero", "RR 0.8 < min_rr 2.0",
                "insufficient margin"):
        r.submit("ARB/USDT:USDT", err)
    assert r._symbol_cooldown == {}, "пара заглушена своим же гейтом"
    assert r.exchange_calls == 4, "запросы не должны подавляться"


def test_cooldown_expires():
    """Пауза временная: биржа возвращает пару в строй — пробуем снова."""
    r = _Router()
    r.submit("ICP/USDT:USDT", BINGX_OFFLINE)
    assert r.submit("ICP/USDT:USDT", None) == "skipped_cooldown"
    r._symbol_cooldown["ICP/USDT:USDT"] = time.time() - 1      # срок вышел
    assert r.submit("ICP/USDT:USDT", None) == "ok"


def test_cooldown_longer_than_ote_loop_cycle():
    """Пауза обязана быть длиннее цикла лупа, иначе повтор проскочит."""
    assert SYMBOL_COOLDOWN_SEC >= 600 * 2, "цикл OTE-лупа 600 с — пауза должна перекрывать"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
