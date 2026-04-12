# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

---

## [~17:30 UTC 12.04.2026] Агент: Developer — DEV-155 + DEV-156 + DEV-157

- ✅ **DEV-157:** guard в `register_trade()` — sl_dist_pct < 0.1% → skip + WARNING. config: `trading.min_sl_dist_pct: 0.1`
- ✅ **DEV-155:** `min_strength_by_regime` HIGH_VOL: 85 (было 75), + новый `min_strength_by_direction_regime` LONG_RANGE: 75. Применяется в `is_actionable()` и `register_trade_async()`.
- ✅ **DEV-156:** `core/trading/circuit_breaker.py` (Singleton) — WR<15% → +10 к min_strength на 30 мин. Loop `circuit_breaker_loop()` запускается в bot.py.
- ✅ TASKS.md (DEV-155/156/157 → ✅), PROJECT-LOG.md обновлены
- 🔄 Следующий шаг: рестарт бота → логи `[DEV-155]`, `[DEV-156]`, `[CircuitBreaker]`
- ⚠️ VerdictAggregator WT threshold 0.65→0.50 ещё не реализовано

## [~14:30 UTC 12.04.2026] Агент: Developer — DEV-87 OTE backtest v2

- ✅ Запущен `scripts/backtest_ote_mtf.py` — 5 пар, 60 дней, 304 сделки total
- ✅ SWING WR=35.1%, SCALP WR=29.2% — оба ниже порога 45%
- ✅ TASKS.md, PROJECT-LOG.md, DISCUSSION.md обновлены
- ⚠️ OTE остаётся в shadow_mode=true — производственный деплой нецелесообразен
- 🔄 Ожидаем: ARCH решает Step2 фильтры (4h-only? CHoCH-only? exclude BTC?)
- Лучший subgroup: 4h primary WR=37.7%, CHoCH WR=37.8%, ETH WR=45.5%

---

## [~10:00 UTC 12.04.2026] Агент: Architect — Фильтры WR + Circuit Breaker

- ✅ Прочитал аудит TRADER (WR=8.4% за 07-10.04, диагноз: whipsaw рынок)
- ✅ Принял решения по B/C/D: HIGH_VOL→85, LONG_RANGE→75, Circuit Breaker
- ✅ Создал DEV-155 + DEV-156 в TASKS.md с полными спеками
- ✅ Ответил в DISCUSSION.md с приоритетами на 12.04
- 🔄 Ожидаем: DEV реализует DEV-155→DEV-156→рестарт
- ⚠️ DEV-153 (VerdictGate): держать выключенным по рекомендации TRADER до WR > 30% за 3 дня подряд

---

## [12:00 UTC 12.04.2026] Агент: Architect — DUAL_TSL стандарт

- ✅ Сделано: Бэктест 5564 сделок → DUAL_TSL 10%/90% = лучший вариант (+847R)
- ✅ DEV-124 закрыт как ошибочный (нечестное сравнение периодов)
- ✅ config.yaml: `trend_strategy_type: DUAL_TSL`, `tp1_fix_pct: 10`
- ✅ Задокументировано: PROJECT-LOG.md, memory/project_dual_tsl_strategy.md
- ⚠️ Апрель 2026: все стратегии в минусе — плохой рынок, не баг стратегии
- 🔄 Следить: первые DUAL_TSL сделки в БД (`strategy_type=DUAL_TSL`), логи `[regime_strategy] TREND_UP: DUAL_TP → DUAL_TSL`

---

## [11.04.2026 02:30 UTC] Агент: Developer — Куб Метатрона ПОЛНАЯ РЕАЛИЗАЦИЯ

### Что сделано:

**Куб Метатрона — все 13 сфер подключены к шине:**

1. **PairContextBus расширен** (`core/context/pair_context.py`):
   - PairState: 38 полей (все 13 сфер)
   - SphereEvent: 22 типа событий
   - Auto-update PairState при publish()
   - Event log для диагностики (последние 200 событий)

2. **Новые детекторы** (`core/signals/htf_detectors.py`):
   - TrendChangeDetector — смена тренда на 1h → EventBus
   - WTCrossHTFDetector — кросс WT в OB/OS на 4h/1d → EventBus
   - EVENT_PRIORITY: +3 новых триггера (trend_change_1h, wt_cross_4h, wt_cross_1d)

3. **scan_loop.py wiring** — каждый детектор публикует в bus:
   - Anomaly → ANOMALY_DETECTED
   - WT signal → SIGNAL_DETECTED
   - Confluence → SIGNAL_DETECTED
   - Divergence → DIVERGENCE_FOUND
   - Regime → REGIME_UPDATED (+ reversal_mode)
   - WT snap → WT_SNAP_UPDATED (все TF)
   - Pivot snap → PIVOT_SNAP_UPDATED
   - BTC macro shock → CROSS_MARKET

4. **WsFeed → bus** — TICK_PRICE (throttled 1/10 tick)

5. **Exit Manager → bus** (`trade_simulator.py`):
   - POSITION_CLOSED при close_trade()
   - TSL_MOVED при движении TSL
   - TP1_HIT при частичном TP

6. **PostTradeAnalyser → bus** — CASCADE_UPDATED, OTE_ZONE_SET

7. **NarrativeBuilder** (`core/intelligence/narrative_builder.py`) — читает ПОЛНЫЙ PairState:
   - Факторы из всех сфер: WT snap, cascade, divergence, pivot, anomaly, BTC
   - spheres_used: считает сколько сфер дали данные
   - Публикует NARRATIVE_BUILT в bus

8. **SphereRegistry** (`core/context/sphere_registry.py`) — Сфера 12:
   - Подписан на все 22 типа событий
   - health_check() → статус каждой сферы (OK/STALE/DEAD)
   - summary_text() для /status

9. **Mesh-связность** (`bot/core/bot.py → _wire_cube_subscriptions()`):
   - 8 подписок между сферами
   - Сфера 3 ← regime_updated, Сфера 6 ← wt_snap_updated
   - Сфера 9 ← signal_detected, Сфера 10 ← divergence + pivot
   - Сфера 12 ← все

10. **position_sync.py** — фикс бага ложных exit_price:
    - Sanity check: SL с R>3 → заменяем на SL цену
    - TP с R<-1 → заменяем на TP цену
    - EXPIRED с R>10 → заменяем на SL цену

### Известные проблемы:
- ⚠️ 90 OPEN: 42 VST + 48 SIM-only (SIM-only by design)
- ⚠️ NEAR #5795 и ещё ~10 сделок: position_sync использовал текущую цену вместо реального exit → фикс выше
- ⚠️ DUSK/USDT R:R=26.8 — нет записи о сделке в логе (возможно min_strength фильтр)

### Файлы изменены (НЕ закоммичены):
- `core/context/pair_context.py` — полный Shared Context Bus
- `core/context/event_bus.py` — +3 EVENT_PRIORITY
- `core/context/sphere_registry.py` — НОВЫЙ
- `core/signals/htf_detectors.py` — НОВЫЙ
- `core/intelligence/narrative_builder.py` — полный нарратив из всех сфер
- `core/trading/post_trade_analyser.py` — CASCADE/OTE publish
- `core/trading/trade_simulator.py` — POSITION_CLOSED/TSL_MOVED/TP1_HIT publish
- `core/infra/ws_feed.py` — TICK_PRICE publish
- `core/exchange/position_sync.py` — sanity check fix
- `bot/core/bot.py` — HTF detectors, SphereRegistry, _wire_cube_subscriptions
- `bot/loops/scan_loop.py` — все детекторы → bus publish
- `docs/ENCYCLOPEDIA.md` — статус Куба 12/12 сфер

### Следующий шаг:
- Рестарт бота → проверить логи [Cube] и [SphereRegistry]
- Через 30 мин: `bot.sphere_registry.summary_text()` — все 12 сфер OK?

---

## [12.04.2026 ~16:30 UTC] Агент: TRADER — TR-001 + TR-007
- ✅ TR-001: разбор БД 12.04, WR тренд 8%→17% (улучшение, но <30%)
- ✅ TR-007: VerdictAggregator — verdict_would_block не пишется в features_json (0 записей). Нужна задача DEV.
- ✅ Баг-репорт: ASR R=-450, AKT TP с R=-6.56 — аномальные R_multiple, нужен sanity clamp [-15,+15]
- ✅ EventBus: все Full CALL → None (ожидаемо), BTC 4h gate работает в shadow TREND_DOWN
- ✅ Согласен с решениями ARCH по DEV-155 + DEV-156
- ⚠️ SHORT HIGH_VOL: 3 дня подряд avgR<-0.7, WR=5% — DEV-155 критически нужен
- ⚠️ PIXEL SHORT HIGH_VOL открыт (str=71) — не пройдёт DEV-155 порог 85

## [10.04.2026] Агент: TRADER — SQL-разбор + рекомендации (TR-001, DEV-153)
- ✅ Ответил на DEV-153: 426 сделок с wt_snap (389 закрытых)
- ✅ WR benchmark: нейтральный период 01-03.04 = 38.7% (vs 8.4% за 07-10.04)
- ⚠️ WR=8.4% (07-10.04) — рыночный контекст (post-crash whipsaw)
