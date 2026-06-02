"""AdvisorConnector — бот-сторона порта AdvisorPort (ARCH-125 §2, ADR-001).

Оборачивает любой `AdvisorPort` (рой/ML/внешний сервис) устойчивостью:
  - timeout (рой медленный ~60с) — НЕ блокирует event loop (asyncio.to_thread)
  - circuit breaker — после N сбоев порт временно отключается, бот живёт по базовой логике
  - shadow — вердикт пишется в advisor_snap, НОЛЬ влияния на исполнение
  - persist — последний брифинг в memory/advisor_brief.md + JSONL-лог для A/B

Зависит ТОЛЬКО от лёгкого `advisor_contract` (Protocol) — тяжёлый рой не тянется.
Инстанс порта инжектится снаружи (DI), см. bot/loops/advisor_loop.spawn_advisor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.intelligence.advisor_contract import AdvisoryRequest, AdvisoryVerdict, AdvisorPort

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_BRIEF = PROJECT_ROOT / "memory" / "advisor_brief.md"
_DEFAULT_LOG = PROJECT_ROOT / "memory" / "advisor_brief_log.jsonl"


class _CircuitBreaker:
    """Простой breaker: open после N подряд сбоев, half-open после cooldown."""

    def __init__(self, max_fails: int = 3, cooldown_s: float = 1800.0):
        self._max_fails = max_fails
        self._cooldown_s = cooldown_s
        self._fails = 0
        self._opened_at: Optional[float] = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self._cooldown_s:
            self._opened_at = None          # half-open: дать одну попытку
            self._fails = 0
            return True
        return False

    def record_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self._max_fails and self._opened_at is None:
            self._opened_at = time.monotonic()
            logger.warning("[advisor] circuit breaker OPEN (%d сбоев) на %.0f мин",
                           self._fails, self._cooldown_s / 60)


class AdvisorConnector:
    """Устойчивый вызов внешнего советника. shadow=True → только наблюдение."""

    def __init__(
        self,
        port: AdvisorPort,
        *,
        timeout_s: float = 180.0,   # каскад DS→mistral-fallback на живых данных ~115с (DS 402-retry + 7 моделей + синтез)
        breaker_fails: int = 3,
        breaker_cooldown_s: float = 1800.0,
        shadow: bool = True,
        brief_path: Path = _DEFAULT_BRIEF,
        log_path: Path = _DEFAULT_LOG,
    ):
        self._port = port
        self._timeout_s = timeout_s
        self._breaker = _CircuitBreaker(breaker_fails, breaker_cooldown_s)
        self.shadow = shadow
        self._brief_path = brief_path
        self._log_path = log_path

    @property
    def healthy(self) -> bool:
        try:
            return self._breaker.allow() and bool(self._port.health())
        except Exception:
            return False

    async def consult(self, req: AdvisoryRequest) -> Optional[AdvisoryVerdict]:
        """Спросить советника. None при breaker-open / timeout / ошибке / health=False.
        Никогда не бросает — деградирует к None (бот работает по базовой логике)."""
        if not self._breaker.allow():
            logger.info("[advisor] breaker open → skip consult")
            return None
        try:
            if not self._port.health():
                logger.info("[advisor] port health=False → skip")
                return None
        except Exception as e:
            logger.warning("[advisor] health() упал: %s", e)
            self._breaker.record_failure()
            return None

        t0 = time.monotonic()
        try:
            # port.consult синхронный и медленный → в поток, чтобы не блокировать loop
            verdict = await asyncio.wait_for(
                asyncio.to_thread(self._port.consult, req), timeout=self._timeout_s
            )
        except asyncio.TimeoutError:
            logger.warning("[advisor] timeout %.0fс", self._timeout_s)
            self._breaker.record_failure()
            return None
        except Exception as e:
            logger.warning("[advisor] consult упал: %s", e)
            self._breaker.record_failure()
            return None

        self._breaker.record_success()
        if verdict is None:
            logger.info("[advisor] вердикт None (советник не уверен)")
            return None

        elapsed = int((time.monotonic() - t0) * 1000)
        logger.info("[advisor] вердикт: %s (conf=%.2f, %dms)%s",
                    verdict.label, verdict.confidence, elapsed,
                    " [SHADOW]" if self.shadow else "")
        try:
            self._persist(req, verdict, elapsed)
        except Exception as e:
            logger.warning("[advisor] persist упал: %s", e)
        return verdict

    def _persist(self, req: AdvisoryRequest, verdict: AdvisoryVerdict, elapsed_ms: int) -> None:
        """Последний брифинг → md (читаемо) + JSONL-лог (для A/B). DB не трогаем (shadow)."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self._brief_path.parent.mkdir(parents=True, exist_ok=True)
        factors = "\n".join(f"- {f}" for f in (verdict.key_factors or []))
        md = (
            f"# Advisor Brief (shadow)\n\n"
            f"> {ts} • intent=`{req.intent}` • advisor=`{verdict.advisor_id}` • "
            f"conf={verdict.confidence:.2f} • {elapsed_ms}ms\n\n"
            f"## Вердикт: {verdict.label}\n\n{verdict.rationale}\n\n"
            f"## Ключевые факторы\n{factors or '—'}\n"
        )
        self._brief_path.write_text(md, encoding="utf-8")

        entry = {
            "ts": ts,
            "intent": req.intent,
            "label": verdict.label,
            "confidence": verdict.confidence,
            "rationale": verdict.rationale,
            "key_factors": verdict.key_factors,
            "advisor_id": verdict.advisor_id,
            "latency_ms": elapsed_ms,
            "snapshot": req.snapshot,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
