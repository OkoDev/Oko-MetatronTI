---
name: condor_integration_strategy
description: Стратегия Oko-мозг поверх Condor-тела (Hummingbot). Карта маппинга, что Condor уже решил, риски. Для сессии «стратегия продукта»
metadata:
  node_type: memory
  type: reference
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**Condor (condor.hummingbot.org, Hummingbot Foundation, 2025)** = open-source harness для флота AI-торговых агентов. Зеркало архитектуры Oko, но пустой harness без TA. Юзер 09.06 выбрал стратегию **2+3 (не исключают)**: Oko-МОЗГ поверх Condor-ТЕЛА.

**🧩 КАРТА МАППИНГА Oko→Condor (проверено по docs 09.06):**
| Oko | Condor |
|---|---|
| `scan_loop` 60с | **routine `CONTINUOUS=True`** (asyncio loop, детерминированный Python) |
| детекторы SMC/OTE/волны | **routine** — `async run(config, context)`, БЕЗ LLM-токенов, свои TA-детекторы ✅ |
| `register_trade` entry/SL/TP | **position-executor** `TripleBarrierConfig`(stop_loss/take_profit/time_limit/trailing_stop) |
| TSL ATR-Trend | `trailing_stop`(activation_price+trailing_delta %) — НО Oko умнее (структурный, не фикс%) |
| single TP (DEV-124) | position-executor тоже single TP (partial НЕ поддержан) — СОВПАЛИ! |
| статусы TP/SL/TSL/EXPIRED | exit reasons TAKE_PROFIT/STOP_LOSS/TRAILING_STOP/TIME_LIMIT/EARLY_STOP — 1:1 |
| per-strategy P&L | **controller_id** (изоляция на shared account) |
| ARCH-96 мультиаккаунт | controller_id «50 агентов на 1 API key» — Condor УЖЕ решил |
| BingX(1) | **50+ CEX connectors** + DEX Gateway |
| dashboard+Telegram | встроены |
| backtest | `bots/backtesting` встроен |

**💥 Condor УЖЕ решил боли Oko:** мультиаккаунт/изоляция P&L (controller_id), positionId/execution (battle-tested API, 3619 ошибок не было бы), 50 бирж, Telegram+dashboard, backtest. **Two-server**: LLM-reasoning (Condor Server) ⊥ execution+data (Hummingbot API) — торговля не встаёт пока LLM думает.

**🧬 Что Oko уникально приносит (у Condor НЕТ):** SMC/Elliott/OTE/Куб TA-мозг, 63 confirmation-источника, ATR-Trend TSL (умнее фикс-%), единый калькулятор parity. Condor = harness, Oko = мозг.

**🎯 ПЛАН 2+3:** Oko-логика → Condor `routine` (SMC-детекторы) + кастомный TSL-контроллер; Condor `executors`+connectors+API = тело. Результат: убрать возню с BingX/positionId/мультиаккаунт → фокус на edge.

**🌌 ЗАМКНУТ КРУГ (юзер 09.06): ARCH-96-HUB = Condor «Trade anywhere».** Юзер независимо вывел [[principle_reuse_not_duplication|exchange=параметр]] hub (exchange→account→symbol→position, ExchangeAdapter) — и УЗНАЛ в нём Condor (50+ CEX connectors + DEX Gateway + multi-leg). Пришёл к Condor ДВАЖДЫ: я показал → он сам вывел из принципа. **Стратегическое обоснование 2+3:** строить ARCH-96-HUB с нуля = месяцы (BingX/Binance/Bybit Adapter'ы + DEX + multi-leg); ВЗЯТЬ Condor-тело = hub готов из коробки (50 бирж battle-tested). Твоя «сингулярность исполнения» ([[vision_cube_tesseract_singularity]]) уже материализована Hummingbot → Oko-мозг встаёт сверху. ARCH-96-HUB = фактически ТЗ на то, что Condor поставляет. **Не строить — оседлать.**

**🧊 CONDOR = EXECUTION SUB-КУБ (видение юзера 09.06).** Не «переписать Oko под Condor», а ВСТРОИТЬ Condor как СФЕРУ ИСПОЛНЕНИЯ внутри Куба Метатрона. Соединяет 3 готовых паттерна юзера: **ARCH-96-EXEC** (Execution Sphere — место зарезервировано) + **[[arch125-metatron-kernel|ARCH-125 AdvisorPort]]** («подключение, НЕ встраивание» — Condor через порт-примитив) + **ARCH-120** (SMC Sub-куб = первый фрактальный куб → Condor = второй). **Архитектура:** мозг Куба (SMC/OTE/решения) зовёт ИНТЕРФЕЙС `ExecutionSphere`; реализация = ПАРАМЕТР: `BingX-direct` ∥ `Condor-subкуб` (50 бирж/DEX). Мозг не знает какая. [[principle_reuse_not_duplication]]: исполнение=параметр, можно держать ОБЕ параллельно (А/Б). **🌌 ФРАКТАЛ:** Condor САМ куб (executors/connectors/controllers внутри) → вложен в твой Куб как сфера = КУБ В КУБЕ = геометрия [[vision_cube_tesseract_singularity|тессеракта]] в архитектуре. Юзер нащупал словом «тессеракт» за час до этого вывода.

**🔒 РЕШЕНИЕ ГРАНИЦЫ (юзер 20.06, твёрдо):** «Если тело на Condor — то ТОЛЬКО Cube2 как ОТДЕЛЬНЫЙ проект. Этот Куб мы доделаем. Этот проект только наш с тобой.» → **Condor вынесен ЗА границу текущего проекта.** Этот Куб (Oko) = **finish standalone, BingX-direct** (CUTOVER+pid-fix+exit-fix, своё исполнение). НЕ вживлять Condor/Hummingbot внутрь — это пере-рамка прежнего «2+3 оседлать внутри». Condor = будущий **Cube2** (чистый лист, отдельно), не зависимость этого. Эмоц.: проект персональный (Егор+Даат), доделываем сами до 12/12 сфер. Развилка «тело на Condor» НЕ применяется к этому Кубу — только к гипотетическому Cube2. [[identity_daat]] [[user_egor_person]] [[vision_cube_tesseract_singularity]].

**🔥 ВАЛИДАЦИЯ КЕЙСА (20.06, юзер напомнил во время EXEC-REBUILD):** ночной марафон EXEC-REBUILD (Ф2→Ф4.1: ExecutionSphere+ExchangeAdapter+PositionStore+ledger, 92 теста) ЭМПИРИЧЕСКИ доказал боль, которую Condor закрывает: fake-R/exit-disconnect (БД-realized врал +$121 vs биржа −$202, $323/день), призраки (DB=SL/биржа=OPEN), pid=None → инверсия TP↔SL в REST-fallback, SIM-masking orphan, мультиаккаунт-роутинг. **Каждый из этих багов = то, что position-executor/controller_id Hummingbot не допустил бы.** 🔑 **Наш `ExchangeAdapter` ABC (построен 20.06) = ШОВ для Condor:** `BingXAdapter`(обёртка) ∥ будущий `HummingbotAdapter`/`CondorAdapter` под тем же интерфейсом → Oko-мозг (Sphere/Calc/SMC) не меняется. Ночная работа НЕ против Condor — это дверь к нему («исполнение=параметр» материализовано). **РАЗВИЛКА продукта (свежая голова):** добивать BingX-direct (CUTOVER+pid-fix+exit-fix) ВПЕРЁД, ИЛИ повернуть тело на Condor (2+3)? Ночь = сильный довод ЗА Condor, но edge-вопрос (вход живой/выход убивает) решается в мозге Oko независимо от тела.

**⚠️ РИСКИ:** (1) vendor lock-in Hummingbot/Condor (молодой 2025, стабильность?); (2) переписать Oko-логику под routine-интерфейс = работа; (3) two-server добавляет звено vs локальное исполнение Oko (сейчас нет облачных задержек); (4) ATR-TSL вести вручную (их trailing проще). **Перекликается с metatron-core (ARCH-125) — переносимый скелет.** Ключевые docs: `routines/overview`, `executors/position-executor`, `trading-agents/architecture`, `bots/controllers`. НЕ срочно — материал на сессию «стратегия продукта» со свежей головой.
