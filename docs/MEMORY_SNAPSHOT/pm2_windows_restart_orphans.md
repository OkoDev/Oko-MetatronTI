---
name: pm2_windows_restart_orphans
description: "🔴 На Windows `pm2 restart` оставляет старый python-процесс сиротой: он держит порт/пишет файлы, новый экземпляр падает по кругу (structure-term: 8271 перезапуск), а «проверки после перезапуска» идут в СТАРЫЙ код. Перезапуск = stop → убить python по CommandLine → start → проверить владельца порта."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b9292ecd-40bf-480f-b583-11c47310bf19
  modified: 2026-10-04T22:13:12.860Z
---

14.09.2026: после нескольких `pm2 restart structure-term` с 10:11 порт 8010 держал осиротевший `python web/structure_terminal.py`
(родитель — демон pm2), а экземпляр pm2 падал с `OSError 10048` (порт занят) — 8271 перезапуск. Все проверки API
«после перезапуска» обслуживал старый код; у `wave5-shadow` тоже висел дубль (два процесса пишут state.json).

**Why:** pm2 на Windows убивает обёртку, а не дочерний python; ошибка не видна, если смотреть только `pm2 list` (статус online).

**How to apply:** перезапуск сервиса проекта —
1. `pm2 stop <app>`;
2. `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -like '*<script>*' | Stop-Process -Force`;
3. `pm2 start <app>`;
4. проверить: один python-процесс на скрипт; для веба — `Get-NetTCPConnection -LocalPort <port> -State Listen` → PID = PID из `pm2 list`;
   счётчик restarts в `pm2 list` не должен расти.
Связано: [[bug_watchdog_restarts_healthy_bot]], [[wave5_shadow_forward]].

**🔴 29.09 ОКНА КОНСОЛИ из-под pm2:** процесс под pm2, запускающий консольную программу (handle64, powershell),
открывает Егору окно Windows Terminal на КАЖДЫЙ вызов. `CREATE_NO_WINDOW` НЕ помогает (Windows Terminal — терминал
по умолчанию; проверено: окна всплывали). Рабочее: `creationflags=DETACHED_PROCESS` + `STARTUPINFO(SW_HIDE)` +
`stdin=DEVNULL`, вывод через `capture_output` (0 окон, вывод полный). PowerShell в DETACHED молчит — командную строку
процесса читать через `ntdll.NtQueryInformationProcess(h, 60, …)`, не через Get-CimInstance.

**15.09 повтор на oko-bot (живой бот):** в 18:30:07 кто-то (не эта сессия — её рестарты 13:57/14:14/14:21/14:53 чистые) сделал stop/start;
старый процесс остался сиротой ВНЕ pm2 и держал `bot_instance.lock`. pm2-экземпляр на каждом старте писал «⚠️ Бот уже запущен (обнаружен
lock-файл)» и выходил с кодом 1 → 22 рестарта за 15 минут; каждый старт спаунил LLM-хуки (daily_pipeline, weekly_digest, obsidian_indexer,
task_linker) — отсюда спам `[team-ask]/[swarm-ds]` и нагрузка. `pm2_guard.log` при этом писал «ok oko-bot online» — статус online врёт.
Лечение то же: stop → убить ВСЕ `oko_mtf.py` → start → через 2 мин restarts не растёт и 0 новых «уже запущен».
Признак для проверки: `pm2 describe oko-bot` uptime < 1 мин + два python с oko_mtf.py.

**✅ 15.09 ЛЕЧЕНИЕ В КОДЕ (коммит f5d05db) — для oko-bot ручная зачистка больше не нужна:**
корень — `scripts/bot_pm2.js` спаунит python потомком node-обёртки; pm2 на Windows завершает обёртку безусловно, потомок живёт.
Второй круг был в 20:42 (43 рестарта). Теперь: обёртка передаёт `OKO_PM2_WRAPPER_PID`, `oko_mtf._start_pm2_parent_watchdog`
держит хэндл её процесса (WinAPI; 🔴 без restype/argtypes HANDLE обрезается до 32 бит и ожидание сразу WAIT_FAILED) и при её
завершении снимает lock и выходит (rc 3); lock-проверка перенесена ДО бэкапа БД и LLM-хуков. Живой тест: обычный
`pm2 restart oko-bot` → один процесс, 0 «уже запущен». (29.09 подтверждено ещё раз: restart → один oko_mtf.py, :8000 через ~60 с.) Кто давал stop в 18:30/20:42 — не установлено (heartbeat_watchdog.py умеет
`pm2 restart oko-bot`, но не запущен; pm2_guard только resurrect). Для wave5-shadow/structure-term лечение прежнее (ручная процедура).

**🔑 04.10: РОСТ `restarts` ≠ АВАРИЯ.** За сутки счётчик вырос 30 → 41, и я доложил «причина не
установлена, бот нестабилен». Егор: «бот перезапускался по причине работы над проектом в
НЕСКОЛЬКИХ СЕССИЯХ ПАРАЛЛЕЛЬНО». То есть рестарты давали агенты, каждый после своей правки.
Traceback'и в логе (ccxt WS pong, aiogram send_photo) к ним отношения не имели — это фон.
**Прежде чем объявлять рестарты дефектом: спросить, не работает ли кто-то ещё.**
Последствия, которые ЕСТЬ и при «нормальных» рестартах: всё состояние в памяти процесса
теряется — волновой контекст обнулялся и прогревался 75 мин ([[wave_fifth_is_master_context]],
лечится персистом), WS-кэш получает дыры ([[ws_cache_holes_after_restart]]), прибор L12b даёт
12/13 на холодном логе. Поэтому состояние, которое дорого набирать, обязано переживать рестарт.
**И при параллельной работе:** перед коммитом смотреть `git status` на ЧУЖИЕ правки в дереве
(04.10 в нём лежали `scripts/news_sphere.py`, `START.md`, `whats-next.md` соседней сессии),
коммитить только свои файлы поимённо, `git add -A` не использовать.
