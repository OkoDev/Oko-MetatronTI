---
name: strip_twin_shared_cache
description: "STRIP-TWIN — strip-бот как A/B-близнец на общем OHLCV-кэше main (не дублирует REST). Блокер: strip заброшен с 16.05 на старом коде, не git-связан"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**STRIP-TWIN (юзер 14.06: «strip кормить нашим кэшем для симуляции?»).**

**Реальность strip** (`E:\MTF BOT\CURSOR\crypto_volume_bot_strip`): отдельная скопированная папка, **НЕ git-ветка** main. Заброшен с ~16.05 (`crypto_bot.log` 656MB mtime 16.05, `ohlcv_cache.db` 12.04). Точка входа `bot_with_subscriptions.py` (main переименован в `oko_mtf.py` 15.05) → strip отстал на месяц ARCH-изменений (EXEC-WS, perf-loop, GlobalRateLimiter, SIM-DEPRIO — мимо). Чистый sim (subscriptions.db, не торгует на бирже).

**Кэш main:** рабочий = in-memory LRU `ApiEngine._cache._data` (класс `OhlcvCache` api_engine.py:38). Дисковый `ohlcv_cache.db` 2.5GB = периодич. дамп `save_to_disk()` (mtime 18.05), НЕ живой кэш. 2 процесса не делят in-memory dict → нужен слой обмена.

**Идея кормления — двойная польза (обе в тему ночной работы):**
1. **IP-бюджет:** [[exec_ws_vst_userdata_proven]]/GlobalRateLimiter защищают ОДИН IP от бан 100410. strip тянет биржу сам → удваивает запросы → риск бана. strip ест кэш main → 0 запросов → бюджет цел.
2. **Детерминизм A/B:** независимый fetch → разные бары → нечестное сравнение. Общий кэш → бит-в-бит одни данные → разница ТОЛЬКО в логике/конфиге (золотой стандарт A/B). = [[principle_reuse_not_duplication]] (один источник, два потребителя).

**Варианты слоя:** B(реком.) HTTP `/api/ohlcv` на dashboard:8000 (инфра есть — уже отдаёт /api/pairs; main горячий путь не трогаем; strip read-only); A общий SQLite WAL (main пишет, strip читает; файл есть, но блокировки); C Redis (избыточно).

**🔴 БЛОКЕР перед «врубить»:** strip = старый код. A/B нового конфига = грязный (конфиг + месяц дрейфа). Сначала ЛИБО пересоздать strip из текущего main (тогда A/B = только конфиг), ЛИБО определить что strip тестирует иначе.

**Статус:** 🔵 research-backlog (TASKS:STRIP-TWIN). Не код на ночь — прогон main не трогать. Связь: [[sim_deprioritize_loop]] (strip = весь sim → те же принципы), вектор «Куб питает несколько потребителей».
