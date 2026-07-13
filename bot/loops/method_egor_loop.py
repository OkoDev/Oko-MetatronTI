"""
METHOD-EGOR loop — боевой вход по методу Егора на VST (05.07, добро Егора «в бой, VST песочница»).

Геометрия (ядро core.smc.method_egor, честный бэктест WR55%, 15m/4h OOS+): вход на ОТКАТЕ
(ote_retest provisional) на РАЗВОРОТЕ у экстремума большого 4h импульса + OTE-цели + тугой
локальный стоп. Вход MARKET + гейт свежести (детект=свежий ретест → цена в OTE-зоне сейчас →
вход близко к зоне, без LIMIT pending-orphan рисков; урок oko_ote). Реальный филл ≈ сигнал —
в отличие от ote_nested, что льёт входом «в воздухе» (не на откате).

🧲 ТОЛПА-ГЕЙТ (недостающий кусок метода, только live): funding из radar_state.
  SHORT у вершины разрешён только если funding>0 (лонги перегреты = топливо вниз);
  LONG у дна — funding<0 (шорты платят = топливо вверх). Отсекает сетапы без топлива разворота.

Reuse: обвязка radar (multi-TP лестница, BE, TSL, positionId) через trade_router source='method_egor'.
Gated: config trading.method_egor.enabled (default false). Порядок: детект→толпа-гейт→register.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

import pandas as pd

from bot.loops.arch104_observer_loop import _get_active_pairs, _fetch_df

logger = logging.getLogger(__name__)

DEFAULT_SCAN_SEC = 900
CONCURRENCY = 3


def _cfg(bot) -> dict:
    try:
        return bot.config.get("trading.method_egor", {}) or {}
    except Exception:
        return {}


def _liquid_pairs(bot, pairs: list[str], topn: int) -> list[str]:
    ranked = []
    for p in pairs:
        try:
            tk = bot.data_collector.get_cached_ticker(p) if hasattr(bot.data_collector, "get_cached_ticker") else None
            qv = float((tk or {}).get("quoteVolume") or 0) if tk else 0
        except Exception:
            qv = 0
        ranked.append((qv, p))
    ranked.sort(reverse=True)
    picked = [p for qv, p in ranked if qv > 0][:topn]
    return picked or pairs[:topn]


def _open_count(db_path) -> int:
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"method_egor\"%'").fetchone()[0]
    except Exception:
        return 10**9


def _symbol_busy(db_path, symbol: str) -> bool:
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status IN ('OPEN','PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"method_egor\"%' LIMIT 1",
                (symbol,)).fetchone() is not None
    except Exception:
        return True


def _crowd_funding(symbol: str) -> float | None:
    """funding из radar_state (radar пишет в oko_feed external_data.db). symbol BTC/USDT → BTC."""
    base = symbol.split("/")[0].replace(":USDT", "")
    try:
        from oko_feed.store import conn
        c = conn()
        try:
            row = c.execute("SELECT funding FROM radar_state WHERE symbol=?", (base,)).fetchone()
        finally:
            c.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _crowd_confirms(direction: str, funding: float | None) -> bool | None:
    """Толпа = топливо разворота. None = нет данных радара (не блокируем, но помечаем)."""
    if funding is None:
        return None
    if direction == "SHORT":
        return funding > 0        # лонги платят = перегрев лонгов = топливо вниз
    return funding < 0            # шорты платят = топливо вверх


async def method_egor_loop(bot) -> None:
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[METHOD-EGOR] disabled (trading.method_egor.enabled=false) — loop не стартует")
        return
    try:
        from core.smc.method_egor import detect_method_egor
        from core.smc.ote_matrix import structure_trend
    except ImportError as e:
        logger.error("[METHOD-EGOR] detector import failed: %s", e)
        return
    scan_sec = float(cfg.get("scan_sec", DEFAULT_SCAN_SEC) or DEFAULT_SCAN_SEC)
    fresh_bars = int(cfg.get("fresh_bars", 2))
    max_pos = int(cfg.get("max_positions", 6))
    max_syms = int(cfg.get("max_symbols", 60))
    edge = float(cfg.get("edge", 0.5))
    require_crowd = bool(cfg.get("require_crowd", True))     # толпа-гейт как ЖЁСТКИЙ фильтр
    logger.info("[METHOD-EGOR] started: scan=%ds fresh=%d max_pos=%d max_syms=%d edge=%.2f crowd_gate=%s",
                scan_sec, fresh_bars, max_pos, max_syms, edge, require_crowd)

    first = True
    while True:
        try:
            await asyncio.sleep(60 if first else scan_sec)
            first = False
            t0 = time.time()
            pairs = await _get_active_pairs(bot)
            if not pairs:
                continue
            pairs = _liquid_pairs(bot, pairs, max_syms)
            sem = asyncio.Semaphore(CONCURRENCY)
            fired = [0]

            async def _scan(sym):
                async with sem:
                    try:
                        if await _scan_one(bot, sym, detect_method_egor, structure_trend,
                                           fresh_bars, edge, max_pos, require_crowd):
                            fired[0] += 1
                    except Exception as e:
                        logger.debug("[METHOD-EGOR] %s: %s", sym, e)

            await asyncio.gather(*[_scan(s) for s in pairs])
            logger.info("[METHOD-EGOR] cycle: %d пар, fired=%d за %.1fs", len(pairs), fired[0], time.time() - t0)
        except asyncio.CancelledError:
            logger.info("[METHOD-EGOR] loop cancelled")
            raise
        except Exception as e:
            logger.exception("[METHOD-EGOR] loop error: %s", e)
            await asyncio.sleep(scan_sec)


async def _scan_one(bot, symbol, detect_method_egor, structure_trend,
                    fresh_bars, edge, max_pos, require_crowd) -> bool:
    dc = getattr(bot, "data_collector", None)
    if dc is None:
        return False
    df_4h, df_15m = await asyncio.gather(
        _fetch_df(dc, symbol, "4h", 400),
        _fetch_df(dc, symbol, "15m", 1500),
    )
    if df_4h is None or df_15m is None or len(df_4h) < 80 or len(df_15m) < 300:
        return False
    for _df in (df_4h, df_15m):
        if "ts" in _df.columns:
            _df.index = pd.to_datetime(_df["ts"], utc=True, errors="coerce")
        elif "time" in _df.columns:
            _df.index = pd.to_datetime(_df["time"], unit="ms", utc=True, errors="coerce")

    def _detect():
        t4 = df_4h.tail(400)
        st = structure_trend(t4)
        # гейты аудита 06.07 (LINK: «большой 4h» = микро-нога 4.3%, RR1<1 у 4/6 shadow):
        # ATR(4h) → мин-масштаб ноги; возраст экстремума в 4h-барах → не против свежего слома.
        # RR-гейт и SL-буфер активны в ядре по дефолту.
        from core.smc.ote_matrix import _atr
        ext_age = None
        if st.get("extreme_ts") is not None:
            try:
                ext_age = int((t4.index[-1] - st["extreme_ts"]) / pd.Timedelta("4h"))
            except Exception:
                pass
        # НОГА = impulse_origin→extreme (07.07, Егор: «вершина ВСЕГО импульса», ETH 2464 vs
        # дрейфующий слом 2157). Фолбэк на break_level — origin пуст только на init-старте истории.
        return detect_method_egor(df_15m, htf_trend=st.get("trend"),
                                  htf_break=st.get("impulse_origin") or st.get("break_level"),
                                  htf_extreme=st.get("extreme"), edge=edge, fresh_bars=fresh_bars,
                                  htf_atr=_atr(t4), htf_extreme_age_bars=ext_age)

    setups = await asyncio.get_running_loop().run_in_executor(None, _detect)
    if not setups:
        return False
    s = setups[0]
    # 🧲 ТОЛПА-ГЕЙТ: funding подтверждает разворот
    funding = _crowd_funding(symbol)
    confirms = _crowd_confirms(s["direction"], funding)
    if require_crowd and confirms is not True:
        logger.info("[METHOD-EGOR] %s %s: толпа не подтверждает (funding=%s) — skip",
                    symbol, s["direction"], funding)
        return False
    if _open_count(bot.trade_simulator.db_path) >= max_pos:
        logger.info("[METHOD-EGOR] %s свежий сетап, но max_positions %d — skip", symbol, max_pos)
        return False
    if _symbol_busy(bot.trade_simulator.db_path, symbol):
        return False
    await _register(bot, symbol, s, funding)
    return True


async def _register(bot, symbol, s, funding) -> None:
    try:
        from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    except ImportError as e:
        logger.warning("[METHOD-EGOR] import failed: %s", e)
        return
    is_long = s["direction"] == "LONG"
    tps = [float(t) for t in s["targets"] if t]
    if not tps:
        return
    # MARKET + гейт свежести (урок oko_ote config:751 — LIMIT pending-lifecycle без чекера =
    # orphan-риск). Детект = свежий ретест → цена СЕЙЧАС в OTE-зоне, MARKET входит близко к зоне.
    px_now = 0.0
    vol24 = 0.0
    try:
        tk = await bot.data_collector.get_ticker(symbol)
        if tk:
            px_now = float(tk.get("last") or tk.get("close") or 0)
            vol24 = float(tk.get("quoteVolume") or 0)
    except Exception:
        pass
    # гейт свежести: цена уже за целью или за стопом → сетап протух, skip
    if px_now > 0:
        if (tps[0] <= px_now) if is_long else (tps[0] >= px_now):
            logger.info("[METHOD-EGOR] %s %s: t1 уже пройдена (px=%.6g) — skip", symbol, s["direction"], px_now)
            return
        if (px_now <= float(s["sl"])) if is_long else (px_now >= float(s["sl"])):
            logger.info("[METHOD-EGOR] %s %s: цена за стопом (px=%.6g) — skip", symbol, s["direction"], px_now)
            return
    entry_px = px_now if px_now > 0 else float(s["entry"])
    rec = TradingRecommendation(
        symbol=symbol, action="BUY" if is_long else "SELL",
        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
        overall_strength=75, confidence=0.75, risk_level="MEDIUM", signals_count=1,
        supporting_signals=[], conflicting_signals=[],
        market_context=MarketContext(symbol=symbol, current_price=entry_px,
                                     volume_24h=vol24, volume_change_24h=0.0, price_change_24h=0.0),
        entry_price=entry_px, stop_loss=float(s["sl"]), take_profit=tps[0],
        sl_source="egor:local_tight", tp_source="egor:ote_big",
    )
    extra = {
        "signal_type_override": "method_egor",
        "trade_mode": "method_egor",
        "trigger_source": "egor:reversal_at_extreme",
        "egor_pos": round(float(s.get("pos", 0)), 3),
        "egor_htf_trend": s.get("htf_trend"),
        "egor_funding": funding,
        "radar_tps": tps,                     # OTE-лестница 0.5/0.62/0.705 → post-fill multi-TP
    }
    try:
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            res = await bot.trade_router.submit(rec, source="method_egor", extra_features=extra)
            tid = getattr(res, "trade_id", None)
            if tid:
                logger.info("[METHOD-EGOR] %s %s → #%s entry=%.6g sl=%.6g tps=%s funding=%s",
                            symbol, s["direction"], tid, entry_px, s["sl"], tps, funding)
            else:
                drops = "; ".join(f"{g}:{d}" for g, d in getattr(res, "hard_drops", [])) or "none"
                logger.info("[METHOD-EGOR] %s router dropped: %s", symbol, drops)
        else:
            logger.warning("[METHOD-EGOR] signal_router.enabled=false — не регистрирую")
    except Exception as e:
        logger.exception("[METHOD-EGOR] %s register error: %s", symbol, e)
