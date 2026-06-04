---
name: backtest-lookahead-bug
description: "При MTF backtest'е reindex HTF→LTF через ffill даёт lookahead bias — HTF флаги становятся доступны на LTF до закрытия HTF свечи. Фикс — сместить HTF индекс на конец периода"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Lookahead bias при MTF reindex

## Что это

`pandas.resample("4h")` создаёт индекс с timestamp **начала** периода (например 04:00).
`close` этого бара = последняя цена в 07:59.
Если флаг (например `bear_bos_4h`) рассчитан по close → значение известно только в 07:59.

При `flags_4h.reindex(df_1h.index, method="ffill")`:
- 1h бар 05:00 получает значение 4h бара 04:00 → значение из 07:59
- **Lookahead на 3 часа**

## Симптомы в данных

Backtest даёт нереально хорошие результаты:
- WR > 90%
- avgR > +1.5 при TP=2R
- Все top-паттерны включают HTF факторы (`bos_4h`, `atr_down_4h`)

## Фикс

Сместить индекс HTF на конец периода ДО reindex:

```python
f_4h_raw = compute_flags(df_4h, "4h")
f_4h_raw.index = f_4h_raw.index + pd.Timedelta(hours=4)  # на close
f_4h = f_4h_raw.reindex(df_1h.index, method="ffill").fillna(False)

f_1d_raw = compute_flags(df_1d, "1d")
f_1d_raw.index = f_1d_raw.index + pd.Timedelta(days=1)
f_1d = f_1d_raw.reindex(df_1h.index, method="ffill").fillna(False)
```

## Why

19.05.2026: первая версия SMC combinator показала топ-1 паттерн SHORT с WR=96.7%, avgR=+1.888 (n=454). Это слишком хорошо — крипта так не работает. Расследование показало lookahead.

## How to apply

При любом MTF backtest'е через pandas — ВСЕГДА смещать индекс HTF на конец периода перед reindex'ом. Альтернатива — `shift(1)` на HTF DataFrame до reindex.

Также проверять live-side: в live боте `event_bus` публикует флаги по `analyze_smc(df_tf)` на закрытии каждого бара — там нет проблемы. Но при бэктесте на исторических данных через resample — есть.
