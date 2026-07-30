# -*- coding: utf-8 -*-
"""RANGEFADE LOOP (Егор 30.07 «найди золотую стратегию») — первый эдж, переживший прокурора.
Бэктест 2024-26 causal: 1h ATRTrend UP + WT<порог (глубокий откат) → лонг, TP 1R, SL 3-барный лоу.
Медиана +0.66% (косты 0.15), 82% монет плюс, устойчив к топ-3, OOS-стабилен. Каветат: режим-
зависим (2025-26 силён, 2024 нет). Решающий тест — ЖИВОЕ исполнение VST (эдж умирает на филлах).

Триггер из шины (wt_snap 1h: wt1, atr_trend), SL из свежих 1h klines. Router source=rangefade.
Gated: trading.rangefade.enabled. Cap max_open. Дедуп/cooldown на пару.
"""
import asyncio
import logging
import time
import urllib.request
import json as _json

logger = logging.getLogger(__name__)
POLL_SEC = 120
_last_fire: dict = {}   # sym -> ts (cooldown)


def _cfg(bot):
    return bot.config.get("trading.rangefade", {}) or {}


def _kl_low(base, bars=4):
    """Свежие 1h klines BingX → минимум последних `bars` (для SL). Только на триггере (редко)."""
    try:
        u = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
             f"&interval=1h&limit=10")
        d = _json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "oko"}),
                                              timeout=8)).get("data", [])
        lows = [float(k["low"]) for k in d[:bars]]
        return min(lows) if lows else None
    except Exception:
        return None


async def rangefade_loop(bot):
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[RANGEFADE] disabled (trading.rangefade.enabled=false)")
        return
    wt_thr = float(cfg.get("wt_threshold", -60))
    tp_r = float(cfg.get("tp_r", 1.0))
    max_open = int(cfg.get("max_open", 8))
    wt_thr_4h = float(cfg.get("wt_threshold_4h", -70))
    cooldown = float(cfg.get("cooldown_h", 6)) * 3600
    # ДВА фейд-сиблинга (30.07): 1h (rangefade, чоп-режим) + 4h WT<-70 (rangefade4h, СИЛЬНЕЕ —
    # плюс в ОБА года, медиана +2%, WR61). source различает для табло.
    VARIANTS = [("1h", wt_thr, "rangefade", 4), ("4h", wt_thr_4h, "rangefade4h", 4)]
    logger.info("[RANGEFADE] loop start: 1h WT<%.0f (rangefade) + 4h WT<%.0f (rangefade4h) → LONG TP%.1fR · кап %d",
                wt_thr, wt_thr_4h, tp_r, max_open)
    import sqlite3
    from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    while True:
        try:
            await asyncio.sleep(POLL_SEC)
            pair_ctx = getattr(bot, "pair_context", None)
            if pair_ctx is None:
                continue
            db = bot.trade_simulator.db_path
            conn = sqlite3.connect(db, timeout=5)
            n_open = conn.execute("SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') "
                                  "AND signal_type IN ('rangefade','rangefade4h')").fetchone()[0]
            conn.close()
            if n_open >= max_open:
                continue
            now = time.time()
            for sym in pair_ctx.all_symbols():
                if n_open >= max_open:
                    break
                st = pair_ctx.get(sym)
                px = st.tick_price
                if not px:
                    continue
                for tf, thr, src, lookback in VARIANTS:
                    wt = (st.wt_snap or {}).get(tf) or {}
                    w1 = wt.get("wt1")
                    at = wt.get("atr_trend")
                    if w1 is None or at is None:
                        continue
                    if not (at > 0 and w1 < thr):          # аптренд ТФ + глубокий откат
                        continue
                    key = f"{sym}:{src}"
                    if now - _last_fire.get(key, 0) < cooldown:
                        continue
                    base = sym.split("/")[0]
                    lo = _kl_low(base, lookback)
                    if not lo or lo >= px:
                        continue
                    sl = lo * 0.997
                    tp = px + tp_r * (px - sl)
                    rec = TradingRecommendation(
                        symbol=sym, action="BUY", direction=SignalDirection.LONG,
                        overall_strength=65, confidence=0.6, risk_level="MEDIUM", signals_count=1,
                        supporting_signals=[], conflicting_signals=[],
                        market_context=MarketContext(symbol=sym, current_price=px, volume_24h=0.0,
                                                     volume_change_24h=0.0, price_change_24h=0.0),
                        entry_price=px, stop_loss=sl, take_profit=tp,
                        sl_source=f"{src}:{tf}low", tp_source=f"{src}:{tp_r}R")
                    res = await bot.trade_router.submit(rec, source=src, extra_features={
                        "signal_type_override": src, "trade_mode": src,
                        "rf_tf": tf, "rf_wt1": round(w1, 1), "rf_tp_r": tp_r})
                    if res.trade_id:
                        _last_fire[key] = now
                        n_open += 1
                        logger.info("[RANGEFADE] ✅ %s [%s] WT=%.0f → trade %s exch=%s",
                                    sym, src, w1, res.trade_id, res.exchange_order_id or "pending")
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[RANGEFADE] loop err: %s", e)
