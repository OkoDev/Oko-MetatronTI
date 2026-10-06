---
name: backup-system
description: "Ежедневный автобэкап критичных БД на F: (другой физ.диск) — как восстановить"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
---

**Что (11.07.2026, желание №6):** `scripts/backup_dbs.py` — pm2 `backup-dbs`, cron 04:10 UTC.
Бэкапит на `F:\oko_backups\` (Seagate HDD = ДРУГОЙ физический диск от E: где бот на ADATA SSD →
смерть SSD не уносит трек-рекорд): `subscriptions.db` + `oko_feed/external_data.db` + `config.yaml`
+ `.env` в один `oko_backup_YYYYMMDD_HHMM.tar.gz` (~75МБ). **НЕ** бэкапит `ohlcv_cache.db` (17ГБ,
перекачиваемый через `scripts/fetch_binance_vision.py`).

**Метод:** sqlite3 online-backup API (`con.backup(bck)`) — безопасно ПОКА бот пишет (файловая
копия рвёт БД на середине записи). Ротация: 14 ежедневных + воскресные на 8 недель.

**Восстановление:** `tar -xzf oko_backup_*.tar.gz` → положить `subscriptions.db` в корень проекта,
`external_data.db` в `oko_feed/`. Проверка целостности: `PRAGMA integrity_check` (при создании
верифицировано: ok, 45126 сделок). Провал/успех бэкапа → TG SYSTEM-канал.

**Watch:** oi-fast память 27→258МБ после SMC-чартов (matplotlib import); `plt.close(fig)` есть
(chart_builder.py:409) → не утечка, resident-cost. См. [[current_state]].
