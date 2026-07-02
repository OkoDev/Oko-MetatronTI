"""USDT.D режим-детектор (03.07.2026) — сильнейший гейт из протестированных.

Валидация (usdtd 300д TW + atr_S2 бэктест): risk-off (USDT.D>MA20) = +0.735%/сд (n=822);
risk-on (<MA20) = −0.569%/сд (n=347) — разделение 1.3%. Обратная корреляция с альтами
same-day −0.78..−0.95 (лага нет → это РЕЖИМ-барометр, не предиктор).

Источники: история = таблица usdtd (TW CRYPTOCAP:USDT.D, снята через MCP) + live = CoinGecko
/global (бесплатно). Источники расходятся по уровню (~0.4пп, разный состав TOTAL) → TW-ряд
нормализуется offset'ом к CG при склейке; накопленный CG-ряд (usdtd_cg) со временем вытесняет TW.
risk_off = последнее значение > MA20 дневных значений. Fail-open (None при ошибках).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("ohlcv_cache.db")
_CG_URL = "https://api.coingecko.com/api/v3/global"
_CACHE_TTL = 4 * 3600            # live-замер не чаще раза в 4ч
_MA_LEN = 20

_last_fetch: float = 0.0
_last_result: bool | None = None


def _fetch_cg_usdtd() -> float | None:
    try:
        r = json.load(urllib.request.urlopen(_CG_URL, timeout=15))
        return float(r["data"]["market_cap_percentage"]["usdt"])
    except Exception as e:  # noqa: BLE001
        logger.debug("[USDTD] CoinGecko fetch error: %s", e)
        return None


def _series(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    """Склеенный дневной ряд: TW-история (норм. offset'ом) + CG-замеры. [(date, value)] по датам."""
    conn.execute("""CREATE TABLE IF NOT EXISTS usdtd_cg (date TEXT PRIMARY KEY, value REAL)""")
    cg = dict(conn.execute("SELECT date, value FROM usdtd_cg ORDER BY date").fetchall())
    tw = {}
    try:
        for t_ms, close in conn.execute("SELECT time, close FROM usdtd ORDER BY time").fetchall():
            d = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            tw[d] = float(close)
    except sqlite3.OperationalError:
        pass                                        # таблицы usdtd может не быть
    if cg and tw:
        # offset по первой общей дате (или ближайшей паре TW-конец/CG-начало)
        common = sorted(set(tw) & set(cg))
        if common:
            off = tw[common[0]] - cg[common[0]]
        else:
            off = tw[max(tw)] - cg[min(cg)]
        tw = {d: v - off for d, v in tw.items()}
    merged = dict(tw)
    merged.update(cg)                               # CG-замеры приоритетнее
    return sorted(merged.items())


def get_usdtd_risk_off() -> bool | None:
    """True = risk-off (USDT.D > MA20, среда SHORT-эджа) · False = risk-on · None = нет данных.
    Синхронный (sqlite+http с таймаутом), дёргать редко (кэш 4ч)."""
    global _last_fetch, _last_result
    now = time.time()
    if now - _last_fetch < _CACHE_TTL and _last_result is not None:
        return _last_result
    try:
        conn = sqlite3.connect(_DB)
        try:
            # live-замер → upsert на сегодня
            val = _fetch_cg_usdtd()
            if val is not None:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                conn.execute("""CREATE TABLE IF NOT EXISTS usdtd_cg (date TEXT PRIMARY KEY, value REAL)""")
                conn.execute("INSERT OR REPLACE INTO usdtd_cg(date, value) VALUES (?, ?)", (today, val))
                conn.commit()
            ser = _series(conn)
        finally:
            conn.close()
        if len(ser) < _MA_LEN + 1:
            return None
        vals = [v for _, v in ser]
        ma = sum(vals[-_MA_LEN:]) / _MA_LEN
        _last_result = vals[-1] > ma
        _last_fetch = now
        logger.info("[USDTD] %.3f%% vs MA20 %.3f%% → %s",
                    vals[-1], ma, "RISK-OFF (short-среда)" if _last_result else "RISK-ON")
        return _last_result
    except Exception as e:  # noqa: BLE001
        logger.debug("[USDTD] regime error: %s", e)
        return None
