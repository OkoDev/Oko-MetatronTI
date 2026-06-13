# PERF-LOOP-DRIFT — Шаг B: изоляция торгового loop (эпик)

> bot-arch проект, 13.06.2026. Контекст: C keep-alive + OTE executor закоммичены (`db9726d`),
> timestamp invalid −80%. B развязывает торговлю от scan-нагрузки → торговый rtt не зависит
> от числа пар (критично при 500+). Главный блокер: GlobalRateLimiter shared cross-loop.

## Решение блокера GlobalRateLimiter (Вариант A)

Переписать на **process-wide token-bucket** loop-agnostic:
- `threading.Lock` — только на атомарную резервацию слота (держится микросекунды, арифметика).
- Само ожидание `await asyncio.sleep(sleep_for)` — ВНЕ лока, в вызывающем loop.
- Бан: `_ban_until` (monotonic deadline) проверяется в `acquire`; убрать `asyncio.ensure_future`/фоновый `_unban_after` (acquire сам спит до deadline).
- **Сохраняет ОДИН IP-бюджет** (process-wide state) при работе из двух loop. Отклонены: B (per-loop = 2× RPS = баны), C (один loop = текущее).

## Почему выгода реальна (GIL честно)

Корень rtt-пиков = **scheduler starvation**, НЕ GIL: при 200 парах сотни готовых корутин (scan_one до 203, TaskSampler 881) в одной ready-очереди; торговая корутина после `await` встаёт в конец → ждёт прокрутки сотен. Отдельный loop = собственная ready-очередь → торговые callbacks планируются мгновенно. GIL: scan I/O-bound (отпускает GIL) + numpy SMC (отпускает) → торговый поток получает GIL почти сразу; остаточный джиттer десятки мс (чистый Python SMC) смягчён OTE executor. Приемлемо.

## Поэтапный план (риск + критерий)

| Шаг | Что | Файл | Риск | Критерий проверки |
|---|---|---|---|---|
| **0** | GlobalRateLimiter → threading token-bucket (loop-agnostic). Изолированный коммит, БЕЗ флага (обратно-совместимо). | `core/infra/api_engine.py:254-318` | **Высший для банов**: ошибка bucket → 100410 или over-throttle | unit: конкурентный acquire 2 loop → RPS≤rps; бан виден cross-loop; одиночный loop = идентичное поведение (replay RPS до/после) |
| **1** | Инфраструктура торгового loop за флагом `trading.dedicated_loop` (default false). Daemon-поток + `new_event_loop()` + wrap-хелпер + graceful shutdown. Мёртвый код при off. | новый `core/infra/trading_loop.py`, `bot/core/bot.py` | минимальный | on → старт/стоп чисто; off → нулевая разница |
| **2** | OrderManager: все `await client.*` через `_call(coro)` = при флаге `wrap_future(run_coroutine_threadsafe(coro, trading_loop))`, иначе прямой await. session lazy → создастся в торговом loop. | `core/exchange/order_manager.py` | **Высший для 92 живых позиций**: wrap сломает place/cancel SL → позиции без стопов | VST: open/close/cancel SL через loop, сверка с биржей; торговый rtt не растёт с парами |
| **3** | tsl_updater place_* — наследуют обёртку шага 2 через `om`. Проверить что не создаёт свой клиент. | `core/exchange/tsl_updater.py` | средний (TSL не двинет SL) | VST: TSL активация → перенос SL на бирже |
| **4** | EXEC-WS в торговый loop (`run_coroutine_threadsafe(stream.run())`). keepalive/stats create_task внутри run() → ок. | `core/exchange/exec_ws_integration.py`, `user_data_ws.py` | WS reconnect в чужом loop | exch_id пишется; reconnect не растёт под scan |
| **5** | Сверка market-data (`_sem`, in-flight Futures) остался в main; включение LIVE после ≥24ч VST. | — | финальный | 24ч без банов; торговый rtt p99<1с при 200+; LAG main не вырос; 92 позиции с целыми SL |

## Критичные подводные камни (эффект бабочки)

1. **`scripts/*` создают свой `OrderManager(config)`** в отдельных процессах — НЕ видят торговый loop бота. Обёртка `_call` ДОЛЖНА gracefully падать в прямой `await` если trading_loop не поднят (флаг off / др. процесс). Иначе сломаются ремонтные скрипты (close_orphans, repair_*) — критично для ручного управления орфанами.
2. **EXEC-WS `_get_listen_key`** — проверить идёт ли через GlobalRateLimiter; если нет → вне IP-бюджета (баны при reconnect-шторме). Уточнить на шаге 4.
3. **Cross-loop исключения** — оборачивать `_call` так, чтобы оригинальный exception пробрасывался (через `wrap_future`), иначе теряем traceback ошибок place SL.

## 🔴 Критика роя (7/7, 13.06) — УТОЧНЕНИЯ перед реализацией

Рой подтвердил направление (изоляция реальна, GIL не мешает, порядок 0→1→2 верен), но выявил **2 риска сверх плана** + лучший механизм:

**1. 🔴 DEADLOCK через sqlite3 (gemini/cerebras — главный новый риск):**
OrderManager тесно связан с БД (raw sqlite3, `busy_timeout` в `subscription_manager.py:30`). Если main loop блокирует sqlite3 на запись, а торговый loop через `run_coroutine_threadsafe` пытается обновить статус ордера в БД → **взаимная блокировка потоков**. `wrap_future` в синхронном контексте усугубляет.
→ **ОБЯЗАТЕЛЬНО перед шагом 2:** аудит — делает ли `OrderManager`/`client.*` запись в БД ВНУТРИ торгового пути. Если да — БД-доступ вынести из cross-loop (отдельная очередь записи / держать БД в одном loop).

**2. 🔴 `_ban_until` рассинхрон (openrouter — лучший аргумент):**
Несогласованный `_ban_until` между loops → регресс защиты от 100410. → ban-state должен быть **process-wide atomic** (одно поле, monotonic deadline, читается обоими loop без отдельных asyncio.Event на loop).

**3. 🟡 Падение торгового потока → потеря согласованности позиций.**
→ watchdog/supervisor торгового потока (heartbeat, restart/alert при смерти).

**4. 💡 ЛУЧШИЙ МЕХАНИЗМ (рой): `janus.Queue` + single-worker вместо wrap_future 30 callsites.**
Торговые запросы складываются в потокобезопасную `janus.Queue`; ОДИН воркер в торговом потоке забирает и шлёт с жёстким шагом. Преимущества: (а) IP-бюджет автоматически (один воркер = естественная сериализация, без race в token-bucket); (б) НЕ нужно оборачивать 30+ callsites; (в) меньше deadlock-риска; (г) traceback сохраняется. **Пересмотреть шаг 2 в пользу janus single-worker.** Минус: новая зависимость `janus`; задержка очереди (но торговля не HFT).

**Вывод роя:** план верен, но шаг 2 (cross-loop calls напрямую) = высокий deadlock-риск через БД. Реализовать с аудитом БД-вызовов + рассмотреть janus single-worker. Изолированный тест шага 0 + нагрузочный тест синхронизации loops обязательны.

Полный разбор: `obsidian/Team-Discussions/2026-06-13-валидация-плана-реализации-не-выбор-стратегии-план.md`

## Заметки
- AccountRouter уже `threading.Lock` (cross-thread-safe); клиенты создаются синхронно (loop-привязка только у session, ленивая) → перенос автоматический.
- api_engine `_sem` + in-flight Futures — только market-data, ОСТАЮТСЯ в main loop (не переносить).
- bot-arch agentId: ad2a1388eb1f853b4 (для уточнений).
