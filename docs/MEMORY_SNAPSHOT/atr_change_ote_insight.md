---
name: atr-change-ote-insight
description: "atr_change = ATRTrend ±1 (направление верно) но СЛЕП к OTE; вход в 5m-OTE WR89% avgR+0.741; regime-гейт снят 11.06 (тавтология, -178R)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**atr_change = ATRTrend ±1** (SHORT=−1, LONG=+1) — направление УЖЕ зашито в сигнал. Но atr_change **СЛЕП к структуре**: входит на ATR-всплеске → садится **НИЖЕ OTE-зоны** (поздно, на импульсе). Корень слабых/шумных данных (avgR+0.072 = усреднение «случайно в OTE» ∥ «вне зоны»).

**Гейт снят 11.06** (`config.yaml signal_quality.atr_change`: `allow_short_regimes` убран, `long_strength_penalty=0`): regime-гейт `[TREND_DOWN]` был **ТАВТОЛОГИЕЙ** — atr_change SHORT уже = ATRTrend−1, гейт перепроверял ТО ЖЕ направление через regime-метку + добавлял лаг ADX-силы (резал ранние −1). −178R утечки ([[arch124_regime_audit]]). `min_strength_atr_change=15` оставлен (базовый порог).

**🔴 WR89% ОПРОВЕРГНУТ (DS бэктест 14.06, `scripts/atr_ote_e3_backtest.py`, 36K сигналов 20 пар).** WR89% avgR+0.741 был на **n=9 — ФЕЙК малой выборки.** На большой PAIRED выборке (n=2'442): A (текущий entry=`ev.price`) avgR=**+0.095** vs B (mid-OTE Э3) **+0.068** → **текущий вход ЛУЧШЕ.** OTE-покрытие лишь 7%. **Полная OTE-конверсия (Э3 mid-OTE entry) НЕ улучшает, даже хуже. DEV-209 (частичный, OTE-фильтр для 15m) = ОПТИМУМ.** Э3/Э2 НЕ делать. Урок: n=9 нельзя доверять (как фейк-R [[bug_ote_sl_near_entry_r_explosion]]).

**Что РЕАЛЬНО работает (DEV-209, валидировано):** atr_change разворот −89R→+46R. 1h/4h прямой вход, 15m только в OTE-зоне (фильтр) + OTE confirmation. Драйвер = СЕЛЕКТОР (VST avgR+0.401 vs SIM −0.083), не OTE-вход. 92% чистых SL, edge реальный (не фейк-R).

**Историческое (опровергнутый дизайн, НЕ реализовывать):** `docs/PLAN_ATR_CHANGE_OTE.md` Э2 (ожидание отката) + Э3 (mid-OTE entry, SL за 1.0) — бэктест показал НЕ улучшает. regime-гейт снят 11.06 (тавтология, −178R [[arch124_regime_audit]]) — это осталось верным.

**Связи:** [[ote_nested_mtf_strategy]] (5m-вход в OTE = тот же каркас), [[regime_v2_validated]] (общий корень: структура > regime-метка), [[calib_atrtrend_factor]] (ATRTrend = источник направления), [[mtf_weight_hierarchy_universal]].
