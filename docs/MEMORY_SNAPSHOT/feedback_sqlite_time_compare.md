---
name: feedback_sqlite_time_compare
description: "SQLite сравнение времени — created_at это ISO с 'T', а datetime('now') даёт пробел; 'T'>' ' ломает фильтр в пределах дня. Использовать ISO-cutoff с 'T'"
metadata: 
  node_type: memory
  triggers: 
    - SQLite
    - created_at
    - datetime('now')
    - сравнение времени
    - SQL-запрос
  type: feedback
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**В SQLite-фильтрах по времени `created_at` сравнивать с ISO-cutoff С 'T', НЕ через `datetime('now','-N ...')`.**

**Why:** `created_at` хранится как `'2026-06-14T10:39:18.810540+00:00'` (ISO, разделитель `T`, микросекунды, +00:00). `datetime('now','-12 minutes')` возвращает `'2026-06-14 10:32:00'` (разделитель ПРОБЕЛ, без TZ). Строковое сравнение: `'T'`=0x54 > `' '`=0x20 → ВСЕ записи дня `...T...` оказываются `>= '...  ...'` независимо от часа. 14.06 запрос «биржевые за 12 мин» вернул 268 (весь день acc1) вместо 4 (реальное окно) → чуть не сделал ложный вывод про EXEC-WS. Граница РАЗНЫХ дней работает (дата отличается), но в пределах ОДНОГО дня фильтр полностью сломан.

**How to apply:** cutoff строить как ISO с 'T':
```python
import datetime
cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=12)).isoformat()
# или фикс: CUT = "2026-06-14T10:32:00"
cur.execute(f"... WHERE created_at >= '{cut}'")
```
НЕ `WHERE created_at >= datetime('now','-12 minutes')` (пробел vs T). Проверять результат: вывести MIN/MAX(created_at) — диапазон должен совпасть с ожидаемым окном.

Связь: [[feedback_db_query_utc]] (UTC vs МСК), [[feedback_verify_fix_dataera_first]] (split по моменту). 14.06 время подвело 4 раза за день (RR-дебаг 10ч окно, arch104 до-бан, EXEC-WS дважды) — ВСЕГДА проверять временной диапазон фактом (MIN/MAX), не доверять фильтру.
