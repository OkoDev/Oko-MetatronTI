"""
cube_inbox.py — ВХОДЯЩИЙ МОСТ: факты внешних сфер из хаба Куба → бот (ADR-003, шаг 3–4).

Спутник публикует ФАКТ «увидел сетап» (`core/context/cube_client.publish`), а регистрирует и
исполняет сделку только бот — по своим `signal_router.source_policies`. Торговых команд в шине нет.

Защита (ADR-003, правило 4 и 5):
  • **белый список источников**: кто имеет право превратиться в сделку. Чего нет в списке — только лог;
  • источник без своей политики получает `default_policy.exchange_enabled: false` → SIM;
  • дедуп по (источник, пара, сторона) на `dedup_min`;
  • факты переигрываются по `id` после простоя — ничего не теряется молча;
  • мост публикует принятый факт и в локальную шину как `SIGNAL_DETECTED`, чтобы сферы бота увидели
    внешний сигнал тем же `subscribe_async`, без собственного кода.

Белый список живёт в `config.yaml` → `cube_hub.inbox.allow` (по умолчанию пусто = мост не торгует).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CubeInbox:
    def __init__(self, bot, allow: list[str], poll_sec: float = 5.0, dedup_min: float = 60.0):
        self.bot = bot
        self.allow = set(allow or [])
        self.poll = poll_sec
        self.dedup_min = dedup_min
        self._last_id = 0
        self._seen: dict[tuple, float] = {}
        self.accepted = self.rejected = self.registered = 0

    # ── приём одного факта ──
    async def handle(self, f: dict) -> bool:
        """True — факт превращён в сделку. Исключения не выпускают: мост не роняет бота."""
        data = f.get("data") or {}
        src = str(data.get("signal_type") or "").strip()
        sym = f.get("symbol") or ""
        side = str(data.get("direction") or "").upper()
        if src not in self.allow:
            self.rejected += 1
            logger.info("[CUBE-INBOX] %s %s от %s — вне белого списка, только лог",
                        src or "?", sym, f.get("producer"))
            return False
        key = (src, sym, side)
        now = time.monotonic()
        if now - self._seen.get(key, 0.0) < self.dedup_min * 60:
            logger.debug("[CUBE-INBOX] %s %s дубль в пределах %.0f мин", src, sym, self.dedup_min)
            return False
        self._seen[key] = now
        self.accepted += 1

        # сферы бота должны увидеть внешний сигнал тем же событием, что и свой
        try:
            from core.context.pair_context import SphereEvent
            self.bot.pair_context.publish(sym, SphereEvent.SIGNAL_DETECTED, {
                "signal_type": src, "direction": side, "strength": data.get("strength"),
                "tf": data.get("tf"), "price": data.get("price"), "atr_pct": data.get("atr_pct"),
                "external": f.get("producer"),
            })
        except Exception as e:                           # noqa: BLE001
            logger.debug("[CUBE-INBOX] публикация в локальную шину: %s", e)

        return await self._register(f, data, src, sym, side)

    async def _register(self, f: dict, data: dict, src: str, sym: str, side: str) -> bool:
        entry, sl, tp = data.get("entry") or data.get("price"), data.get("sl"), data.get("tp")
        if not (entry and sl and tp):
            logger.warning("[CUBE-INBOX] %s %s без геометрии (entry/sl/tp) — не регистрируем", src, sym)
            return False
        router = getattr(self.bot, "trade_router", None)
        if router is None:
            logger.warning("[CUBE-INBOX] роутер недоступен — %s %s пропущен", src, sym)
            return False
        from types import SimpleNamespace
        rec = SimpleNamespace(
            symbol=sym, direction=SimpleNamespace(value=side), entry_price=float(entry),
            stop_loss=float(sl), take_profit=float(tp), signal_type=src,
            overall_strength=int(data.get("strength") or 50), confidence=0.6,
            timeframe=data.get("tf") or "4h", metadata=dict(data),
            sl_source=data.get("sl_source") or f"{src}:external",
            tp_source=data.get("tp_source") or f"{src}:external")
        extra = {"trade_mode": src, "signal_type_override": src,
                 "external_producer": f.get("producer"), "cube_fact_id": f.get("id")}
        extra.update({k: v for k, v in data.items() if k.startswith("brk_")})
        try:
            res = await router.submit(rec, source=src, extra_features=extra)
        except Exception as e:                           # noqa: BLE001
            logger.warning("[CUBE-INBOX] submit %s %s: %s", src, sym, e)
            return False
        tid = getattr(res, "trade_id", None)
        if tid:
            self.registered += 1
            logger.info("[CUBE-INBOX] ✅ %s %s %s от %s → сделка #%s", src, sym, side,
                        f.get("producer"), tid)
            return True
        drops = ",".join(g for g, _ in (getattr(res, "hard_drops", None) or [])) or "—"
        logger.info("[CUBE-INBOX] %s %s отбит гейтами: %s", src, sym, drops)
        return False

    # ── цикл ──
    async def run(self) -> None:
        from core.context import cube_client as cc
        if not self.allow:
            logger.info("[CUBE-INBOX] белый список пуст — мост только слушает (не торгует)")
        logger.info("[CUBE-INBOX] старт · белый список: %s · опрос %.0f с",
                    ", ".join(sorted(self.allow)) or "—", self.poll)
        # с текущего момента: старые факты не переигрываем при первом запуске
        for f in await asyncio.to_thread(cc.facts, 0, ["signal_detected"], 1, 1):
            self._last_id = f["id"]
        while True:
            await asyncio.sleep(self.poll)
            try:
                rows = await asyncio.to_thread(cc.facts, self._last_id, ["signal_detected"], 200)
                for f in rows:
                    self._last_id = max(self._last_id, int(f.get("id") or 0))
                    if (f.get("producer") or "") == "oko-bot":
                        continue                         # свои факты обратно не принимаем
                    await self.handle(f)
            except Exception as e:                       # noqa: BLE001 — мост не роняет бота
                logger.warning("[CUBE-INBOX] ошибка приёма: %s", e)
