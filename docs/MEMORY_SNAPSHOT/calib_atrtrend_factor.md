---
name: calib-atrtrend-factor
description: "ATRTrend (calculate_trend): factor=1.25 в боте НАМЕРЕННО (надёжность подтверждения смены тренда), НЕ дрейф к 1.0. atr_period=43"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**ATRTrend** = `calculate_trend()` (`core/indicators/indicators.py:98`) — точная Pine Supertrend реализация. ЕДИНЫЙ источник (ARCH-18): выдаёт `trend`(±1, направление) + `trendup`/`trenddown`(полосы) + `tsl`(трейлинг-стоп). Механика: ATR(Wilder RMA) → полосы `hl2 ± factor×ATR` → храповик-трейлинг полос → flip тренда при пробое hl2 через противоположную полосу.

**Параметры (подтверждено кодом+config 11.06):**
- `atr_period = 43` — ВЕЗДЕ согласовано (код-default `indicators.py:98` И `config.yaml:30` = 43). Калибровано под OKO-SM.
- `factor`: код-default **1.0** ∥ config/бой **1.25** (`config.yaml:31`, scan_loop передаёт из config).

**🔴 factor=1.25 — НАМЕРЕННО (юзер 11.06), НЕ дрейф:**
Юзер торгует вручную на factor=1.0, но в БОТ поставил **1.25** специально: шире полосы (`hl2 ± 1.25×ATR`) → цена должна СИЛЬНЕЕ пробить → надёжнее подтверждение смены тренда («наверняка подтверждено»). Это калибровка надёжности, осознанное расхождение торговля↔бот.

**⚠️ НЕ унифицировать `factor` 1.0(код)↔1.25(config) как дрейф!** Будущий агент увидит расхождение код/config → захочет «починить» → сломает калибровку. Аналог [[duplicates_registry]] D-07/D-08 «раздельны ОСОЗНАННО, НЕ трогать».

**Нить D-08 (trend-дрейф):** `classify_v2` (regime) если пересчитает trend сам (когда колонки нет: `market_regime.py:339 calculate_trend(htf.copy())`) → возьмёт **factor=1.0** (код-default) → разойдётся с боевым 1.25. Обычно берёт ГОТОВУЮ trend-колонку (посчитана scan_loop с 1.25) → ОК. Но точка риска при отдельных вызовах.

**Связь с regime:** regime НЕ считает направление заново — берёт `trend`(±1) из этого ATRTrend ([[regime_v2_validated]], [[duplicates_registry]] D-10). Внутри classify regime отдельно использует ATR(14)/ADX(14) для HIGH_VOL+силы (сырой Wilder, НЕ калибр-43) — отдельная параметрическая точка. Подробно: [[mtf_weight_hierarchy_universal]].
