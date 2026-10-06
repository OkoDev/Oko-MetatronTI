---
name: cont_setups_honest_exit_diagnosis
description: "Честный (post-fake-R-cutoff) разбор cont_1h_5m_cont — вход LONG хорош/SHORT мёртв, выход течёт от SYNC-GAP БД↔биржа SL"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0b9885d0-84da-4125-92df-2c24b01a41a7
---

# cont_1h_5m_cont — честный разбор входа+выхода (20.06.2026)

Контекст: юзер «по входам самый большой вопрос к cont_1h_5m_cont» + «не трогать вход — чинить выход» + «нужна отсечка по fake-R, до неё анализ не стабилен».

## 🔴 ОТСЕЧКА FAKE-R ПЕРЕВОРАЧИВАЕТ ВЫВОД
Отсечка: `closed_at >= 2026-06-19T06:00:00 UTC` (после 02beb18 — последний positionID R-фикс + рестарт) + санити-фильтр R∈[−1.5, MFE+0.2]. БД R до неё отравлен phantom-exit ([[bug_phantom_exit_resolve]]).

| срез | avgR грязный | avgR ЧЕСТНЫЙ | вывод |
|---|---|---|---|
| cont_1h_5m **LONG** | 0.375 | **0.778** WR63% %≥1R 54% | **хороший вход!** |
| cont_1h_5m **SHORT** | 0.116 | **0.076** medR=0 MFE=0.85 capture9% | **мёртв** (exit не спасёт — нет профита ловить) |
| pull SHORT | 0.88 | **1.2-1.36** WR70-85% | чемпион |
| pull LONG | 0.67 | 0.70 medR−0.05 | слабый |

**Закон направления:** LONG живёт у **cont**, SHORT живёт у **pull**. Крест (cont SHORT, pull LONG) = смерть денег. cont_1h_5m = доминирующий объём (n~280 VST/период).

## 🔴 ВЫХОД cont LONG ТЕЧЁТ — корень SYNC-GAP БД↔биржа (НЕ настройка трейла)
Когорта дошедших MFE≥1R (VST-only, n=77): CAPTURE 60% от MFE. `SL`-ярлык = трейл-выходы +2.2R (движок compute_hybrid_tsl РАБОТАЕТ когда доезжает). 🔴 **84 РЕАЛЬНЫХ VST-ордера (acc1+acc2, real orderId, 0 paper) → статус EXPIRED** при MFE до 4.6R, R от реального WS-fill (give-back реальный).

**Путь EXPIRED:** `exec_ws_integration.py:146` `_sync_close_async` — WS видит pa=0 → default `status="EXPIRED"`, REST `_resolve_exit` не классифицирует ордер → статус остаётся EXPIRED, R от ws_exit_price (честный). position_sync реклассифицирует EXPIRED→TP/SL/TSL по P&L (стр.636), но WS-путь 2b — нет.

**Улика sync-gap:** be_activated=1 у **71/84**, tsl_activated лишь у **6/84**, при этом **39% закрылись R<0**. Если BE реально двигает биржевой SL в entry+0.1% — убытков быть не должно. Значит BE/трейл = решение в БД, но **на биржевой SL не доезжает** → биржа держит исходный SL, раннеры схлопываются.

## ВЕРДИКТ / ПЛАН
- Вход cont LONG чинить НЕ надо (0.78R). SHORT cont exit-фиксом не спасти (MFE<1R). Юзер: вход не трогаем.
- Выход = **CUTOVER territory** ([[exec_sim_split_epic]], [[exec_ws_vst_userdata_proven]]): (a) запись — Execution Sphere close-applier классифицирует по o.rp (не REST) → нет EXPIRED-мислейбла + честный R; (b) реальный give-back — SL/трейл должен идти через ЕДИНЫЙ путь Sphere.adjust_sl что реально кладёт на биржу. Текущий дуал-путь (DB-флаг be ∥ tsl_updater placement) течёт.
- NEXT-проверка: грепнуть tsl_updater — реально ли place/trail биржевого SL для OTE-сделок, или флаг be ставится без биржевого ордера.
- TP1 отсутствует (0 TP-выходов) — далёкая HTF-цель почти не берётся.

Связь: [[ote_nested_edge_diagnosis]] [[bug_phantom_exit_resolve]] [[exec_sim_split_epic]] [[feedback_data_era_first]]
