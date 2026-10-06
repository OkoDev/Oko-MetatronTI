---
name: feedback-get-ohlcv-format-trap
description: "🔴 Формат-ловушка (30.06, била 4× подряд в SL-фиксе): data_collector.get_ohlcv() и ohlcv_cache отдают df с RangeIndex + колонкой 'time'(ms), НЕ DatetimeIndex. Код, фильтрующий df.index>ts или ждущий DatetimeIndex, молча падает (except→None). Smoke на ccxt-DatetimeIndex обманывает — тестировать на БОТ-формате"
metadata:
  node_type: memory
  triggers: 
    - get_ohlcv
    - ohlcv_cache
    - DatetimeIndex
    - формат данных
    - свечи
  type: feedback
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

**Формат OHLCV-данных в проде — источник ТИХИХ багов (30.06 бил 4 раза подряд в одном SL-фиксе).**

## Факт
- `core/infra/data_collector.get_ohlcv()` → df с **RangeIndex** + колонка **`time`** (ms epoch). НЕ DatetimeIndex. (api_engine.py: `reset_index(drop=True)`, columns=["time",...]).
- `ohlcv_cache.db` колонки: `symbol, timeframe, time, open, high, low, close, volume` (НЕ `timestamp`). symbol с префиксом `binance:`/`bingx:`.
- honest-backtest `_load`: `SELECT time ... ORDER BY time` (правильно).

## Грабли (что молча ломается)
1. `df.index > entry_ts` (Timestamp) на RangeIndex → TypeError → `except` → None → фича тихо не работает (CHoCH-перенос не срабатывал).
2. `SELECT timestamp` → no such column → `_load` None → пустой результат (reach-map дал 0 строк).
3. `detect_structure_breaks`/`find_setups_zz` на RangeIndex работают (levels=цены, не index), но `choch_ts = df.index[i]` = int, не Timestamp.

## Правило (Why: 4 итерации потеряны)
1. **Перед использованием df от get_ohlcv — нормализовать индекс**, если нужен DatetimeIndex:
   ```python
   if not isinstance(df.index, pd.DatetimeIndex) and "time" in df.columns:
       df = df.copy(); df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
   ```
2. **Smoke прод-кода — на БОТ-формате** (RangeIndex + колонка time), НЕ на `ccxt` с `set_index('ts')`. ccxt-DatetimeIndex даёт ложно-зелёный smoke (так SL-инверсия и гиганты прошли smoke, но падали в бою).
3. **debug-логи в проде скрыты** (уровень INFO) → ошибки в `except logger.debug(...)` невидимы. Для диагностики прод-фичи временно поднять до info/warning. См. [[ote_production_drift_root]].

Связь: эпопея SL-фикса ote_nested (495ee08→de5285b→867760b→d907a91) — каждая итерация падала на формате до системного smoke на бот-формате.

## 🔴 РАСШИРЕНО 21.08.2026 — ТРИ ТИХИХ НУЛЯ ПОДРЯД
Все три дали НЕ ошибку, а пустой результат — самый опасный вид отказа.

1. **Детекторы SMC ждут `RangeIndex` + колонку `time`.** Передал `DatetimeIndex` →
   `detect_structure_breaks` / `detect_order_blocks` / `detect_fvg` вернули **0, 0, 0**
   на 3000 барах BTC. Не исключение — просто пустые списки.
2. **Символы в `ohlcv_cache.db` БЕЗ суффикса**: `0G/USDT`, а не `0G/USDT:USDT`
   (последний — формат боевой БД `simulated_trades`). Захардкоженный `BTC/USDT:USDT`
   дал `read_sql` → **0 строк**, и все детекторы честно вернули нули.
3. **Два формата `created_at` в одной колонке** (`'2026-03-01 00:41:26'` и ISO с TZ):
   `pd.to_datetime` без `format="mixed"` молча вернул NaT для **53355 из 56448** записей.

🔑 **ОБЩЕЕ ПРАВИЛО: перед замером — САНИТАРНАЯ ПРОВЕРКА на одной монете.**
Напечатать: сколько строк пришло, сколько объектов вернул каждый детектор, пример
первого объекта. Ноль объектов = стоп, а не «признак не работает».
Иначе замер покажет «SMC не помогает» на ПУСТЫХ данных — и это будет ложный вердикт,
неотличимый от честного отрицательного результата.

Правильные вызовы (проверено 21.08):
```python
dd = pd.read_sql("SELECT time,open,high,low,close,volume ...")   # RangeIndex!
sbs  = detect_structure_breaks(dd, length=5)      # 188 на 4000 барах
obs  = detect_order_blocks(dd, sbs)               # принимает breaks, НЕ length
fvgs = detect_fvg(dd).all_fvgs                    # 692; возвращает FVGAnalysis
```
Причинные поля: `StructureBreak.idx` · `OrderBlock.break_idx` · `FVG.index + 2`
(index = импульсная свеча i−1, подтверждение на i).
🔴 НЕ причинные (смотрят в будущее): `OrderBlock.mitigated_idx` / `is_breaker`,
`FVG.mitigated` / `mitigation_index`.
