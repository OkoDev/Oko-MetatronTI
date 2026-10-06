---
name: weekly-hypothesis-forward
description: "🔮 ПЕРВЫЙ ПРОАКТИВНЫЙ СЛОЙ (13.07): недельные гипотезы от future pivots. Егор: «FUTURE PIVOTS знает уровни заблаговременно — можно прогнозировать, но мы не делаем никогда! не торгуем гипотезы». scripts/weekly_hypothesis.py (pm2 weekly-hypo, час) + weekly_pivot_watch.py (pm2 weekly-pivot, 15м): правила из ИЗМЕРЕННОЙ pivot_behavior_map, резолвинг по касаниям. Неделя W29: 65 гипотез, 30 bear_break_s1"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
---

**Сдвиг парадигмы (Егор 13.07): система всегда была РЕАКТИВНОЙ (ждёт сигнал), а пивоты — единственный
индикатор, знающий уровни ЗАРАНЕЕ (пн 00:00 вся неделя известна, не лагают, не перерисовываются).
Егор строит план недели глазом — теперь бот делает это кодом. НЕ торговля — форвард-проверка
прогнозной силы. [[pivot-behavior-map]] [[vision-bot-as-anchor-against-emotion]]**

## Конвейер (оба pm2, cron, pm2 save сделан)
1. `scripts/weekly_pivot_watch.py` (pm2 `weekly-pivot`, */15м) — читает СВЕЖИЕ 1W-пивоты из
   pivot_cache бота (reuse, НЕ считает — Егор поймал дублирование: «мы же пивоты знаем заранее,
   зачем считать ещё раз»; гард свежести period_start=текущая неделя). Пишет:
   `weekly_pivot_open` (зона открытия недели) + `weekly_pivot_touch` (первое касание S1/S2/R1/R2).
2. `scripts/weekly_hypothesis.py` (pm2 `weekly-hypo`, час) — режим=наклон P (1W vs 1W_prev из
   кэша, ноль запросов) + зона открытия → гипотеза по ИЗМЕРЕННЫМ правилам; резолвинг ЧИСТО по
   таблице касаний (что раньше: target→TARGET/STRETCH, inval→INVALID).

## 4 правила (из pivot_behavior_map, НЕ из головы)
```
BEAR+S1..P → bear_break_s1: SHORT цель S1 (натяг S2) inval R1, p=62% (S1 ломается в BEAR)
BEAR+P..R1 → bear_fade_r1:  SHORT цель S1 (натяг S2) inval R2, p=56% (R1 bounce в BEAR)
BULL+P..R1 → bull_break_r1: LONG  цель R1 (натяг R2) inval S1, p=57% (R1 ломается в BULL)
BULL+S1..P → bull_hold_s1:  LONG  цель R1 (натяг R2) inval S2, p=57% (S1 держит в BULL)
```
Таблица `weekly_hypothesis` (PK symbol+week_start): status OPEN/TARGET/STRETCH/INVALID/NONE.

## Неделя 2026-W29 (первая, стартовые данные)
61% ликвидных перпов открылись ПОД недельным P (медвежий уклон, совпал со SHORT-лентой SIM).
65 гипотез: bear_break_s1=30 · bull_break_r1=14 · bear_fade_r1=11 · bull_hold_s1=10.
Ретро-ожидание (2 дня): reach S1 21%/R1 18%/S2 5%/R2 4%; полная неделя: S1 43%/R1 39%.

## NEXT (по итогам недели)
- Воскресный скоринг: TARGET-rate по hypo_code vs prob из ретро (сбывается ли карта форвардно) —
  кандидат в forward_machine (Сфера 11 судит и гипотезы).
- Слой 2 (Егор: «исходя из волн и ВСЕХ наших данных»): конфлюэнция гипотезы со структурой 4h /
  волновой фазой / квадрантом OI — гипотеза+LTF-триггер (CHoCH len5 после касания) = метод Егора
  кодом. ⚠️ pivot_behavior_map мета-вывод: в лоб direction-pivot НЕ монетизируется (свит стопов) —
  гипотеза даёт СТОРОНУ+ЦЕЛЬ+decision-support, вход только по структуре. [[method-egor-two-scale-entry]]
