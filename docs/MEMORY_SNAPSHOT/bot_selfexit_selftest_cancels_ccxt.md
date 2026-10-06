---
name: bot_selfexit_selftest_cancels_ccxt
description: "✅ 29.09: самопроизвольные выходы бота через ~1 мин после рестарта (pm2 «exited code 1 via SIGINT» без «Stopping») — SelfTest звал load_markets под wait_for(10 с), таймаут отменял ОБЩУЮ задачу ccxt markets_loading, её ждал главный старт → CancelledError. Лечение asyncio.shield в DataCollector (3579484)"
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-09-29T18:02:08.631Z
---

29.09 бот дважды сам выходил через 65–80 с после рестарта (04:17:36, 17:41:05). В pm2 «exited with code [1] via
signal [SIGINT]» БЕЗ «Stopping app» — это подпись pm2 для любого выхода, не настоящий Ctrl+C. Признак в логе: все циклы
«started» и «cancelled» в одну секунду; трассировка start_monitoring → load_markets → ccxt `await self.markets_loading`
→ CancelledError.

Механика: ccxt держит ОДНУ задачу markets_loading на всех вызывающих; `core/selftest.py` при старте зовёт
`asyncio.wait_for(dc.load_markets(), timeout=10)`. BingX медленный → таймаут → asyncio отменяет ожидаемую задачу, то есть
общую загрузку → главный старт получает CancelledError → бот выходит. Хронология: SelfTest 17:40:45–56 → отмена 17:41:00.
Редкий (2 из 11 рестартов) — только при медленном BingX. Отброшено проверкой: Ctrl+C от шлюза OmniRoute (3 цикла подъёма/
остановки — сигнала нет; выходил только бот, не все приложения pm2).

Лечение: `asyncio.shield(self.exchange.load_markets())` в DataCollector (оба места). Тест test_load_markets_shield.py
воспроизводит сбой. Боевая проверка 20:58: загрузка рынков ~50 с, бот поднялся полностью.

**Why:** каждый самовыход — окно без торгового цикла и дыры в данных (бары WS).
**How to apply:** общий future/задачу, которую ждут несколько корутин, ждать через asyncio.shield, если хоть один
вызывающий может быть отменён (wait_for, таймауты, отмена задач). «SIGINT» в pm2 на Windows — не доказательство Ctrl+C.
Связано: [[pm2_windows_restart_orphans]], [[ws_cache_holes_after_restart]].

**30.09 родственная дыра старта (✅ исправлена `fe93a49` — фоновые повторы 15/30/60/120 с):** 13:05 BingX `/swap/v2/quote/contracts` → RequestTimeout →
`load_markets` вернул [] → `bot/monitoring.py:start_monitoring` отвечает «❌ Не удалось загрузить пары» и выходит
без повтора → бот живёт БЕЗ скана (13:05–13:16, заметили по хабу: возраст доски рос линейно). Признак в логе:
«[MarketWS-v2] enabled, но usdt_pairs пуст» и нет «Скан: N пар». Было: лечилось только рестартом.
