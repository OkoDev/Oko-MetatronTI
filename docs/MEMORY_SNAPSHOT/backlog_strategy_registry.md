---
name: backlog-strategy-registry
description: "📋 РЕЕСТР СТРАТЕГИЙ — план работ. Корень 15 дефектов: к свойствам стратегии ходят по ТРЁМ РАЗНЫМ КЛЮЧАМ (source / trade_mode / signal_type_override), у impulse_fib они совпали СЛУЧАЙНО. Не DSL, а дотянуть существующий SourcePolicy + общий раннер + preflight-скрипт"
metadata:
  node_type: project
  type: project
  originSessionId: 696399f2-16be-4ffc-97be-acad52cc3fb5
  modified: 2026-08-20T23:15:16.693Z
---

# 📋 БЭКЛОГ: РЕЕСТР СТРАТЕГИЙ (план от 21.08.2026)

Егор: «механизм исполнения очень усложнён в части добавления новых стратегий —
приходится смотреть разные узлы, чтобы заработала».

Факт: чтобы завести ОДНУ стратегию, пришлось тронуть **11 мест в config.yaml
(7 секций) и 8 файлов кода**. Каждое обнаруживалось ТОЛЬКО через отказ в бою:
15 дефектов, 9 молчаливых.

## 🔑 КОРЕНЬ — НЕ «МНОГО МЕСТ», А ТРИ КЛЮЧА К ОДНОЙ ТАБЛИЦЕ
| где | ключ поиска |
|---|---|
| `core/trading/gates/min_sl_dist.py:32` | `ctx.source` |
| `core/trading/trade_simulator.py:454, 484` | `trade_mode` |
| `core/trading/trade_simulator.py:796, 890` | `extra_features["signal_type_override"]` |
| `core/exchange/order_manager.py:484-493` | параметр `source` |

**У `impulse_fib` все три совпали СЛУЧАЙНО. У следующей стратегии не совпадут —
и отказ снова будет молчаливым.**

## Решение: НЕ DSL, а дотянуть существующее
`core/trading/source_policies.py:29-79` — `SourcePolicy` уже есть и уже несёт
leverage/risk_pct/entry_order_type/trade_mode/soft_gates. Добавить поля:
`min_sl_dist_pct` · `min_rr` · `tsl_activation_r` · `tp_mode: SINGLE|DUAL` ·
`rr_cap: float|None` · `ttl_days` · `entry_lifecycle: none|limit_pending` + `pending_ttl_sec`.
Единый ключ — **`source`**. `trade_mode` остаётся полем, но перестаёт быть ключом поиска.
Границы: исполнение → `signal_router.source_policies.<src>`; механика (universe_top,
min/max_stop_pct, bars, sides, max_open) → `trading.<src>`. Семь секций → две.

## ✅ ФАЗА 1 СДЕЛАНА 21.08 — поля в SourcePolicy (read-only)
`core/trading/source_policies.py`: добавлены `min_sl_dist_pct` · `min_rr` ·
`tsl_activation_r` · `tp_mode` · `rr_cap_exempt`. Все читаются по ЕДИНОМУ ключу
`source`; потребители пока работают по-старому (переключение = фаза 2).
`None` = «не задано, работает глобальный порог».

Реестр сразу даёт полную картину, которой раньше не было нигде:
| источник | min_sl | min_rr | tsl | tp_mode | rr_exempt |
|---|---|---|---|---|---|
| impulse_fib | 1.4 | 2 | 99 | SINGLE | True |
| choch_wavec | 8 | 0.95 | — | DUAL | False |
| **wt_sideways** | — | — | 0.8 | DUAL | False |
| rangefade | 0.25 | 0.95 | — | DUAL | False |
| ote_nested | — | 0.9 | 4 | SINGLE | True |
| radar | — | 0.5 | — | DUAL | False |

Проверено после правки: `strategy_preflight impulse_fib --gates` чист,
**SelfTest 12/12**, бот поднялся. Бэкап `source_policies.py.bak.*` рядом.

🔴 ФАЗА 2 (не начата): переключать потребителей ПО ОДНОМУ с замером до/после.
Порядок: min_sl_dist ×3 → min_rr ×2 → tp_mode/rr_cap → ttl/tsl.
Опасность известна: смена ключа с `trade_mode` на `source` ДВИНЕТ пороги там,
где имена расходятся (`wt_sideways`→`sideways`). Пороги живых стратегий
зафиксировать замером ДО правки.

## Шаги (каждый оставляет систему рабочей)
0. **Аудит-скрипт** (полдня, риск нулевой): для 11 источников печатает старое значение по
   каждому из трёх ключей против нового. Расхождение = стоп.
1. **Поля в SourcePolicy, read-only** (1 день): реестр читает, никто не переключён.
2. **Потребители по одному** (2-3 дня): min_sl_dist ×3 → min_rr ×2 → tp_mode/rr_cap →
   ttl/tsl. После каждого — шаг 0 + `scripts/verify_impulse_fib_loop.py`.
3. **Общий раннер + вынос pending-лайфцикла** (2-3 дня, риск высокий):
   `choch_wavec_loop` (281 стр.) и `impulse_fib_loop` (377 стр.) совпадают ДОСЛОВНО в
   вселенной, `_fetch_1h`, `_resolve`, кэпе, дедупе. Переводить сначала `choch_wavec`,
   `impulse_fib` — последним.

## ✅ САМЫЙ ДЕШЁВЫЙ РЫЧАГ — СДЕЛАН 21.08
`scripts/strategy_preflight.py` готов и верифицирован тремя негативными тестами
(стоп ниже порога · RR ниже порога · тот же стоп у другой стратегии — все три
поймал с точной причиной). Четыре раздела: **A** четыре ключа поиска · **B** пороги
по местам с 🔴 при расхождении · **C** политика+секция стратегии · **D** прогон
синтетического сигнала через 6 живых HARD-гейтов роутера.

```
python scripts/strategy_preflight.py                      # сводка по 32 источникам
python scripts/strategy_preflight.py impulse_fib --gates --stop 2.0 --rr 3.0
```

🔑 Урок при написании: **читать конфиг ТОЛЬКО через боевой `config_loader`**.
Сырой `yaml.safe_load` дал ложную тревогу «tsl_activation_r_per_strategy мёртв» —
на деле `config_loader.py:31-44` мержит `sl_tp_engine` → `trading`, и оба пути живые.

Найдено сразу: **4 источника из 32 с расхождением ключей**, главный —
`wt_sideways` (source=`wt_sideways`, но policy.trade_mode=`sideways`): вписанный
per-strategy порог нашёл бы роутер и НЕ нашёл `trade_simulator`. Мина заряжена, ждёт.

## Чего реестр НЕ починит (не создавать иллюзий)
Гонка INSERT→mark_pending · кэш баланса · чужая позиция на (symbol, direction) ·
фактическая цена фила · `database is locked` · расхождение вселенной бэктест↔бой.
Молчаливость лечится preflight'ом и законом «отказ ОБЯЗАН логироваться с причиной».

## Риски перехода
Смена ключа с `trade_mode` на `source` двигает пороги там, где имена расходятся
(`wt_sideways`→`sideways`, `radar`, `oko_ote`). Пороги живых стратегий зафиксировать
замером ДО правки. `SourcePolicy` создаётся на каждый `submit`
(`trade_router.py:88`) — новые поля не должны читать конфиг в цикле.

## ✅ Сделано 21.08 (до реестра, точечно)
- `choch_wavec` получил все фиксы impulse_fib: mark_pending, откат при отказе биржи,
  восстановление стопа, finally, кэп по сделкам, подключение к лайфциклу (TTL 12ч).
  До этого TSL трейлил его несуществующие позиции (BITLIGHT #58333: стоп ушёл
  0.19249 → 0.15828, НИЖЕ входа шорта; восстановлен).
- Обезврежена мина: `single_tp_sources` и `rr_cap_exempt` отсутствовали в конфиге,
  работали фолбэки кода — кто первым вписал бы свой ключ, молча выбил бы обе стратегии.
- Создана секция `trading.sl_management` — код читал её (trade_simulator.py:776-780),
  но её НЕ БЫЛО; одноимённые ключи в `sl_tp_engine.sl_tp` были сиротами.

Связано: [[impulse_fib_cell_live]], [[bug_gate_lives_in_two_places]],
[[bug_source_policies_deadpath_router_off]], [[principle_reuse_not_duplication]].
