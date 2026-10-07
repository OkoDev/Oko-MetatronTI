# -*- coding: utf-8 -*-
"""Инвариант: лимитный источник, который ходит на биржу, обязан быть в центральном лайфцикле.

Класс ошибки встретился ДВАЖДЫ:
  · 21.08 — `impulse_fib_15m` выпал из лайфцикла (шаблон LIKE не ловил суффикс);
  · 07.10 — `choch_wavec_4h`: в политике не было `pending_lifecycle: true`, а запасной
    список `_CENTRAL_LIFECYCLE` знает только `choch_wavec`. Лимитки исполнялись на бирже,
    а в SIM висели PENDING_ENTRY — дрифт «на бирже есть, в SIM нет» (ENSO 6 дней, KGEN).

Без лайфцикла у лимитки нет ни перевода в OPEN по филу, ни снятия по TTL. Тест прогоняют
ворота `pre-push`, поэтому третий такой источник не уедет на сервер молча.
"""
from core.infra.config_loader import ConfigLoader
from core.trading.source_registry import pending_sources


def _exchange_limit_sources(cfg):
    pol = cfg.get("signal_router.source_policies", {}) or {}
    return sorted(
        s for s, p in pol.items()
        if str((p or {}).get("entry_order_type", "")).upper() == "LIMIT"
        and bool((p or {}).get("exchange_enabled", False))
    )


def test_every_exchange_limit_source_is_managed():
    cfg = ConfigLoader("config.yaml")
    managed = set(pending_sources(cfg))
    orphans = [s for s in _exchange_limit_sources(cfg) if s not in managed]
    assert not orphans, (
        f"лимитные источники идут на биржу БЕЗ лайфцикла: {orphans} — "
        f"поставьте `pending_lifecycle: true` в их политике (signal_router.source_policies)"
    )


def test_choch_wavec_4h_is_managed():
    """Точечная проверка источника, на котором класс проявился 07.10."""
    cfg = ConfigLoader("config.yaml")
    assert "choch_wavec_4h" in pending_sources(cfg)
