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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_ask  # noqa: E402
import team_ask  # noqa: E402

DS_PROVIDER = "deepseek"
MIN_MODELS = 3                 # ниже — нет смысла в рое
DS_PLAN_TOKENS = 4000
DS_SYNTH_TOKENS = 4000


# ─────────── Контракт AdvisorPort (ARCH-125 §2; локально до metatron-core) ───────────
# 🔒 FROZEN (02.06.2026): сигнатуры AdvisoryRequest/Verdict заморожены — их импортирует
# advisor_connector.py (порт в scan_loop, параллельная сессия). НЕ менять поля без
# согласования: смена ломает импорт на стороне бота. Эволюция — через schema_version + ADR.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AdvisoryRequest:
    snapshot: dict
    intent: str = "free_question"          # "trade_decision" | "audit" | "free_question"
    question: Optional[str] = None
    deadline_ms: int = 60000               # advisor-домен канон: LLM-рой медленный (НЕ 5000 как trade-decision)
    schema_version: int = SCHEMA_VERSION   # R4: выравнивание с ARCH-125 §2
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisoryVerdict:
    label: str
    confidence: float
    rationale: str
    key_factors: list = field(default_factory=list)
    advisor_id: str = "swarm-ds@v1"
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)   # по-модельные голоса, план DS


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
        all_p = [p for p in team_ask.ALL_PROVIDERS if llm_ask.has_key(p)]
        # дирижёр (deepseek) исключается из опрашиваемых — он голова, не голос
        self.providers = [p for p in (providers or all_p) if p != DS_PROVIDER]

    def health(self) -> bool:
        return llm_ask.has_key(DS_PROVIDER) and len(self.providers) >= MIN_MODELS

    # ── Phase 1: план дирижёра — выжимка + подвопрос на каждую модель ──
    def _plan(self, req: AdvisoryRequest, context: str) -> Optional[dict]:
        prompt = (
            "Ты — ДИРИЖЁР роя LLM. У тебя ПОЛНЫЙ контекст проекта. Задача: подготовить "
            f"опрос для моделей {self.providers}. Для каждой верни JSON:\n"
            '{"model": {"excerpt": "релевантная выжимка контекста ПОД этот вопрос (не весь, '
            'только нужное)", "subquestion": "конкретный подвопрос модели"}}\n\n'
            f"ВОПРОС: {req.question}\n\nПОЛНЫЙ КОНТЕКСТ:\n{context}\n\n"
            "Верни ТОЛЬКО JSON, ключи = имена моделей."
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
        prompt = (
            "Ты — ДИРИЖЁР роя. У тебя ПОЛНЫЙ контекст + ответы моделей. Синтезируй:\n"
            "1. Где консенсус, где спор. 2. Скорректируй галлюцинации (ты видишь реальный "
            "контекст, модели — нет). 3. Итоговый вердикт.\n"
            "Верни JSON: {\"label\": \"краткий вердикт\", \"confidence\": 0.0-1.0, "
            "\"rationale\": \"1-3 предложения\", \"key_factors\": [\"...\"]}\n\n"
            f"ВОПРОС: {req.question}\n\nОТВЕТЫ МОДЕЛЕЙ:\n{votes}\n\nКОНТЕКСТ:\n{context}"
        )
        raw = _ds_call(prompt, DS_SYNTH_TOKENS)
        if not raw:
            return None
        try:
            s = raw[raw.find("{"): raw.rfind("}") + 1]
            d = json.loads(s)
            return AdvisoryVerdict(
                label=d.get("label", "?"), confidence=float(d.get("confidence", 0.5)),
                rationale=d.get("rationale", ""), key_factors=d.get("key_factors", []),
                meta={"votes": answers, "raw_synthesis": raw},
            )
        except Exception:
            return AdvisoryVerdict(label="synthesis_parse_error", confidence=0.3,
                                   rationale=raw[:500], meta={"votes": answers})

    def consult(self, req: AdvisoryRequest) -> Optional[AdvisoryVerdict]:
        t0 = time.monotonic()
        if not self.health():
            print("[swarm-ds] health=False → fallback на обычный team_ask", file=sys.stderr)
            return None  # клиент падает на team_ask.main()
        context = team_ask.collect_context()
        plan = self._plan(req, context)
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.providers)) as ex:
            # get_answer → (provider, model, text); берём text как ans (R1 fix)
            for prov, _model, ans in ex.map(ask, self.providers):
                answers[prov] = ans
        verdict = self._synthesize(req, answers, context)
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
