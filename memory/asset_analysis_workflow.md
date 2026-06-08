# Asset Analysis Workflow — цепочка анализа любого актива

> Создано: 07.06.2026, DS. Проверено на XLM/USDT.
> Для любого актива, по которому нужен всеобъемлющий анализ перед торговым решением.

## Этапы (последовательно)

### 1. WebSearch — фундаментал и новости
```bash
# Параллельный поиск по 3 направлениям:
WebSearch: "TICKER news catalysts partnerships [month] [year]"
WebSearch: "TICKER price technical analysis [month] [year]"  
WebSearch: "TICKER on-chain metrics active addresses [year]"

# Если нашлась ключевая новость — копать глубже:
WebSearch: "найденный_термин details impact"
```

### 2. Team Ask — синтез контекста проекта + новостей
```bash
python tools/team_ask.py "TICKER — всеобъемлющий анализ.
## НАЙДЕНО В СЕТИ:
[новости, уровни, ончейн]

## КОНТЕКСТ ПРОЕКТА OKO MTF:
- Стратегии (ote_nested avgR, arch104 avgR)
- Режим рынка (SHORT vs LONG преимущество)
- TSL Hybrid v3 статус

## ВОПРОС:
1. Фундаментал и катализаторы
2. Техническая картина что видит бот
3. Нарративы
4. Риски
5. План действий" --skip-meta
```

### 3. Live Price + OTE Zones — расчёт уровней входа
```bash
# Скрипт: fetch OHLCV → smc_engine.zigzag_atr → dealing range → OTE зоны
python -c "
import ccxt, pandas as pd, numpy as np, json
ex = ccxt.bingx(...)
ohlcv_1h = ex.fetch_ohlcv('TICKER', '1h', limit=200)
from core.smc.smc_engine import zigzag_atr, _zz_typed
# ... расчёт dealing range, OTE LONG/SHORT, ATR, SL/TP
# Вывод: JSON с зонами и параметрами сделки
"
```

### 4. Результат — трейдеру
```
Цена / OTE-зона / Диапазон входа / SL / TP / ATR
Структура: EMA20/50, свинги, тренд
Вердикт: ждать / входить / какой сетап
```

## Пример (XLM/USDT, 07.06.2026)
- WebSearch → DTCC partnership H1 2027 (крупнейший мандат)
- Team Ask → 7/7: фундаментал bullish, техника SHORT-доминирующая
- Live Zones → OTE LONG 0.194-0.202, цена 0.2112 → ждать откат

## Ключевые файлы проекта для контекста
- `memory/last_trade_review.md` — свежая статистика стратегий
- `memory/session_brief.md` — последние изменения
- `scripts/ote_monitor_xlm.py` — мониторинг конкретного актива (шаблон)
