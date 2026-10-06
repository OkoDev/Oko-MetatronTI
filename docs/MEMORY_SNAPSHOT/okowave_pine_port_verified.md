---
name: okowave_pine_port_verified
description: "Волновой детектор бота перенесён в Pine (docs/reference/OkoWave_v1.pine), сверен запуском на 500 барах TW; в TW сохранён под чужим именем-копией"
metadata: 
  node_type: memory
  type: project
  originSessionId: b9292ecd-40bf-480f-b583-11c47310bf19
  modified: 2026-09-08T04:03:34.984Z
---

# 🌊 OKO WAVE — ВОЛНОВОЙ ДЕТЕКТОР В PINE (08.09.2026), СВЕРЕН ЗАПУСКОМ

`docs/reference/OkoWave_v1.pine` — Pine v6. Порт: `oko_sm_engine.run_structure` (два
масштаба 50/5) · `current_leg` · признаки `leg_*` под ИМЕНАМИ КОЛОНОК МАТРИЦЫ
(`matrix_full.wave_features`) · `wave_service`: `n_down/n_up` на трёх ТФ, `_htf_dir`,
`_detect_phase`, `_is_recount`. Круг замкнулся: `oko_sm_engine` сам был портом
[[smc_canon_engine_is_oko_sm]] из `OkoSM_v163.pine`, надстройки в Pine не было никогда.

**🔑 Требование Егора: оба слоя length рабочие.** В Python нога строится только на старшем
масштабе, младший даёт один `leg_minor_breaks`. В Pine у младшего слоя своя структура:
свои trail, своя нога, поля `minor_leg_*`. Это РАСШИРЕНИЕ — с матрицей сверяется только слой 50.

## ✅ Сверка запуском, не «на глаз»

500 баров BINGX:SEIUSDT.P 1h выгружены из TW и прогнаны кодом бота. Совпали до 5-го знака:
`trend`/`itrend`, `leg_dir`, `leg_span_bars` 73, `leg_age_origin` 87, `leg_age_extreme` 14,
`leg_amp_pct` 10.05405, `leg_amp_atr` 7.41992/93, `leg_speed_atr` 0.10164,
`leg_minor_breaks` 5, `leg_minor_per100` 5.74713.
Разошлись двое, оба объяснены и оба не дефект: `leg_pos` — единственное поле от ЖИВОЙ цены;
`n_up` 2 против 0 — вход «только закрытый бар» (пивот 494 подтверждается на баре 499).

## 🌊 РАЗВОЛНОВКА 1-2-3-4-5 — ЭТО ДРУГОЙ ДЕТЕКТОР, И ОН ТОЖЕ ПЕРЕНЕСЁН

Егор: «а где разволновка? я вижу только одну ногу!». Ответ: `oko_sm_engine` волн НЕ
размечает вовсе — он даёт одну ногу. Разметка живёт в ДРУГОМ модуле, `core/smc/smc_engine.py`:
`zigzag_atr(11, dev)` + `detect_elliott_impulse` (hard-правила R1/R2/R3, extension волны 5,
фибо w2/w4/w3 → textbook) + `detect_elliott_mtf(devs=3/5/8)`. В матрицу он входит как
`etl_elliott` (`elliott_bull_impulse` / `bear` / `textbook`), и на нём стоит замер
[[elliott_canon_beats_my_proxy]]. Перенесён в `docs/reference/OkoElliott_v1.pine`.

**Итог в TW — ОДИН объединённый индикатор** `docs/reference/OkoWaveElliott_v1.pine`
(«OKO Wave — структура и нога», короткое имя «OKO WE»): блок 1 — структура+нога,
блок 2 — разволновка тремя масштабами. Объединять пришлось из-за лимита: у аккаунта
**ровно 30 скриптов**, новые слоты молча не создаются (pine_new, «Создать новый» и
копирование возвращают успех, но слот не появляется, а Ctrl+S перезаписывает текущий —
так я дважды затёр собственный скрипт). Чтобы разнести на два индикатора, сначала
удалить любой ненужный скрипт.

🔑 На 1h канон срабатывает РЕДКО (последний импульс dev5 завершился 422 бара назад) —
это свойство строгих правил, а не поломка. На 15m/5m разметка плотная.

## 🔴 Что осталось незакрытым

1. **Детектор дивергенций не портирован** — `has_div` подаётся внешним `input.source`,
   поэтому фаза `wave5_final` недостижима без подключения стороннего индикатора.
2. **ATR:** Python `ewm(alpha=1/43)` против Pine `ta.rma(43)` — расходятся первые ~43 бара.
3. **Разволновка сверена только глазами** (волны рисуются, textbook отмечается), запуском
   против Python — НЕТ. Числовая сверка сделана только для блока 1.

## ⚡ Как править этот скрипт в TW (окно редактора — отдельное)

MCP `pine_set_source` работает, но 47 КБ гонять через контекст дорого. Быстрее:
`Set-Clipboard` файлом → клик в область кода → `ui_keyboard` Ctrl+A, Ctrl+V →
`pine_smart_compile`. 🔴 После компиляции индикатор НА ГРАФИКЕ не обновляется —
надо удалить study и добавить заново. Кнопки редактора не видны `ui_click`, но доступны
из главного окна через `document.querySelector('.publishButtonTitle-ddmSLPrc')` → 6 раз
`parentElement` → кнопки тулбара (первая = меню имени: Переименовать/Создать/Открыть).

Связано: [[leg_span_bars_can_be_negative]] · [[wave_leg_1h_long_candidate]] ·
[[smc_canon_engine_is_oko_sm]] · [[tradingview_cdp_store_launch]] · [[oko_sm_engine_ported]]
