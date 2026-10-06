---
name: ote_engine_full_map
description: ПОЛНАЯ КАРТА кормильца ote_nested — что видит/знает/как решает/на чём едет. Секрет = конфлюенция во времени+пространстве (Куб). FVG+OB+SC* +1.23 vs OB solo +0.13
metadata: 
  node_type: memory
  type: project
  originSessionId: 01a80823-46cc-4251-9bdf-bf45da105c68
---

🚗 **ПОЛНАЯ КАРТА ote_nested (18.06, скан перед раскруткой).** Конфиг: `config/ote_setups.yaml`, движок `core/smc/ote_signal_generator.py`.

**1. ВИДИТ:** MTF — HTF (1h/4h/1d) строит OTE-зону (фиб 0.5-0.79), LTF (5m/15m/1h) триггер. Структура: zigzag→импульс→OTE; CHoCH length=5. Зональные триггеры: FVG/OB/EQL/SC/SC* (приоритет SC*>EQL>OB>FVG).

**2. ЗНАЕТ:** 6 подтверждений (нужно ≥3): div/wt_cross/vol/liq_sweep/fvg_held/atr. Волна elliott_n_down/up + phase-gate (cont конец волны=блок, pull без HTF=блок). DS-вертикаль div: hidden 1h + regular 15m.

**3. РЕШАЕТ:** 18 сетапов (tier1/2/3, веса 1.0/0.6/0.3). min_confirmations=3, min_runner_rr=2.0. SL за свечу реакции +buf 0.15% (тугой ×10). TP1 +1R 50%, runner pull→OTE / cont→HTF-target.

**4. ЕДЕТ НА (честный R):** КОНФЛЮЕНЦИЯ триггеров — FVG+OB+SC* **+1.232** vs FVG solo +0.401 vs OB solo +0.128. SC* = маркер топа. + тугой SL<0.6% +0.90, SHORT над уровнем +1.13, pull>cont, tier1>tier2, чемпион 4h_1h_pull.

**🔑 СЕКРЕТ:** конфлюенция во ВРЕМЕНИ (HTF-контекст×LTF-триггер×волна×подтверждения) и ПРОСТРАНСТВЕ (HTF-зона×стек триггеров в точке) + асимметрия тугого SL. Куб Метатрона: каждый совпавший слой множит вероятность. Едет на СХОЖДЕНИИ многих, не на одном.

**⚠️ ПРОБЕЛЫ (рост):**
- 🔴🔴 **ДИВЕРГЕНЦИИ НЕДОКРУЧЕНЫ — 2 МЁРТВЫХ ПРОВОДА (18.06):**
  1. **RSI-вертикаль:** `self.ds_patterns` (ote_signal_generator.py:110) ЧИТАЕТСЯ но НИГДЕ не используется. DS-вертикаль hidden 1h + regular 15m = **+1.84R WR96%** лежит мёртвым грузом. Движок берёт только простой `rsi_div_regular OR hidden` на ОДНОМ ltf (стр.233).
  2. **WT-дивергенции:** движок ВООБЩЕ не читает wt_div (только `wt_cross` = пересечение, не дивергенция!). А config best_long = `bull_fvg + wt_div_bull_hidden_15m` = **+1.84R WR100%**.
  ✅ **Флаги ГОТОВЫ в combinator_core.py:520-547** на ЛЮБОМ ТФ: `wt_div_bull/bear_{regular,hidden}_{tf}` + `rsi_div_bull/bear_{regular,hidden}_{tf}`. Подключение дёшево, но движок=критичен → ТОЛЬКО через бэктест-стенд.
  ⚠️ Готового стенда НЕ было: `backtest_ote_mtf.py` = СТАРЫЙ `detect_ote_signal` (ARCH-53).
  ✅ **ШАГ 0 СДЕЛАН (18.06): стенд построен и ВАЛИДИРОВАН.** `e:/tmp/ote_stand.py` — walk-forward на parquet через ТОТ ЖЕ `OTESignalGenerator` + simulate exit (tp1+1R 50%/runner SL→BE/SL, без TSL). Результат: 164 сделки (8 пар/14дн), avgR=**+0.889** vs БД +0.75 (стенд чуть оптимистичнее=упрощ.exit), pull+0.958>cont+0.848 СОВПАДАЕТ с реальностью. Движок отрабатывает на истории как в проде. Блокер: generate дорог (zigzag каждый бар) → для полной статы нужна оптимизация (предвычислить HTF-зоны). Для A/B (ШАГ 1) хватает — относит. разница нивелирует оптимизм.
  ✅ **ШАГ 1 СДЕЛАН (18.06): A/B на стенде → ВЕРТИКАЛЬ РЕДКА, не главный рычаг.** baseline 164 сделки +0.889. RSI-вертикаль (hidden_1h+regular_15m) = **n=0**: детект работает (rsi_hid ~10% баров, reg ~5%), но СОВПАДЕНИЕ двух div в момент входа ≈0.5-1% → на 164 FIRE = 0 (статистически ожидаемо). Research +1.84R верен, но набран на тысячах входов (DS-318 n=67-353) → вертикаль = РЕДКИЙ премиум на ~1% сделок, НЕ удвоит общий edge. WT-div намёк +0.302 (n=4 шум). 🔴 RSI-div 15m SOLO даже ВРЕДИТ (−0.407, n=21) → текущий div-confirmation в движке под вопросом.
  **🔑 ПЕРЕФОКУС Этап 2 (стенд уберёг от слепой ставки на вертикаль):** главные рычаги = ЧАСТЫЕ+доказанные: (1) тугой SL +0.90R [[ote_tight_sl_validated]]; (2) конфлюенция триггеров FVG+OB+SC* +1.23 vs solo +0.13; (3) pull/tier1. Вертикаль/WT-div — премиум на малой доле, не game-changer. ПРИНЦИП: ote=ВСЁ → тесты до движка (стенд `e:/tmp/ote_stand.py` с A/B готов).
- `zigzag_params` per-TF: только 1h задан (depth8/dev2), 5m/15m/4h/1d=NULL → OTE-зоны дефолтом, могут врать. TODO собрать у юзера OKO-SM Waves настройки.
- confirmations логирование включено сегодня → через дни вес div и каждого.

Связь: [[ote_tight_sl_validated]], [[ote_nested_mtf_strategy]], [[signal_health_map_18jun]], [[project_confluence_principle]], [[principle_log_signal_components]].
