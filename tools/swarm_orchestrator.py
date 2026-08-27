# -*- coding: utf-8 -*-
"""ARCH-126 / ADR-002 — DS-оркестратор роя за AdvisorPort (Phase 1).

DeepSeek-v4 (1M ctx) = дирижёр: режет контекст осмысленно под каждую модель,
рассылает, синтезирует на ПОЛНОМ контексте. Снаружи — контракт AdvisorPort
(consult/health). Внутри DS дирижирует 7 моделями роя.

Поток consult() (Phase 1, один раунд):
  AdvisoryRequest → DS-план (выжимка+подвопрос на модель) → рассылка → DS-синтез → AdvisoryVerdict

Fallback: нет deepseek (баланс/ключ) → обычный team_ask (mistral-meta).
NB: данные-слепоту (DEV-240) НЕ лечит — эмпирику клиент валидирует данными.

Контракт-классы локальны (мигрируют в metatron-core, ARCH-125 playbook B).

Запуск: python tools/swarm_orchestrator.py "вопрос"   (CLI-обёртка над consult)
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_ROOT))
import llm_ask  # noqa: E402
import team_ask  # noqa: E402
# Контракт — из вынесенного advisor_contract (зерно metatron-core, общий с портом)
from core.intelligence.advisor_contract import (  # noqa: E402
    AdvisoryRequest, AdvisoryVerdict, SCHEMA_VERSION,
)

DS_PROVIDER = "deepseek"
MIN_MODELS = 3                 # ниже — нет смысла в рое
DS_PLAN_TOKENS = 4000
DS_SYNTH_TOKENS = 4000


def _ds_call(prompt: str, max_tokens: int) -> Optional[str]:
    """Вызов DeepSeek-дирижёра. None если недоступен (баланс/ключ/ошибка)."""
    if not llm_ask.has_key(DS_PROVIDER):
        return None
    try:
        return llm_ask.ask_openai_compat(
            DS_PROVIDER, prompt, llm_ask.DEFAULT_MODELS[DS_PROVIDER], max_tokens
        )
    except Exception as e:
        print(f"[swarm-ds] DS недоступен: {e}", file=sys.stderr)
        return None


class SwarmOrchestrator:
    """AdvisorPort-адаптер: DS дирижирует роем."""

    def __init__(self, providers: Optional[list] = None):
        llm_ask.load_env()   # ключи из .env (иначе has_key=False при прямом запуске)
        all_p = [p for p in team_ask.ALL_PROVIDERS if llm_ask.has_key(p)]
        # дирижёр (deepseek) исключается из опрашиваемых — он голова, не голос
        self.providers = [p for p in (providers or all_p) if p != DS_PROVIDER]

    def health(self) -> bool:
        return llm_ask.has_key(DS_PROVIDER) and len(self.providers) >= MIN_MODELS

    # ── Phase 1: план дирижёра — выжимка + подвопрос на каждую модель ──
    def _plan(self, req: AdvisoryRequest, context: str) -> Optional[dict]:
        prompt = (
            # prompt-cache DeepSeek (×50-120): СТАТИКА (инструкция+формат+context) ПЕРВОЙ
            # и идентичной → кэшируется префикс; ПЕРЕМЕННОЕ (вопрос) — в самом КОНЦЕ.
            "Ты — ДИРИЖЁР роя LLM. У тебя ПОЛНЫЙ контекст проекта. Задача: подготовить "
            f"опрос для моделей {self.providers}. Для каждой верни JSON:\n"
            '{"model": {"excerpt": "релевантная выжимка контекста ПОД вопрос (не весь, '
            'только нужное)", "subquestion": "конкретный подвопрос модели"}}\n'
            "Верни ТОЛЬКО JSON, ключи = имена моделей.\n\n"
            f"ПОЛНЫЙ КОНТЕКСТ:\n{context}\n\n"
            f"ВОПРОС (в конце — не ломает кэш-префикс): {req.question}"
        )
        raw = _ds_call(prompt, DS_PLAN_TOKENS)
        if not raw:
            return None
        try:
            s = raw[raw.find("{"): raw.rfind("}") + 1]
            return json.loads(s)
        except Exception:
            return None

    # ── Phase 1: синтез дирижёра на ПОЛНОМ контексте ──
    def _synthesize(self, req: AdvisoryRequest, answers: dict, context: str) -> Optional[AdvisoryVerdict]:
        votes = "\n\n".join(f"### {m}\n{a}" for m, a in answers.items())
        # market_brief: label из enum + разбор исходов (C свёрнут в B). Иначе — свободный вердикт.
        if req.intent == "market_brief":
            label_rule = ('"label" ∈ {RISK_ON, RISK_OFF, CAUTION, HOLD} (поза рынка/риск)')
            task_extra = (
                "Контекст = snapshot рынка/портфеля (btc_mode, portfolio agg, recent_closed[20]).\n"
                "4. РАЗБОР ИСХОДОВ (recent_closed): какие signal_type/regime/direction работали "
                "(по R_multiple/status), какие нет → 1-2 темы в key_factors.\n"
                "5. Поза рынка и уровень риска с учётом btc_mode + portfolio avg_r.\n"
            )
        else:
            label_rule = '"label" = краткий вердикт'
            task_extra = ""
        prompt = (
            "Ты — ДИРИЖЁР роя. У тебя ПОЛНЫЙ контекст + ответы моделей. Синтезируй:\n"
            "1. Где консенсус, где спор. 2. Скорректируй галлюцинации (ты видишь реальный "
            "контекст, модели — нет). 3. Итоговый вердикт.\n" + task_extra +
            f"Верни JSON: {{{label_rule}, \"confidence\": 0.0-1.0, "
            "\"rationale\": \"1-3 предложения\", \"key_factors\": [\"...\"]}\n\n"
            # prompt-cache: статичный КОНТЕКСТ перед переменными votes/вопросом
            f"КОНТЕКСТ:\n{context}\n\nОТВЕТЫ МОДЕЛЕЙ:\n{votes}\n\nВОПРОС: {req.question}"
        )
        raw = _ds_call(prompt, DS_SYNTH_TOKENS)
        advisor_id = "swarm-ds@v1"
        if not raw:
            # DS недоступен (баланс 0 / ключ / ошибка) → деградация в mistral-meta синтез.
            # balance=0 НЕ ломает: рой опрошен → mistral синтезирует → обычный рой, не None.
            raw = self._fallback_synth(votes, req)
            advisor_id = "swarm-mistral-fallback@v1"
        if not raw:
            # и mistral недоступен → сырая агрегация голосов (лучше чем None для клиента)
            return AdvisoryVerdict(
                label="swarm_raw", confidence=0.3,
                rationale="DS+mistral недоступны — сырые голоса роя в meta.votes",
                advisor_id="swarm-raw@v1", meta={"votes": answers, "intent": req.intent},
            )
        try:
            s = raw[raw.find("{"): raw.rfind("}") + 1]
            d = json.loads(s)
            return AdvisoryVerdict(
                label=d.get("label", "?"), confidence=float(d.get("confidence", 0.5)),
                rationale=d.get("rationale", ""), key_factors=d.get("key_factors", []),
                advisor_id=advisor_id,
                meta={"votes": answers, "raw_synthesis": raw, "intent": req.intent},
            )
        except Exception:
            return AdvisoryVerdict(label="synthesis_parse_error", confidence=0.3,
                                   rationale=raw[:500], advisor_id=advisor_id,
                                   meta={"votes": answers})

    def _fallback_synth(self, votes: str, req: AdvisoryRequest) -> Optional[str]:
        """Деградация: синтез через mistral (llm_ask), когда DS-дирижёр недоступен."""
        if not llm_ask.has_key("mistral"):
            return None
        prompt = (
            "Синтезируй ответы роя LLM: консенсус, споры, итоговый вердикт. "
            'Верни JSON: {"label": "...", "confidence": 0.0-1.0, "rationale": "1-3 предл.", '
            '"key_factors": ["..."]}\n\n'
            f"ВОПРОС: {req.question}\n\nОТВЕТЫ:\n{votes}"
        )
        try:
            return llm_ask.ask_openai_compat("mistral", prompt, llm_ask.DEFAULT_MODELS["mistral"], 3000)
        except Exception:
            return None

    def consult(self, req: AdvisoryRequest) -> Optional[AdvisoryVerdict]:
        t0 = time.monotonic()
        if not self.health():
            print("[swarm-ds] health=False → fallback на обычный team_ask", file=sys.stderr)
            return None  # клиент падает на team_ask.main()
        # Контекст по intent: market_brief/trade_decision — из snapshot (рынок/портфель/пара);
        # free_question/audit — bundle проекта (brief+timeline+TASKS).
        if req.intent in ("market_brief", "trade_decision") and req.snapshot:
            context = json.dumps(req.snapshot, ensure_ascii=False, indent=2, default=str)
        else:
            context = team_ask.collect_context()
        plan = self._plan(req, context)
        # 18.08: шлюз OmniRoute снят с pm2 (держал 350 MB круглосуточно). Боевой луп
        # `bot/loops/advisor_loop.py` зовёт consult раз в час, и запасные входы при 429
        # (OMNIROUTE_SPARE) идут именно через него → поднимаем на время консультации.
        # ensure_gateway вернёт None, если шлюз уже поднят кем-то — чужой не гасим.
        gw = llm_ask.ensure_gateway()
        # рассылка: по плану DS (выжимка+подвопрос) или fallback на общий вопрос+trim
        def ask(p):
            if plan and p in plan:
                ctx = plan[p].get("excerpt", "")
                q = plan[p].get("subquestion", req.question)
            else:
                ctx = team_ask._trim_context(context, team_ask.CONTEXT_BUDGET_CHARS.get(p, team_ask.DEFAULT_CONTEXT_BUDGET))
                q = req.question
            return team_ask.get_answer(p, q, ctx)
        answers = {}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.providers)) as ex:
                # get_answer → (provider, model, text); берём text как ans (R1 fix)
                for prov, _model, ans in ex.map(ask, self.providers):
                    answers[prov] = ans
            verdict = self._synthesize(req, answers, context)
        finally:
            # бот живёт вечно — без явного гашения шлюз висел бы с первой консультации
            llm_ask.stop_gateway(gw)
        if verdict:
            verdict = AdvisoryVerdict(**{**verdict.__dict__, "latency_ms": int((time.monotonic() - t0) * 1000)})
        return verdict


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/swarm_orchestrator.py \"вопрос\"")
        return 1
    question = sys.argv[1]
    orch = SwarmOrchestrator()
    if not orch.health():
        print(f"[swarm-ds] недоступен (deepseek баланс/ключ? моделей={len(orch.providers)}). "
              f"Используй обычный team_ask.")
        return 2
    req = AdvisoryRequest(snapshot={}, question=question, intent="free_question")
    v = orch.consult(req)
    if not v:
        print("[swarm-ds] consult вернул None")
        return 3
    print(f"\n=== ВЕРДИКТ ДИРИЖЁРА (conf={v.confidence:.2f}, {v.latency_ms}ms) ===")
    print(f"{v.label}\n\n{v.rationale}")
    if v.key_factors:
        print("\nКлючевые факторы:")
        for f in v.key_factors:
            print(f"  • {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
