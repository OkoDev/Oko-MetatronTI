# -*- coding: utf-8 -*-
"""DS-ADVISOR LOOP — торговый агент DC (deepseek-v4-pro) на VST (25.07, решение Егора).

Егор: «давай сразу на VST — это и есть песочница» + «пусть DS получает весь поток и принимает
торговые решения». Урок сессии: SIM врёт об исполнении — форвард DC меряется сразу реальными
филлами VST (деньги виртуальные). Решения DC НЕ фильтруются — только риск-капы.

Поток: DC пишет ds_signals (анализ: шина /api/cube/context + durable БД, полная свобода) →
этот луп строит rec → bot.trade_router.submit(source='ds_advisor') = ЕДИНЫЙ узел (гейты,
sizing, VST-ордер LIMIT, exchange_order_id, sync — как у pump). Судья: forward machine.
ГЕЙТ РЕАЛЬНЫХ ДЕНЕГ: 20-30 сделок net+ (демо VST — сразу, это песочница).

Капы: max_open (деф. 5) одновременных ds_advisor · sanity inverted-geometry (класс-4) ·
TTL сигнала (протухшие режектятся). Gated: trading.ds_advisor.enabled.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

POLL_SEC = 30


def _norm_symbol(s: str) -> str:
    s = s.strip().upper()
    if "/" in s:
        return s if ":" in s else s + ":USDT"
    return f"{s}/USDT:USDT"


def _cfg(bot) -> dict:
    return bot.config.get("trading.ds_advisor", {}) or {}


async def _process_one(bot, row: dict) -> tuple[int, str]:
    """→ (processed_flag, note). 1=зарегистрирован, -1=ошибка/режект."""
    from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    sym = _norm_symbol(row["symbol"])
    d = (row["direction"] or "").upper()
    entry, sl = float(row["entry_price"]), float(row["stop_loss"])
    if d not in ("LONG", "SHORT") or entry <= 0 or sl <= 0:
        return -1, f"bad signal dir={d} entry={entry} sl={sl}"
    if (d == "LONG" and sl >= entry) or (d == "SHORT" and sl <= entry):
        return -1, f"inverted geometry {d} entry={entry} sl={sl}"
    # TTL сигнала
    try:
        age_min = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(str(row["created_at"])).replace(tzinfo=timezone.utc)
                   ).total_seconds() / 60
        if age_min > float(row["ttl_min"] or 2880):
            return -1, f"signal expired ({age_min:.0f} min)"
    except Exception:
        pass
    is_long = d == "LONG"
    tp = float(row["take_profit"]) if row["take_profit"] else (
        entry + 2 * (entry - sl) if is_long else entry - 2 * (sl - entry))
    rec = TradingRecommendation(
        symbol=sym, action="BUY" if is_long else "SELL",
        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
        overall_strength=60, confidence=float(row["confidence"] or 0.6),
        risk_level="MEDIUM", signals_count=1,
        supporting_signals=[], conflicting_signals=[],
        market_context=MarketContext(symbol=sym, current_price=entry,
                                     volume_24h=0.0, volume_change_24h=0.0, price_change_24h=0.0),
        entry_price=entry, stop_loss=sl, take_profit=tp,
        sl_source="ds_advisor", tp_source="ds_advisor",
    )
    extra = {
        "signal_type_override": "ds_advisor",
        "trade_mode": "ds_advisor",
        "trigger_source": "ds_advisor",
        "ds_signal_id": row["id"],
        "ds_thesis": (row["thesis"] or "")[:300],
        "ds_confidence": row["confidence"],
    }
    res = await bot.trade_router.submit(rec, source="ds_advisor", extra_features=extra)
    if res.trade_id:
        logger.info("[DS-ADVISOR] ✅ #%s %s %s → trade %s exch=%s",
                    row["id"], sym, d, res.trade_id, res.exchange_order_id or "pending")
        return 1, str(res.trade_id)
    hd = ",".join(g for g, _ in res.hard_drops) or "router None"
    logger.info("[DS-ADVISOR] ⛔ #%s %s %s — %s", row["id"], sym, d, hd)
    return -1, f"gate: {hd}"


async def ds_advisor_loop(bot) -> None:
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[DS-ADVISOR] disabled (trading.ds_advisor.enabled=false) — loop не стартует")
        return
    max_open = int(cfg.get("max_open", 5))
    logger.info("[DS-ADVISOR] loop start: DC торгует VST через router · кап %d позиций · "
                "судья forward machine · гейт 20-30 net+ → реальные деньги", max_open)
    db = bot.trade_simulator.db_path
    while True:
        try:
            await asyncio.sleep(POLL_SEC)
            conn = sqlite3.connect(db, timeout=5)
            conn.row_factory = sqlite3.Row
            n_open = conn.execute(
                "SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') "
                "AND signal_type='ds_advisor'").fetchone()[0]
            budget = max(0, max_open - n_open)
            if budget == 0:
                conn.close()
                continue
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM ds_signals WHERE processed=0 ORDER BY id LIMIT ?",
                (budget,)).fetchall()]
            conn.close()
            for row in rows:
                try:
                    flag, note = await _process_one(bot, row)
                except Exception as e:  # noqa: BLE001
                    flag, note = -1, str(e)[:180]
                conn = sqlite3.connect(db, timeout=5)
                if flag == 1:
                    conn.execute("UPDATE ds_signals SET processed=1, trade_id=? WHERE id=?",
                                 (int(note), row["id"]))
                else:
                    conn.execute("UPDATE ds_signals SET processed=-1, error=? WHERE id=?",
                                 (note, row["id"]))
                conn.commit()
                conn.close()
        except asyncio.CancelledError:
            logger.info("[DS-ADVISOR] loop cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[DS-ADVISOR] loop err: %s", e)
