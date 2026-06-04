---
name: session-2026-05-22-arch104-live
description: "Эпохальная сессия — ARCH-104 от 15 patterns до 175 (с ARCH-105 hidden div), critical D-042 fix (ts/time index), и первая ARCH-104 сделка на BingX VST с реальным exchange order"
metadata: 
  node_type: memory
  type: reference
  date: 2026-05-22
  status: milestone
  triggers: 
    - ARCH-104 live
    - ARCH-105 hidden div
    - D-042 ts time bug
    - observer datetime index
    - первая VST сделка arch104
    - separate isolated margin
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Сессия 22.05.2026 — ARCH-104/105 в проде

## Главные milestone

1. **Pipeline ARCH-104 жив целиком** — от 0 decisions/день до 9 decisions/scan
2. **D-042 critical bug fix** — самое важное открытие дня
3. **ARCH-105 hidden div phase 1** — combinator расширен + walkforward + T7 patterns
4. **Реальные ордера на BingX VST** — #14489 APT, #14491 ZEC

## Хронология (Москва)

- 13:00-17:00: попытки понять почему decisions=0 (думали anchor coverage)
- 17:00-20:00: построили T4/T5/T6/T7 с hidden div (175 patterns в registry)
- 20:00-21:00: scan diagnostic — нашли 2 full match в isolation, но observer 0
- 21:30: **D-042 root cause found!** `_fetch_df` искал `"ts"` колонку, а `data_collector` возвращает `"time"` → нет datetime index → shift на pd.Timedelta мусор → reindex пусто → 0 matches
- 22:00: D-042 commit + restart
- 01:02 (next day): **первая VST сделка #14478 BAS** через ARCH-104
- 01:19: **первый exchange order #14489 APT** на BingX через router
- 01:26: 9 decisions / 243 пары / 1 scan
- 01:42: TSL активирован на одной из позиций (+1R achieved)

## Commits сегодня (8 штук)

- `134ee56` D-029 observer tuning (interval 600s, concurrency 4)
- `7a21aac` D-030 VST trading enable
- `6591b76` D-031 tier-2 30 patterns
- `5acbb2d` D-032 tier-2 LTF 30 patterns
- `92df4f8` D-035 include_pivots=True + D-034 persistent bounce
- `12cbe12` D-036 D2 family 34 patterns
- `7520a53` D-037 tier-4 no-bounce 30 patterns
- `5bb9776` D-038 tier-5 continuation 4 patterns
- `6591b76` D-041 ARCH-105 tier-7 hidden div 28 patterns
- **`d2eca72` D-042 ts/time observer fix (СРИТIČN!)**
- `6496e37` D-043 pandas warning cleanup
- `a2c4e01` D-044 router integration для exchange
- `f0f7841` D-045 warmup 60s вместо 600s

## D-042 — самый важный bug дня

**Root cause:** `bot/loops/arch104_observer_loop.py::_fetch_df`:
```python
if "ts" in df.columns:  # ← но data_collector возвращает "time"!
    df["ts"] = pd.to_datetime(...)
    df = df.set_index("ts")
```

`bot.data_collector.get_ohlcv` возвращает df с колонкой **`time`**, не `ts` (как ccxt). Condition false → df остаётся с RangeIndex → `_shift(df, hours)` применяет `pd.Timedelta(hours=N)` к int index → мусорный shifted index → reindex не находит matches → active_flags пустой/неполный → registry.find_matching ничего не возвращает → **decisions=0**.

**Fix:** поддержать оба формата ('ts' и 'time'), fail-fast если index не DatetimeIndex.

**Эффект:** 5+ часов 0 decisions → 9 decisions/scan через 17 минут после fix.

## Архитектурные выводы

- **ARCH-104 by design = mean-reversion** — все patterns require HTF reversal markers. На trending рынке без daily reversal молчит.
- **Hidden divergence = continuation marker** — закрывает gap для trending phases (ARCH-105)
- **`pivot_bounce_*` события — нужно persistent flag** (10 баров) для last-bar scan
- **`include_pivots=True`** обязательно в combinator для observer (default False — bug)
- **datetime index критичен** для lookahead-safe shift через pd.Timedelta

## Registry финал

- LONG: 89 patterns (15 T1 + 30 T2 + 30 T2L + 16 D2 + 15 T4 + 4 T5 + 4 T6 + 8 T7)
- SHORT: 86 patterns (6 T1 + 15 T2 + 12 T2L + 18 D2 + 15 T4 + 20 T7)
- **175 total**
- TF distribution: 1h=61, 5m=52, 15m=45, 4h=17

## Backlog (D-046 завтра)

- **Separate Isolated Margin mode** на BingX (Hedge уже есть)
- Требует closure of all positions перед switch (bingx ошибка "сначала закройте")
- Code changes: убрать "позиция уже открыта" check + uniqueize trade_mode per (det_tf, pattern_id)
- Даст **Multi-TF Scaling D-026** работающим — N независимых позиций per пара
- **Намного больше data** для оценки patterns

## Lessons learned

1. **Direct adapter test > assumptions** — когда observer молчит, протестируй adapter напрямую через ccxt в isolation. Если он работает — bug в observer pipeline, не в adapter/registry.
2. **Никогда не assume API format** — `data_collector` ≠ `ccxt direct fetch`, проверь колонки. Memory: [[feedback_no_fabricated_apis]]
3. **pandas FutureWarning игнорировать нельзя** — иногда сигнал реального bug, иногда косметика. Проверь через explicit conversion.
4. **Persistent monitor > one-shot watch** для multi-hour observation. Monitor tool с `persistent=True` — кладёт каждое event как notification.
5. **Рой даёт архитектуру, но примеры реализации требуют верификации** — `subscription_manager.get_active_subscriptions()` повторился — рой тоже выдумывает API.

## Связано

- [[feedback_no_fabricated_apis]] — D-042 как пример того что нужно grep before assumption
- [[session_2026-05-21_memory_redesign]] — предыдущая важная сессия (memory system)
- `obsidian/Team-Discussions/2026-05-21-d2-design-4h1h-htf-anchor-combinations-для-intrada.md` — D2 anchors от роя
- `obsidian/Team-Discussions/2026-05-22-arch-105-проектирование-wt-hidden-divergence-для-c.md` — ARCH-105 hidden div план
