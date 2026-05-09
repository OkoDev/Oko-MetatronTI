# Аудит: STOP-LIMIT ордера исчезают на BingX VST

**Дата:** 2026-04-19
**Инцидент:** DEV-175 STOP-LIMIT ордера пропадают с биржи → позиции остаются без защиты → SL срабатывает по рынку с катастрофическим slippage.
**Статус:** Временный фикс применён (`sl_limit_buffer_pct: 0` → STOP_MARKET). Root cause на стороне биржи не подтверждён.

---

## 1. Хронология

| Дата | Событие |
|---|---|
| 16.04 | DEV-175: внедрён `sl_limit_buffer_pct=0.3` для защиты от slippage. Код в [order_manager.py:320](../core/exchange/order_manager.py#L320), [bingx_client.py:320](../core/exchange/bingx_client.py#L320). Тип ордера: `STOP` (Stop-Limit) с буфером 0.3%. |
| 16–19.04 | Бот ставит SL как STOP-LIMIT. Часть ордеров **исчезает** с биржи после размещения. |
| 18–19.04 | Позиции без SL движутся против направления. SL-цена пробивается → `position_sync` закрывает по рынку с огромным gap. |
| 19.04 21:00 | Обнаружено: 22 позиции без STOP_MARKET ордеров. Две первопричины: (1) аудит-скрипт ищет только `type==STOP_MARKET`, пропускает `STOP`; (2) реально исчезнувшие STOP-LIMIT. |
| 19.04 21:10 | Бот остановлен. `sl_limit_buffer_pct: 0.3 → 0`. 22 позиции восстановлены STOP_MARKET. Бот перезапущен. |

---

## 2. Фактическое влияние

Запрос по БД (`closed_at >= 2026-04-18 AND R_multiple < -1.5`):

| Метрика | Значение |
|---|---|
| Сделок с R < -1.5 за 18–19.04 | **15+** (top-15: от −13.5R до −3.4R) |
| Худшие: CHR −13.5R, ARB −9.4R, PYTH −9.4R, SUSHI −7.8R, 1000000BOB −7.0R |
| Сумма PnL% по 533 SL (16–19.04) | **−559.87%** (средний −1.05% на сделку) |
| Win-rate по направлениям не анализировался — предмет отдельного разбора |

**Интерпретация:** правило DEV-175 `sanity_check R<-2` помечает такие сделки как **аномалии** (gap/slippage). 15 таких за 2 дня — это не норма, а прямое следствие отсутствия биржевого SL.

---

## 3. Root cause — гипотезы

### 3.1. Гипотеза A: VST не сохраняет STOP-LIMIT (основная)

Факты:
- `bingx_client.place_stop_order()` возвращает `orderId`, бот пишет в БД.
- Через N циклов `audit_missing_stops` показывает: ордера нет в `get_open_orders()`.
- При `sl_limit_buffer_pct=0` (STOP_MARKET) — ордера **остаются**.

Не подтверждено напрямую (нет серверных логов биржи), но эмпирически воспроизводится.

**Возможные причины на стороне BingX VST:**
1. STOP-LIMIT с `workingType=MARK_PRICE` в демо-режиме не поддерживается стабильно.
2. Limit-цена (stop ± 0.3%) выходит за допустимый отступ от текущей цены → ордер отбрасывается асинхронно.
3. Демо-движок матчинга периодически чистит STOP-LIMIT на рестартах сервиса.

### 3.2. Гипотеза B: TSL бесконечно переставляет SL

Лог показывает 2527 событий `update_sl ... отменяем` + несколько REPAIR циклов. Если `tsl_updater` отменяет старый SL и новая установка падает молча — позиция остаётся голой. Требует отдельной проверки: логируется ли **возврат от биржи** при ре-создании SL.

### 3.3. Гипотеза C: rate-limit 110206 "TP/SL orders exceeded"

Мы наблюдали этот код: 1000PEPE имел 73 open orders, VANRY 70. Значит **старые SL не отменялись** перед установкой новых. Это отдельный баг order_manager, ортогональный STOP-LIMIT.

---

## 4. Провалы в детекции

### 4.1. `audit_missing_stops.py` — ложно-отрицательные

[scripts/audit_missing_stops.py:83](../scripts/audit_missing_stops.py#L83):
```python
if o.get("type") == "STOP_MARKET"
```

**Баг:** STOP-LIMIT ордера (`type=="STOP"`) пропускаются — аудит их не видит, позиция помечена как «без SL», хотя ордер есть. И наоборот: реально исчезнувшие STOP_MARKET были бы пойманы, но сценарий DEV-175 (STOP-LIMIT) скрывал проблему.

**Фикс:** `if o.get("type") in ("STOP_MARKET", "STOP")`.

### 4.2. Нет алерта «SL исчез на живой позиции»

`position_sync` знает о расхождении (позиция OPEN, SL order gone), но реакция — молчаливое закрытие по рынку. Нужен TG-алерт **в момент** обнаружения, до того как цена пробьёт SL.

### 4.3. Нет проверки возврата от `place_stop_order`

В логе видно `✅ новый SL ... order_id=...` сразу после POST — но **не** видно последующей верификации «через 5 сек запросили open_orders и убедились что он там есть». Без такой проверки молчаливое исчезновение не ловится.

---

## 5. Временный фикс (применён 19.04 21:10)

| Файл | Изменение |
|---|---|
| [config.yaml:124](../config.yaml#L124) | `sl_limit_buffer_pct: 0.3 → 0` |
| БД | 22 позиции получили новый `exchange_sl_order_id` (STOP_MARKET) |

Стоимость: возвращается slippage, от которого DEV-175 защищал. Но отсутствие SL **хуже** любого slippage, поэтому это корректный откат.

---

## 6. Что делать — рекомендованные задачи

| # | Название | Приоритет | Файл |
|---|---|---|---|
| DEV-184 | Fix `audit_missing_stops.py` — включить `type in ('STOP_MARKET','STOP')` | High | [scripts/audit_missing_stops.py:83](../scripts/audit_missing_stops.py#L83) |
| DEV-185 | `order_manager.place_sl_order()` — после POST запросить `get_open_orders` и проверить наличие. Если нет — ретрай как STOP_MARKET | High | [core/exchange/order_manager.py:320](../core/exchange/order_manager.py#L320) |
| DEV-186 | TG-алерт «SL missing for OPEN position» в `position_sync`/`order_reconciler` | High | [core/exchange/position_sync.py](../core/exchange/position_sync.py) |
| DEV-187 | Расследовать почему TSL иногда оставляет N>1 SL ордеров (1000PEPE=73) — отмена старого перед установкой нового должна быть инвариантом | Medium | [core/exchange/order_manager.py:210](../core/exchange/order_manager.py#L210) |
| DEV-188 | Фоновый watchdog раз в 60 сек: `open_positions` vs `open STOP/STOP_MARKET` по парам — если mismatch → автоматический REPAIR через `place_sl_order` | Medium | новый `core/exchange/sl_watchdog.py` |
| DEV-189 | Экспериментально: вернуть `sl_limit_buffer_pct=0.1` и проверить, исчезают ли ордера с меньшим буфером. Если проблема решается — фикс DEV-175 применим с корректным параметром | Low | config эксперимент |
| DEV-190 | Повторная переоценка данных 16–19.04 (`data_era='post_fix'`): сделки с R<-2 пометить как **аномалии** в `features_json` и исключать из train-set OutcomePredictor | Low | [scripts/data_integrity_audit.py](../scripts/data_integrity_audit.py) |

---

## 7. Уроки

1. **Любой внешний API нужно верифицировать после записи.** «200 OK + orderId» не означает, что ордер живёт. Проверять через `get_open_orders` спустя 1–5 сек.
2. **Аудит-скрипты должны покрывать все типы ордеров, которые может создать система.** Если DEV-175 вводит новый тип — audit-скрипт обязан обновиться в том же PR.
3. **VST ≠ prod.** Демо-контур BingX имеет поведенческие отличия (STOP-LIMIT нестабилен). Перед переходом на live — повторить тест: STOP-LIMIT с тем же буфером на малом капитале.
4. **Порог R<-2 как sanity (из DEV-175) сработал** — пометил 15 сделок. Это рабочий индикатор инфраструктурной проблемы. Добавить агрегат «число R<-2 за сутки» в дашборд как alert-триггер.
5. **Metrics lie without distribution** (знакомый урок 18.04) — avg_R за 16–19 «всего» −0.72, но top-15 сидят на −3.4...−13.5R. Смотреть распределение, не только среднее.

---

## 8. Критичные файлы (для будущих работ)

| Путь | Содержит |
|---|---|
| [config.yaml:124](../config.yaml#L124) | `sl_limit_buffer_pct` — ручка STOP_MARKET/STOP-LIMIT |
| [core/exchange/order_manager.py:210-344](../core/exchange/order_manager.py#L210) | размещение SL, `place_sl_order` и `update_sl` |
| [core/exchange/bingx_client.py:299-365](../core/exchange/bingx_client.py#L299) | низкоуровневые BingX эндпоинты STOP/STOP_MARKET |
| [core/exchange/position_sync.py:190](../core/exchange/position_sync.py#L190) | обнаружение расхождения позиция↔SL |
| [scripts/audit_missing_stops.py:83](../scripts/audit_missing_stops.py#L83) | аудит (баг: пропускает STOP) |
| [scripts/repair_missing_stops.py:29](../scripts/repair_missing_stops.py#L29) | whitelist-ремонт |

---

## 9. Верификация после фикса

- [x] 22 позиции имеют STOP_MARKET (19.04 21:10)
- [x] Бот перезапущен PID=61508, 21:20
- [ ] Через 24 ч: повторный `audit_missing_stops` → 0 missing
- [ ] Через 48 ч: распределение R за период 20–21.04 — нет сделок с R<-2 (если есть — проблема не в STOP-LIMIT)
- [ ] DEV-184..188 реализованы → инцидент воспроизводим только как регрессия теста
