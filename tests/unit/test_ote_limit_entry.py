"""
Регрессия перевода `ote_nested` на ЛИМИТНЫЙ вход (28.08.2026, команда Егора).

Каждый тест соответствует дефекту, который в этом проекте УЖЕ случался:

  1. `entry_order_type: LIMIT` объявлен, но не применяется — так и было у ote_nested:
     политика стояла с июля, а `signal_router.enabled` был false до 25.07, и старый
     путь ставил ордер МИМО политики, рыночным. Источник ни разу не торговал
     объявленным входом ([[bug_source_policies_deadpath_router_off]]).
  2. LIMIT без `pending_lifecycle` — заявка выпадает из проверки фила и отмены по TTL.
     Поймано у `impulse_fib_15m` 21.08.
  3. TTL по умолчанию вместо TTL источника — у `impulse_fib_15m` окно фила оказалось
     3 часа вместо 12, то есть бой торговал не ту механику, что мерили.
  4. Глобальный гейт режет источник целиком — `min_rr=2.0` так убил rangefade,
     `min_sl_dist=4.0` убил бы ote_nested (медиана стопа 0.63%).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.infra.config_loader import config                      # noqa: E402
from core.trading.source_registry import (                       # noqa: E402
    pending_sources, pending_sql, ttl_for, tf_for)

SRC = "ote_nested"
# Медиана стопа источника по 9472 боевым сделкам (замер 28.08).
MEDIAN_STOP_PCT = 0.63


def _policy():
    return (config.get("signal_router.source_policies", {}) or {}).get(SRC, {}) or {}


def test_entry_order_type_is_limit():
    """Дефект 1: вход обязан быть лимитным — ради этого вся правка."""
    assert str(_policy().get("entry_order_type", "")).upper() == "LIMIT"


def test_source_is_in_pending_lifecycle():
    """🔴 Дефект 2: без лайфцикла лимитка повиснет без проверки фила и без TTL."""
    assert SRC in pending_sources(), (
        "ote_nested с LIMIT-входом вне центрального лайфцикла — "
        "заявка не будет ни исполнена, ни отменена")
    assert f"'{SRC}'" in pending_sql()


def test_ttl_is_declared_not_default():
    """Дефект 3: TTL обязан считаться из ТФ источника, а не из общего дефолта."""
    ttl_h = ttl_for(SRC) / 3600.0
    assert tf_for(SRC) == "1h", "ТФ источника не объявлен — TTL посчитается не в тех барах"
    assert ttl_h == pytest.approx(4.0), f"TTL {ttl_h:.2f} ч вместо объявленных 4 (entry_ttl_bars×ТФ)"
    assert ttl_h != pytest.approx(0.5), "взят общий дефолт 1800 с — объявление не подхватилось"


def test_min_sl_dist_does_not_kill_native_geometry():
    """🔴 Дефект 4: глобальные 4.0% вырезали бы источник целиком (стоп 0.63%)."""
    per = (config.get("trading.min_sl_dist_per_strategy") or {})
    thr = per.get(SRC)
    assert thr is not None, "нет per-strategy исключения — сработает глобальный порог"
    assert thr < MEDIAN_STOP_PCT, (
        f"порог {thr}% выше медианного стопа {MEDIAN_STOP_PCT}% — источник будет молчать")
    assert thr > 0, "нулевой порог пропускает микростопы, которые косты съедают целиком"


def test_exchange_enabled_matches_intent():
    """Лимитный вход без выхода на биржу не проверить — это был бы SIM-полигон."""
    assert _policy().get("exchange_enabled") is True


def test_keys_agree_across_lookups():
    """Расхождение source ↔ trade_mode = молчаливый отказ (мина `wt_sideways`)."""
    assert _policy().get("trade_mode") == SRC


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
