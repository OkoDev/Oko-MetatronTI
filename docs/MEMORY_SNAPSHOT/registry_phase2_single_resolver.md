---
name: registry_phase2_single_resolver
description: "🧩 Реестр стратегий, фаза 2 (22.08): один резолвер source_registry вместо четырёх ключей. per_strategy/threshold/in_list ищут по source → trade_mode → СИНОНИМУ (wt_sideways ↔ sideways). Замер ДО/ПОСЛЕ: 0 расхождений"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9a19646e-5506-497f-b946-1c75aeb88a81
  modified: 2026-08-22T13:04:11.075Z
---

# 🧩 РЕЕСТР СТРАТЕГИЙ, ФАЗА 2 — ОДИН РЕЗОЛВЕР (22.08.2026)

## Что было
К свойствам стратегии код ходил по ЧЕТЫРЁМ ключам с РАЗНЫМИ запасными значениями:

| место | ключ | запас |
|---|---|---|
| `gates/min_sl_dist.py` | `ctx.source` | 0.5 |
| `trade_simulator` (стоп) | `trade_mode` | 0.5 |
| `order_manager` | параметр `source` | **0.1** ← другой |
| `gates/rr_filter.py` | `ctx.source` | 2.0 |
| `trade_simulator` (RR) | `trade_mode` | 2.0 |
| tp_mode / rr_cap | членство по `signal_type_override` | списки хардкодом |
| tsl_activation_r | `signal_type` из БД | — |

У `impulse_fib` имена совпали СЛУЧАЙНО. У `wt_sideways` уже расходятся
(`source=wt_sideways`, `trade_mode=sideways`) — порог под одним именем был невидим
половине кода. Ровно так impulse_fib потерял 8 сигналов из 8
([[bug_gate_lives_in_two_places]]), а min_rr=2.0 убил rangefade целиком
([[bug_rr_gate_killed_tp1r_edge]]).

## Что стало
`core/trading/source_registry.py`:
- `per_strategy(per_key, source, trade_mode)` — ядро: ищет по `source` → `trade_mode`
  → **синониму реестра** (пара source ↔ trade_mode из политики источника) → None;
- `threshold(per_key, global_key, …)` — то же плюс глобальный запасной ключ;
- `min_sl_dist_pct()` / `min_rr()` — тонкие обёртки;
- `in_list(cfg_key, …)` — членство в списках (`single_tp_sources`, `rr_cap_exempt`);
- конфликт объявления (оба имени с РАЗНЫМИ значениями) → WARNING в лог, побеждает `source`.

## Верификация (обязательное условие задачи — пороги не должны поехать)
Замер ДО/ПОСЛЕ: **0 расхождений** — 33 источника × min_sl_dist, 33 × min_rr,
17 реальных имён из БД × tsl, 14 фактических пар `(trade_mode, override)` из боевых
записей × списки. Негативные тесты 8/8. `pytest` router+TSL — 34 passed.
Три рестарта, каждый раз SelfTest 12/12.

## Побочно найдено
- **4 вызова `open_bracket` не передавали `source`** (`scan_loop` ×3: wl_breach,
  atr_change, sideways; `monitoring`) → per-strategy порог там не работал В ПРИНЦИПЕ.
  Проброшено.
- `radar_pump`/`radar_spring` пишутся в `signal_type_override`, но в реестре политик
  их НЕТ (там `radar`) — остаточная мина того же класса, задача `REG-RADAR-SUBTYPES`.

Фаза 3 (общий раннер вместо двух impulse-лупов) — не начата.

---

## ✅ ФАЗА 3 ЗАКРЫТА (22.08): ОБЩИЙ РАННЕР ВМЕСТО ДВУХ КЛОНОВ

**Замер перед работой:** diff двух лупов после нормализации имён дал **СЕМЬ различий**,
и все — параметры (ТФ · масштаб окон · имя источника · таблица журнала · путь к
дрейф-гейту · тег лога). Остальные ~420 строк совпадали дословно.

Цена дублирования уже была заплачена: правка окон под ТФ жила в одном файле и могла
не доехать до близнеца ([[twins_15m_stabilized_by_measure]]).

**Стало:** `bot/loops/impulse_fib_runner.py` — поведение в одном экземпляре,
инстанс описывается дата-классом:

    INSTANCE = Instance(src="impulse_fib_15m", tf="15m", tf_mult=4,
                        table="impulse_shadow_15m", tag="IMPULSE15")

`wait_bars`/`hold_bars` — вычисляемые свойства (`WAIT_BARS * tf_mult`), поэтому окна
физически не могут разойтись с ТФ. Добавить ТФ = строка описания, а не копия файла.
Код: 862 строки в двух клонах → 468 раннера + 66 в двух описаниях.

**Регрессия `scripts/verify_impulse_runner.py` (3 проверки):**
- A. константы инстансов против прежних лупов — совпали (12/96 и 48/384);
- B. резолвер старый против нового на одних данных и записях — **700 записей 1:1**,
  10 символов, статусы + время резолва + result_pct + bars_to_fill;
- C. точки входа (`impulse_fib_loop`, `_TABLE`, `_resolve`) на месте — `bot.py` и
  `verify_impulse_fib_loop.py` не тронуты вовсе.

Старая регрессия `verify_impulse_fib_loop.py` тоже зелёная (0 расхождений в A и B).
Рестарт → **SelfTest 12/12**, оба инстанса поднялись из раннера, ошибок нет.
Окна теперь печатаются в стартовой строке лога (`окна 12/96 баров`) — дефект вида
«клон живёт не на своей длительности» стал видимым с первой секунды.

🔴 Бэкапы `*.bak.phase3` НЕ УДАЛЯТЬ: их импортирует регрессия как эталон.

---

## ✅ DEV-238 + REG-RADAR-SUBTYPES ЗАКРЫТЫ 22.08: КЛЮЧ ПЕРЕВЕДЁН НА `signal_type`

Оказались одной задачей. Корень общий: **LIKE по JSON ломается о суффиксы** —
`'%"trade_mode": "impulse_fib"%'` требует закрывающую кавычку и не ловит
`impulse_fib_15m`; так лимитки нового источника молча выпали из лайфцикла 21.08.

**Найдено третье имя источника.** У `radar` в `signal_type` пишутся ПОДТИПЫ:
за 90 дней `radar_pump` 291 · `radar_build` 115 · `radar_spring` 104 ·
`radar_build_flip` 60 — при одном `trade_mode='radar'` и одной политике.
Порог, вписанный под подтипом, роутер (`ctx.source='radar'`) не увидел бы вовсе.

**Сделано:**
- в политику radar добавлено `signal_subtypes: [...]`;
- реестр получил `subtypes()` / `signal_types()` / `types_sql()`;
- `_aliases()` расширен на подтипы двусторонне → `min_rr('radar_pump')` = 0.5
  (порог родителя), при этом чужие имена не задеты (`radar_unknown_x` → глобальный 2.0);
- `pending_sql()` переведён с `features_json LIKE` на `signal_type IN (...)`;
  старый ключ остался доступен явным `column="features_json"`;
- в `radar_armed_loop` на реестр переведены 5 мест: счётчик, symbol_busy,
  BE-раннеры, repair TP-oids, финальный тред. LIKE остался только в fallback-ветках.

**Эквивалентность ключей доказана на боевой базе (замер ДО/ПОСЛЕ):**
radar-семейство 570 = 570, пересечение полное, расхождений 0;
pending-набор: PENDING 5=5, OPEN 4=4, всего 630=630.
Рестарт → SelfTest 12/12, лайфцикл видит все 5 заявок, ошибок нет.

🔴 **Осознанно НЕ тронуто:** `method_egor`/`method_v2` (выключены, ключ по
`features_json LIKE`) и `atr_s2` в `scan_loop` (ни одной записи в БД для сверки,
проверка fail-closed — промах ключа открыл бы кэп настежь).
