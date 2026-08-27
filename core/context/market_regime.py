# -*- coding: utf-8 -*-
"""Рыночный контекст, общий для торговых лупов (04.08.2026).

Две величины, доказавшие разделяющую силу на живых данных — и, что важно,
разделяющие РАЗНЫЕ источники С ПРОТИВОПОЛОЖНЫМ ЗНАКОМ:

  ac_regime() — кросс-секционная автокорреляция 6ч-доходностей по корзине ликвидных монет.
      Возвратные стратегии (наш фейд big-flush): импульсный режим PF 3.73 / возвратный 1.36.
      Импульсные стратегии (radar_pump/spring): ЗЕРКАЛЬНО — возвратный PF 3.14 / импульсный 0.72.

  funding_map() — ставки фондирования всех пар BingX (bulk).
      Низкая ставка = толпа в шортах = топливо отскоку (у фейда PF 3.00 против 1.06).

Обе — ЗАПИСЫВАЕМЫЕ ФИЧИ, не гейты: гейт режет частоту сильнее, чем поднимает качество
(проверено многократно). Решение о сайзинге принимает владелец.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

import numpy as np

logger = logging.getLogger(__name__)

# Корзина ликвидных монет для кросс-секционного режима. Отсутствующие на BingX молча пропускаем.
AC_BASKET = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "TRX",
             "NEAR", "APT", "ARB", "OP", "ATOM", "FIL", "INJ", "SUI", "TIA", "SEI", "AAVE", "UNI"]
# Пороги — терцили бэктеста 2024-2026
AC_LO, AC_HI = -0.0672, -0.0126

_AC = {"ts": 0.0, "val": None}
_FUND = {"ts": 0.0, "map": {}}
_BINGX_KLINES = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
_BINGX_PREMIUM = "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex"


def _get(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": "oko"})
    return json.load(urllib.request.urlopen(req, timeout=timeout)).get("data", [])


def ac_regime(ttl: float = 3600.0):
    """Кросс-секционная автокорреляция 6ч-доходностей (окно ~14д). Пересчёт раз в час.
    Возвращает float или None, если данные не получены."""
    now = time.time()
    if now - _AC["ts"] < ttl and _AC["val"] is not None:
        return _AC["val"]
    acs = []
    for base in AC_BASKET:
        try:
            d = _get(f"{_BINGX_KLINES}?symbol={base}-USDT&interval=1h&limit=400", timeout=10)
            cl = [float(k["close"]) for k in reversed(d)]      # BingX newest-first → хронология
            if len(cl) < 360:
                continue
            a = np.asarray(cl, dtype=float)
            r6 = a[6:] / a[:-6] - 1.0
            x, y = r6[6:][-336:], r6[:-6][-336:]               # окно 14 дней
            if len(x) > 100 and x.std() > 0 and y.std() > 0:
                acs.append(float(np.corrcoef(x, y)[0, 1]))
        except Exception:
            continue
    if acs:
        _AC["val"] = float(np.mean(acs))
        _AC["ts"] = now
        logger.info("[REGIME] AC=%.4f (%s) по %d монетам", _AC["val"], ac_label(_AC["val"]), len(acs))
    return _AC["val"]


def ac_label(v) -> str | None:
    if v is None:
        return None
    return "импульсный" if v >= AC_HI else ("возвратный" if v <= AC_LO else "середина")


def funding_map(ttl: float = 300.0) -> dict:
    """Ставки фондирования всех пар BingX в процентах (bulk, кэш 5 мин)."""
    now = time.time()
    if now - _FUND["ts"] < ttl and _FUND["map"]:
        return _FUND["map"]
    try:
        m = {str(t.get("symbol", "")).replace("-USDT", ""): float(t.get("lastFundingRate") or 0) * 100.0
             for t in _get(_BINGX_PREMIUM, timeout=15) if t.get("symbol")}
        if m:
            _FUND["map"] = m
            _FUND["ts"] = now
    except Exception:
        pass
    return _FUND["map"]


_TURN = {"ts": 0.0, "map": {}}
_BINGX_TICKER = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"


def turnover_map(ttl: float = 600.0) -> dict:
    """24ч-оборот всех пар BingX в USDT (bulk, кэш 10 мин).
    10.08: бэктест big-flush гонялся на ЛИКВИДНОЙ половине, а бот торгует все 520 пар —
    на хламе (GPUBSC, CATE) трёхбарный лоу оказывается в 20-50% от цены, и одна сделка
    даёт −48%. Гейт оборота возвращает живую вселенную к той, на которой мерился эдж."""
    now = time.time()
    if now - _TURN["ts"] < ttl and _TURN["map"]:
        return _TURN["map"]
    try:
        m = {str(t.get("symbol", "")).replace("-USDT", ""): float(t.get("quoteVolume") or 0)
             for t in _get(_BINGX_TICKER, timeout=15) if t.get("symbol")}
        if m:
            _TURN["map"] = m
            _TURN["ts"] = now
    except Exception:
        pass
    return _TURN["map"]


def context_features(base: str | None = None) -> dict:
    """Готовый набор фич рыночного контекста для extra_features любого источника."""
    v = ac_regime()
    out = {"mkt_ac_regime": round(v, 5) if v is not None else None,
           "mkt_ac_label": ac_label(v)}
    if base:
        f = funding_map().get(base)
        out["mkt_funding"] = round(f, 5) if f is not None else None
    return out
