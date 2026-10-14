# -*- coding: utf-8 -*-
"""Маппинг тикеров BingX↔Binance Vision для мемкоинов-мультипликаторов (ARCH-147.11, паспорт инструмента).

6 пар замерли на 15.09: Binance USDT-M называет мемкоины с ×1000 (FLOKIUSDT → 1000FLOKIUSDT), докачка по
BingX-имени получала 404. _vision_sym переводит имя для URL; хранение остаётся под BingX-именем. Если маппинг
собьётся — ряд снова замрёт молча, поэтому обе ветки (мультипликатор и обычное имя) под golden-case."""
from __future__ import annotations

import scripts.fetch_binance_vision as fb


def test_multiplier_coins_mapped_to_1000_name():
    """3 мультипликатора переводятся на Binance-имя 1000X (проверено 14.10: масштаб паркетов совпал 1:1)."""
    assert fb._vision_sym("FLOKIUSDT") == "1000FLOKIUSDT"
    assert fb._vision_sym("RATSUSDT") == "1000RATSUSDT"
    assert fb._vision_sym("LUNCUSDT") == "1000LUNCUSDT"


def test_plain_coins_pass_through():
    """Остальные (PUNDIX/VTHO/XTZ) на Binance зовутся как есть — маппинг не трогает."""
    for sym in ("PUNDIXUSDT", "VTHOUSDT", "XTZUSDT", "BTCUSDT", "ETHUSDT"):
        assert fb._vision_sym(sym) == sym


def test_download_url_uses_mapped_name(monkeypatch):
    """URL скачивания строится по Binance-имени, а не по BingX (иначе 404)."""
    captured = {}

    def fake_fetch(url, tries=3):
        captured["url"] = url
        return []

    monkeypatch.setattr(fb, "_fetch_zip", fake_fetch)
    fb._download_month("FLOKIUSDT", "1m", "2026-09")
    assert "1000FLOKIUSDT/1m/1000FLOKIUSDT-1m-2026-09.zip" in captured["url"]
    assert "/FLOKIUSDT/" not in captured["url"]

    fb._download_day("LUNCUSDT", "1m", "2026-10-01")
    assert "1000LUNCUSDT-1m-2026-10-01.zip" in captured["url"]
