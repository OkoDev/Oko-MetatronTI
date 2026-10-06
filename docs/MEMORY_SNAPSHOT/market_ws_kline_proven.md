---
name: market_ws_kline_proven
description: "Кастомный aiohttp market-WS kline ДОКАЗАН (5m/15m push по парам) — рычаг разгрузки scan_loop от REST-polling. ccxt.pro был проблемой, не WS"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

> 🔴 БЛОКЕР 14.06: ПОТОКОВАЯ реализация ПРОВАЛИЛАСЬ из-за GIL. Этап 1+2 (`core/infra/market_ws.py`, поток) запущены в проде: merge РАБОТАЛ (replace 256k/append 1657 в основной кэш, shadow=False, DS вердикт WS==REST≥99%). НО market_ws-поток на ~70k свечей/мин (gzip+json.loads+merge = CPU) держит GIL → scan-loop в main-thread задушен → **scan-cycle 300с → 600с+ (НЕ завершался за 10мин)**. ОТКАТ `market_ws.enabled=false`. Python threading НЕ параллелит CPU. EXEC-WS работает (order-события редкие), MARKET-WS нет (high-rate CPU). **ПРАВИЛЬНЫЙ ПУТЬ: отдельный ПРОЦЕСС (multiprocessing, обходит GIL) + IPC-кэш (Redis/shared mem) = D-072 «data_service отдельный процесс + Redis».** Код market_ws.py + OhlcvCache RLock остаются (за флагом off) для переделки в процесс. Урок: high-rate WS (>~1k msg/с CPU-обработки) в Python = ТОЛЬКО процесс, не поток. → [[feedback_verify_fix_dataera_first]] (измерили в проде, не вслепую).

> 🎯 ДИЗАЙН v2 (рой 14.06, консенсус): **multiprocessing.Queue (stdlib), НЕ Redis** (Docker/Windows морока, избыточен 1→1). Producer-ПРОЦЕСС (multiprocessing.Process **spawn** на Windows) держит MarketWS (gzip/json/merge-парсинг в СВОЁМ GIL) + **агрегация** (слать только закрытые бары + последнее состояние текущего, НЕ 70k тиков → IPC десятки/сек). Main: лёгкий **QueueReaderThread** (Queue.get блокирующий → НЕ в asyncio loop) → cache.merge (iloc, GIL мс). Lifecycle: супервайзер is_alive()+авто-рестарт, graceful stop через Event. Сериализация msgpack. Устойчивость: TTL-fallback (краш→cache expire→scan REST). Spawn-нюанс: процесс импортирует market_ws.py заново → не тянуть ML, плоские параметры. Спор (gemini): TCP-socket asyncio vs Queue (Queue=фоновый поток+pickle скрытый GIL) — НО агрегация снимает (десятки/сек). Этапы: A producer+агрегация+Queue → B QueueReaderThread+supervisor → C запуск bot.py spawn за флагом → D shadow→use по ТФ. Это узкий первый шаг [[arch_db_v2_terminal]]/D-072. Реализация 1-2 дня, multiprocessing деликатно (spawn/supervisor) → свежей сессией, не в конце марафона.

**MARKET-WS kline push — ДОКАЗАН эмпирически 14.06 (`scripts/diag_market_ws_kline.py`).**

**Контекст:** scan_loop = узкое место loop (цикл 296-341с / 526 пар, 2867 asyncio lag-warnings, 454 slow OHLCV). Главная нагрузка — REST-fetch 5m/15m по всем парам каждый цикл. OHLCV TTL по ТФ уже оптимизирован (D-065: 4h=4ч/1d=24ч/1h=1ч кэш) — HTF не виноваты, грузят LTF refetch.

**Тест (public market WS, кастомный aiohttp, НЕ ccxt.pro):**
- Endpoint: `wss://open-api-swap.bingx.com/swap-market` (public, без listenKey)
- Subscribe: `{"id":uuid,"reqType":"sub","dataType":"<SYM>@kline_<tf>"}` (напр. `BTC-USDT@kline_5m`)
- Результат: **20/20 потоков (10 пар × 5m+15m) с данными, 2224 апдейта/90с (~25/сек)**, first @ 1-17с, 1 соединение. gzip + Ping/Pong.

**КЛЮЧЕВОЕ:** прошлый WsFeed отключён (ws_enabled=false) НЕ из-за WS-концепции, а из-за **ccxt.pro** (`ws_feed.py:32`: Phase F 1×240 → плато scan_loop 750s, нелинейный overhead). Кастомный aiohttp WS (как [[exec_ws_vst_userdata_proven]]) лёгкий — тот же приём, что оживил EXEC-WS.

**Рычаг 4 разгрузки loop (самый мощный):** kline push → OhlcvCache → scan_loop читает из кэша БЕЗ REST-polling. Цикл 300с → радикально меньше.

**Для полной реализации (ПРОЕКТ, не твик):** (1) масштаб 526×2=1052 подписки → батчи соединений (лимит BingX/conn; WsFeed бил батчами по 100); (2) kline-data → DataFrame(time/OHLCV) в OhlcvCache в формате scan; (3) отдельный поток (как EXEC-WS, не main loop); (4) реконнект + gap-fill (пропущенный бар → REST добор). Спроектировать роем/обсудить.

**Очередь рычагов разгрузки loop (14.06):** 1)event_loop_debug=false ✅ 2)scan_semaphore 5→8 3)SIM-DEPRIO/убрать лишние LTF 4)MARKET-WS kline (этот, стратегический). Проходим по одному, измеряя scan-cycle.
