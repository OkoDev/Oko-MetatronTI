---
name: swarm_status_26sep_quota
description: "Живой пинг роя 26.09 — живы 5/12 голосов, 4 из них на ОДНОЙ квоте OpenRouter 50 запросов/сутки; советник жжёт её впустую с 04.09"
metadata:
  node_type: memory
  type: project
  originSessionId: 4e0fd74a-908f-4216-ac39-c0989b43af55
  modified: 2026-09-26T20:09:08.324Z
---

# Рой 26.09.2026: живы 5 из 12, узкое место — квота OpenRouter

Проверено живым пингом (скрипт в scratchpad сессии, крошечный промпт на каждый голос).

**Живы:** `groq` (gpt-oss-120b) · `openrouter` · `or_cohere` · `or_poolside` · `or_dots`.
Четыре из пяти на ОДНОМ ключе OpenRouter: free tier, `free_model_daily_requests` **50/сутки**,
сброс 00:00 UTC. Groq по заголовкам: 1000 запросов/сутки, **8000 токенов/мин**.

**Мертвы (причина — ответ API):** gemini 400 «User location is not supported» (гео РФ) ·
mistral 429 при `x-ratelimit-limit-req-minute: 0` · sambanova 402 PAYMENT_METHOD_REQUIRED ·
deepseek 402, баланс 0 USD / −0.43 CNY · groq_qwen и groq_compound 404 (модели убраны из каталога Groq) ·
ag_gemini_pro 403 upstream Antigravity, ag_gemini_agent cooldown · cerebras 402 · github_models отдаёт «OK» вместо ответа.

**Кто ест квоту:** советник `bot/loops/advisor_loop.py` (в oko-bot, `advisor.interval_hours: 4`) —
6 прогонов/сутки × 4 голоса OpenRouter = 24 из 50. С 04.09 каждый прогон = `swarm_raw` conf 0.3
(DS и mistral мертвы), голоса в `memory/advisor_brief_log.jsonl` не пишутся → чистая трата.
Один ручной `team_ask` = 4 голоса + 4 судьи ранга + мета (mistral мёртв → openrouter) ≈ 9 запросов OR.

**Спящая мина:** news-sphere компас зовёт рой (openrouter/groq/gemini/mistral) раз в час при
уверенности локалки <50. Сейчас НЕ доходит: в Ollama нет ни одной модели (blobs 0 ГБ, 404 с 21.09).
Если вернуть модель — добавит до 24 запросов OR/сутки, и вместе с советником квота кончится.

**Поиск замен 26.09 (боевой промпт: сумма 1.2 · PF 1.2 · медиана −1, проверено глазами):**
- ✅ `inclusionai/ling-3.0-flash-fin:free` (OpenRouter) — 3/3, лучшие гипотезы; новое семейство, но на той же квоте 50/сут.
- `groq_qwen` починен: `qwen3.6` снят → `qwen/qwen3.8-27b` (2/3). `groq/compound` из Groq исчез совсем.
- Mistral: ключ жив, `limit-req-minute: 0` только у medium/small/magistral; живы codestral (125 RPM, 2/3), mistral-code, ministral-8b/14b (1/3).
- Мертво окончательно: `oc/*` («free tier only from within OpenCode»), `aug/*` (нужен CLI `auggie`), `tllm/*` (Vercel банит наш IP), `ddgw/*` (418 антиабуз), inkling:free (только агентные харнессы), OVH анонимно (2 запроса/мин на IP).
- LLM7 без ключа — только default=codestral; 63 модели с «фронтирными» именами — за бесплатным ключом, оператор и политика данных неизвестны.
- Три прокси бота из PROXY_LIST не отвечают вообще (таймаут) → Gemini через них не поднять.
- 🔑 VPN ЕСТЬ: Happ (xray, TUN `happ-xray`, весь трафик в туннель, sys-proxy 127.0.0.1:10809), выход
  45.144.154.118 VDSka. RIPE и geofeed = NL, но **Google видит RU** (YouTube `"GL":"RU"`) → Gemini 400.
  Проверка страны глазами Google: GET youtube.com → regex `"GL":"(..)"`. Лечится сменой сервера в Happ.
  Прокси бота мертвы и через VPN (гипотеза: привязаны к домашнему IP; в логах 40–65k карантинов/сутки).
- ✅ РАЗГАДКА (вечер 26.09): в `.env PROXY_LIST` стояли СТАРЫЕ IP (192.147.x), а оплачены сингапурские
  64.139.1.246 / .1.228 / .0.86 (до 02.12.2026) — те же логин/пароль/порт 59100. Заменены, бэкап в scratchpad.
  Через SG Google видит SG: gemini 200, BingX 200. Латвия в Happ — тот же VDSka → Google опять RU.
- ✅ `LLM_PROXY` в .env → `llm_ask.ask_gemini` (client_args proxy) и `ensure_gateway` (HTTPS_PROXY шлюзу).
  Ожили gemini, ag_gemini_pro, ag_gemini_agent, ag_opus — все 3/3 на боевом промпте; ag_opus возвращён в состав.
  Рой: живы 10/13 (мертвы mistral, sambanova, groq_compound). Бот увидит новые прокси и LLM_PROXY только после рестарта.
- Из РФ достучались (401 без ключа): Z.ai/BigModel (GLM), SiliconFlow, DashScope intl, Moonshot, Together, DeepInfra, Nebius, Chutes, HF. Cohere — 403 (гео). GigaChat доступен, нужен корневой сертификат Минцифры.
- OpenRouter (оф. доки): 20 RPM; 50/сут при покупках <10 кредитов, 1000/сут при ≥10 за всё время.
- Гипотеза «шлюз OmniRoute ест квоту OR» проверена и ОПРОВЕРГНУТА (Δ0). Кто съел ещё +4 после пинга 26.09 — не найдено.

**Why:** старая норма «5/7 живых» ([[feedback_dense_ds_swarm_work]]) устарела: состав вырос до 12, а живых осталось 5, и они фактически один провайдер.
**How to apply:** перед запуском роя смотреть остаток OR (`GET openrouter.ai/api/v1/key` → `free_model_daily_requests`);
при нехватке — `team_ask --skip-rank`. Выводы роя сейчас = мнение по сути ДВУХ провайдеров, не 12.
