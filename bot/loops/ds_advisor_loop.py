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
    from core.context.context_factory import build_market_context
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
        # 29.09: контекст собирает ШИНА (было volume_24h=0.0 — оборот терялся)
        market_context=build_market_context(bot, sym, current_price=entry),
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
    # 🔭 Рыночный контекст как фичи (04.08) — см. core/context/market_regime.py
    try:
        from core.context.market_regime import context_features
        extra.update(context_features(str(sym).split("/")[0]))
    except Exception:
        pass
    res = await bot.trade_router.submit(rec, source="ds_advisor", extra_features=extra)
    if res.trade_id:
        logger.info("[DS-ADVISOR] ✅ #%s %s %s → trade %s exch=%s",
                    row["id"], sym, d, res.trade_id, res.exchange_order_id or "pending")
        # видимость Егору (25.07 «нужен чарт в сообщении и полноценные ссылки», как у radar):
        # чарт+текст одним фото-сообщением + ссылки TW/BINGX. Чарт в отдельном ПОТОКЕ (build_signal_chart
        # рендерит matplotlib — блокирующе; отдельный event loop в thread не стопорит луп бота).
        try:
            from oko_feed.alerts import send_tg, send_tg_photo
            base = sym.split("/")[0]
            _emoji = "🟢" if is_long else "🔴"
            _ex = "📡 ордер на VST" if res.exchange_order_id else "⏳ ордер отклонён sizing'ом"
            _links = (f'- <a href="https://ru.tradingview.com/chart/?symbol=BINGX%3A{base}USDT.P'
                      f'&interval=60">TW</a>\n- <a href="https://bingx.com/ru/perpetual/{base}-USDT">BINGX</a>')
            _msg = (f"🤖 <b>DC-АГЕНТ вошла:</b> {_emoji} <b>{d}</b> <code>{base}</code>\n"
                    f"вход <code>{entry:.6g}</code> · SL <code>{sl:.6g}</code> · TP <code>{tp:.6g}</code>\n"
                    f"💭 <i>{(row['thesis'] or '—')[:200]}</i>\n"
                    f"{_ex} · trade #{res.trade_id}\n\n{_links}\n\n#DC_AGENT #DS")

            def _chart_sync() -> bytes | None:
                import asyncio as _a
                from core.ui.chart_builder import build_signal_chart
                try:
                    return _a.run(build_signal_chart(f"{base}/USDT:USDT", tf="1h",
                                                     bot=None, wave_overlay=True))
                except Exception:
                    return None
            _png = await asyncio.to_thread(_chart_sync)
            if _png and len(_msg) <= 1024:
                await asyncio.to_thread(send_tg_photo, _png, _msg, "action")  # чарт+текст = одно сообщение
            else:
                _mid = await asyncio.to_thread(send_tg, _msg, "action")       # фолбэк: текст + чарт-reply
                if _png and _mid:
                    await asyncio.to_thread(send_tg_photo, _png,
                                            f"<code>{base}</code> 1h · SMC", "action", _mid)
        except Exception as _tge:
            logger.debug("[DS-ADVISOR] TG: %s", _tge)
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
    # 🔴 22.08 ДВА ЛИМИТА (DEV-239). Ожидающая лимитка НЕ в рынке: выиграть или проиграть
    # она не может, рыночного риска не несёт — расходует только маржу под резерв.
    # Считая её слотом риска, мы запрещали вход из-за расхода, которого нет (22.08 у
    # impulse_fib это дало 8 часов простоя при НОЛЕ позиций, [[cap_pending_not_risk_slot]]).
    # У ds_advisor вход тоже LIMIT → та же мина, просто ещё не выстрелила.
    max_pending = int(cfg.get("max_pending", max_open))
    logger.info("[DS-ADVISOR] loop start: DC торгует VST через router · кап %d позиций / "
                "%d заявок · судья forward machine · гейт 20-30 net+ → реальные деньги",
                max_open, max_pending)
    db = bot.trade_simulator.db_path
    while True:
        try:
            await asyncio.sleep(POLL_SEC)
            conn = sqlite3.connect(db, timeout=5)
            conn.row_factory = sqlite3.Row
            from core.trading.source_registry import slots as _slots
            _st = _slots(conn, "ds_advisor", max_open=max_open, max_pending=max_pending)
            # Бюджет ограничен ОБОИМИ лимитами: свободные слоты риска и свободный резерв маржи.
            budget = max(0, min(max_open - _st["open"], max_pending - _st["pending"]))
            if not budget and _st["why"]:
                logger.info("[DS-ADVISOR] новых сигналов не берём: %s", _st["why"])
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
