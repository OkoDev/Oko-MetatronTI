"""Advisor Loop — глобальный стратегический брифинг роя (ARCH-125 §B, высота B+C).

НЕ per-pair (это дублировало бы 11 детерминированных сфер + рой слеп к данным DEV-240).
Раз в цикл (часовой) ОДИН consult к рою-дирижёру на ПОЛНОМ контексте:
  B — поза рынка / риск / темы (market_brief)
  C — разбор свежих закрытых сделок (Сфера 11 feedback)
Результат → advisor_snap (shadow, memory/advisor_brief.md + JSONL). НОЛЬ влияния на исполнение.

Gated: config `advisor.enabled` (default false). Выключено → spawn_advisor() ничего не делает,
тяжёлый рой даже не импортируется. Включение → нужен DEEPSEEK_API_KEY (дирижёр).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Пауза после закрытия свечи: дать боту дофетчить свежий OHLCV к моменту брифинга.
_CANDLE_SETTLE_S = 30

_BRIEF_QUESTION = (
    "Дай стратегический брифинг по торговому боту на ПОЛНОМ контексте снимка: "
    "(1) поза рынка (risk_on/risk_off/neutral) с учётом BTC-режима; "
    "(2) главный риск прямо сейчас; "
    "(3) темы/паттерны в свежих закрытых сделках — что работает, что нет; "
    "label = краткая поза (RISK_ON/RISK_OFF/CAUTION/HOLD)."
)


def _build_snapshot(_bot) -> dict:
    """Глобальный снимок: рынок (B) + портфель + свежие исходы (C). Без новых DB-схем."""
    snap: dict = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    # B: BTC-режим (Сфера 5, Cross-Market)
    try:
        snap["btc_mode"] = _bot.btc_regime_provider.get_btc_mode()
    except Exception as e:
        snap["btc_mode"] = f"?({e})"

    # Агрегаты + свежие исходы (C) через PerformanceEngine
    try:
        from core.trading.performance_engine import PerformanceEngine
        db = _bot.trade_simulator.db_path
        pe = PerformanceEngine(db)
        s = pe.summary() or {}
        snap["portfolio"] = {
            "open": s.get("open_count"),
            "total": s.get("total"),
            "win_rate": s.get("win_rate"),
            "avg_r": round(s["avg_r"], 3) if s.get("avg_r") is not None else None,
            "avg_r_win": round(s["avg_r_win"], 3) if s.get("avg_r_win") is not None else None,
            "avg_r_loss": round(s["avg_r_loss"], 3) if s.get("avg_r_loss") is not None else None,
        }
        recent = pe.recent_closed(limit=20)
        # сжатые исходы для дирижёра (без features_json — он тяжёлый)
        def _slim(t: dict) -> dict:
            return {k: t.get(k) for k in
                    ("symbol", "direction", "signal_type", "regime", "R_multiple", "status")}
        snap["recent_closed"] = [_slim(t) for t in recent]
        # дешёвые срезы по свежим
        by_dir, by_regime = {}, {}
        for t in recent:
            by_dir[t.get("direction")] = by_dir.get(t.get("direction"), 0) + 1
            by_regime[t.get("regime")] = by_regime.get(t.get("regime"), 0) + 1
        snap["recent_by_direction"] = by_dir
        snap["recent_by_regime"] = by_regime
    except Exception as e:
        snap["portfolio_error"] = str(e)

    return snap


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _send_tg(_bot, verdict) -> None:
    """Отправить брифинг админу в ТГ с #тегом (gated config advisor.send_telegram)."""
    cfg = _bot.config
    if not cfg.get("advisor.send_telegram", False):
        return
    admin_id = cfg.get("telegram.admin_id")
    tg = getattr(_bot, "bot", None) or getattr(_bot, "bot_instance", None)
    if not admin_id or tg is None:
        logger.warning("[advisor_loop] TG: нет admin_id/bot-инстанса — пропуск")
        return
    base = cfg.get("advisor.telegram_tag", "#брифинг")
    ih = float(cfg.get("advisor.interval_hours", 1))
    period = f"{int(ih)}ч" if ih == int(ih) else f"{ih}ч"
    tag = f"{base}_{period}"     # напр. #брифинг_1ч (период из interval_hours)
    factors = "\n".join(f"• {_esc(f)}" for f in (verdict.key_factors or [])[:6])
    text = (
        f"{_esc(tag)} <b>Стратегический брифинг роя</b>\n\n"
        f"<b>Вердикт:</b> {_esc(verdict.label)}  (conf {verdict.confidence:.2f})\n\n"
        f"{_esc(verdict.rationale)}\n"
        + (f"\n<b>Факторы:</b>\n{factors}\n" if factors else "")
        + f"\n<i>{_esc(verdict.advisor_id)} • {verdict.latency_ms}ms • shadow</i>"
    )
    try:
        await tg.send_message(int(admin_id), text[:4000], parse_mode="HTML",
                              disable_web_page_preview=True)
        logger.info("[advisor_loop] брифинг отправлен в ТГ admin=%s", admin_id)
    except Exception as e:
        logger.warning("[advisor_loop] TG send упал: %s", e)


async def advisor_loop(_bot) -> None:
    """Периодический брифинг. Первый запуск — через interval (не на старте)."""
    cfg = _bot.config
    interval_h = float(cfg.get("advisor.interval_hours", 1))
    period = max(300, int(interval_h * 3600))   # период в секундах
    connector = getattr(_bot, "advisor", None)
    if connector is None:
        logger.warning("[advisor_loop] connector не инжектирован — выход")
        return

    # импорт контракта здесь (лёгкий), чтобы модуль грузился даже когда фича off
    from core.intelligence.advisor_contract import AdvisoryRequest

    logger.info("[advisor_loop] запланирован ПО ЗАКРЫТИЮ СВЕЧИ (граница %.1fч +%dс settle, shadow=%s)",
                interval_h, _CANDLE_SETTLE_S, connector.shadow)
    cycle = 0
    while True:
        # выравнивание по закрытию свечи: граница периода (08:00/09:00 для 1ч) + settle.
        # offset МСК=UTC+3 кратен часу → граница UTC-часа == граница локального часа.
        sleep_s = period - (int(time.time()) % period) + _CANDLE_SETTLE_S
        await asyncio.sleep(sleep_s)
        cycle += 1
        try:
            snapshot = _build_snapshot(_bot)
            req = AdvisoryRequest(
                snapshot=snapshot,
                intent="market_brief",
                question=_BRIEF_QUESTION,
                meta={"cycle_id": cycle},
            )
            verdict = await connector.consult(req)
            if verdict:
                logger.info("[advisor_loop] брифинг #%d: %s (conf=%.2f)",
                            cycle, verdict.label, verdict.confidence)
                await _send_tg(_bot, verdict)
            else:
                logger.info("[advisor_loop] брифинг #%d: вердикта нет (skip/breaker/None)", cycle)
        except Exception as e:
            logger.warning("[advisor_loop] cycle #%d error: %s", cycle, e)


def spawn_advisor(_bot) -> bool:
    """Точка подключения из bot.py (1 вызов). Gated config `advisor.enabled`.
    Выключено → возвращает False, ничего не импортирует/не запускает. Никогда не бросает."""
    try:
        if not _bot.config.get("advisor.enabled", False):
            logger.info("[advisor] выключен (config advisor.enabled=false) — пропуск")
            return False

        # тяжёлый рой импортируется ТОЛЬКО при включённой фиче
        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from swarm_orchestrator import SwarmOrchestrator   # AdvisorPort-адаптер (DS-дирижёр)
        from core.intelligence.advisor_connector import AdvisorConnector

        port = SwarmOrchestrator()
        _bot.advisor = AdvisorConnector(
            port,
            timeout_s=float(_bot.config.get("advisor.timeout_s", 90)),
            breaker_fails=int(_bot.config.get("advisor.breaker_fails", 3)),
            breaker_cooldown_s=float(_bot.config.get("advisor.breaker_cooldown_s", 1800)),
            shadow=bool(_bot.config.get("advisor.shadow", True)),
        )
        asyncio.create_task(advisor_loop(_bot))
        logger.info("[advisor] loop spawned (shadow=%s, healthy=%s)",
                    _bot.advisor.shadow, _bot.advisor.healthy)
        return True
    except Exception as e:
        logger.warning("[advisor] не запущен: %s", e)
        return False
