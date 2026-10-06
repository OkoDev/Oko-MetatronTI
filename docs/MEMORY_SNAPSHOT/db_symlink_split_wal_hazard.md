---
name: db_symlink_split_wal_hazard
description: 🔴 subscriptions.db — симлинк на C:\oko_data\; SQLite на Windows не разворачивает симлинк → WAL привязан к ПУТИ. В C:\oko_data лежит старый WAL 16.09 (перенёс move_dbs_to_nvme.ps1). Открыть БД по пути C:\ = увидеть «malformed»; при остановленном боте — влить страницы 16.09 в живую базу
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-09-26T19:46:43.373Z
---

Найдено на аудите 26.09.2026. `E:\...\subscriptions.db` → симлинк на `C:\oko_data\subscriptions.db`.
Бот открывает по пути E:\ и пишет WAL в `E:\...\subscriptions.db-wal`. `scripts/move_dbs_to_nvme.ps1:38-40`
перенёс вместе с БД её `-wal`/`-shm` в `C:\oko_data\` → там остался `subscriptions.db-wal` 5.6 МБ (mtime 16.09 06:46).

Проверено: соединение по пути `C:\oko_data\subscriptions.db` подхватывает этот WAL → page_count 401 169
вместо 418 634, `quick_check` = invalid page number, `count(*) simulated_trades` = malformed.
Через путь бота (`subscriptions.db` из корня проекта) — `quick_check ok`, 60 119 id. Бэкап 25.09 — ok.
Слияния не было, потому что бот держал блокировку (закрытие без EXCLUSIVE не делает checkpoint).

`C:\oko_data\move_log.txt`: перенос 16.09 06:46 сразу после `pm2 stop` (на Windows убивает без чистого
закрытия) → WAL 5.6 МБ уехал вместе с базой; сколько в нём было непереписанных транзакций — не разбиралось.
`ohlcv_cache.db` открывается по ОБОИМ путям: 26.09 01:37 в `C:\oko_data` появлялись его `-wal`/`-shm`, к 01:50 исчезли.

**Why:** если процесс откроет БД по пути C:\ при ОСТАНОВЛЕННОМ боте, закрытие соединения сделает checkpoint
старого WAL в живую базу = реальное повреждение. Плюс записи, бывшие в том WAL на 16.09, в базу не попали.
**How to apply:** БД открывать ТОЛЬКО по одному пути (путь бота). Не открывать `C:\oko_data\*.db` напрямую
даже на чтение. Чинить (с подтверждения Егора): остановить все процессы → перенести старые `-wal`/`-shm`
из `C:\oko_data` в карантин (не удалять) → один канонический путь в конфиге + проверка на старте.
Для `ohlcv_cache.db` в C:\oko_data свои `-wal` (0 байт) и `-shm`, путь открытия не сверен.
Связано: [[pm2_windows_restart_orphans]], [[tf_precompute_lab_speed]].

**✅ 26.09 ~22:00 МСК (решение Егора): старые `subscriptions.db-wal/-shm` → `C:\oko_data\_quarantine_wal_16sep\`**
(sha256 WAL `ABBD4F06CE09C697A9F981005B640D5C001CE58492A2B6924D85D6DFA0A57FB5`). Бот не останавливался — перенос
прошёл, значит файлы никто не держал. После: `quick_check ok`. Код открывает БД только по E:\ (grep `realpath` — пусто);
открытия по C:\ на аудите были мои. Остаётся: проверка пути на старте; транзакции до 16.09 06:46 в карантине, в базе их нет.
