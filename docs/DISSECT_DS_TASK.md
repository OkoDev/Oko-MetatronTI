# Задание DS: STRATEGY-DISSECTION — параллельный data-разбор 3 боевых стратегий

> **Модель (юзер 12.06):** DS + Claude ПАРАЛЛЕЛЬНО. **DS = data** (метрики, RR-зоны, гипотезы,
> бэктесты вариантов SL/TP). **Claude = code** (как вход/триггеры/SL/TP устроены в коде).
> Взаимный фильтр: DS-гипотезы ↔ Claude код-реальность. Итог: оптимальные решения на данных + коде.
> **Цель:** атомарно разложить, прогнать варианты, проверить гипотезы, найти оптимум.

## КОНТЕКСТ
3 стратегии = 96% потока (3 дня n=5595): **arch104 57% + ote_nested 32% + atr_change 7%**.
Вскрытие RR-зоны 2-5R (`docs/MEMORY_SNAPSHOT` research_zone_2_5r): мёртвая середина 2-5R (но VST
+1163R), SHORT +0.413 vs LONG −0.106, confluence −1.136 (не в бою), pivot_1D TP-source убыточны.
**Метрики-гигиена:** avgR + median + WR + n + sumR, data-era post-15.04, min n≥20, VST vs SIM раздельно.

---

## DS DATA-РАЗБОР + ГИПОТЕЗЫ (по стратегиям)

### 1. arch104 (57%, SL=swing_15m, TP=r2.0 фикс)
- **Метрики:** avgR/WR/sumR по RR-зонам (<2/2-3/3-5/5+) × VST/SIM. Где edge, где утечка.
- **H1 (TP-тюнинг — ГЛАВНОЕ):** TP=r2.0 попадает в мёртвую зону 2-3R. Прогнать на истории:
  r2.0 vs r3.0 vs r1.5 vs структурный (ближайший swing/pivot) vs раннер(TSL no-cap). Какой max sumR/avgR?
- **H2 (паттерн-аудит):** из 187 паттернов `config/arch104_patterns.yaml` — какие прибыльны в VST,
  какие баласт (avgR<0 на n≥20)? Список на вывод.
- **H3 (confirmation-score):** оптимальный порог (сейчас ≥3?) — avgR по порогам.
- **H4 (direction):** arch104 SHORT vs LONG (зона 2-5R показала SHORT +0.413 / LONG −0.106) — общий?

### 2. ote_nested (32%, SL=1h/4h_impulse, TP=ote:cont/pull структурный)
- **Метрики:** pull vs cont × n_down/n_up × TF (1h/4h/5m) — avgR/WR. Где OTE сильнее.
- **H1 (pull vs cont):** подтвердить pull +2.206 (контртренд) vs cont (деградирует с фазой). По n_down/n_up.
- **H2 (impulse-TF SL):** 1h_impulse vs 4h_impulse SL — какой даёт лучший R/риск.
- **H3 (вложенность):** entry-TF 5m vs 15m в HTF-OTE — оптимум (риск ×10, maxR).
- **H4 (TSL):** TSL vs no-trail+time-exit (tsl_no_trail_insight: TSL вредит на validated). Подтвердить.
- **H5 (gravity/конфлюенция на входе):** gravity100+ avgR+2.483 — работает ли для ote_nested входов.

### 3. atr_change (7%, SL=atr_trendline, TP=atr_rr_3.0 фикс — худшая −0.426)
- **Метрики:** RR-зоны × VST/SIM. atr_rr_3.0 → зона 3-5R (−0.275 худшая).
- **H1 (КОНВЕРСИЯ — ГЛАВНОЕ):** прямой вход vs вход в 5m-OTE по atr_change-триггеру
  (atr_change_ote_insight: вход в 5m-OTE = WR89% avgR+0.741 vs прямой убыток). Прогнать на истории:
  сколько atr_change-сигналов попали бы в 5m-OTE, какой avgR vs текущий прямой.
- **H2 (TP):** atr_rr_3.0 vs r2.0 vs структурный — какой лучше для atr_change.
- **H3 (factor):** влияние factor=1.25 (бой) vs 1.0 на качество смены тренда.
- **H4 (n_down ловушка):** atr_change n_down=4 = ловушка (avgR−0.904, Elliott-память). Подтвердить, фильтр.

---

## 🔴 ГРАНИЦЫ
- DS работает на **боевой read-only** (SELECT) + бэктест-скрипты на копии/истории. НЕ менять код.
- DS НЕ разбирает КОД-логику входа/триггеров (это Claude — где в коде формируется).
- Каждая гипотеза = вывод на данных (avgR/WR/n/sumR), не мнение.

## DELIVERABLE
- DS: `docs/DISSECT_<NAME>_DATA.md` на каждую (метрики + результаты H1..Hn + рекомендация на данных).
- Claude (параллельно): `docs/DISSECT_<NAME>.md` — code-разбор (вход/триггеры/SL/TP логика из кода).
- Синтез: Claude сводит DS-данные + код → оптимальное решение (как с DB взаимным фильтром).

## ПОРЯДОК
ote_nested (эталон) → arch104 (TP-тюнинг) → atr_change (конверсия). Параллельно: Claude код, DS data.
