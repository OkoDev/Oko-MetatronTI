---
name: project-idea-dashboard-charts
description: Идеи новых action-able чартов для дашборда — MFE captured / time-to-MFE / leak heatmap / strategy timeline
metadata: 
  node_type: memory
  type: project
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Идеи новых чартов для дашборда (отложено 26.05.2026)

**Контекст:** После D-075 (MFE Scatter с toggle SL) договорились добавить **новый** chart рядом — не заменяющий, а дополняющий. Trader сказал "все интересно! запомни, после вернемся."

**Why:** трейдеру нужны action-able визуализации, а не просто scatter с 500 точек где видно "большинство SL дают -1R" (известная вещь).
**How to apply:** при возврате — спросить какую идею делаем первой, реализовать в `web/static/index.html` + аналогичный компонент в Vue v2 (`web/dashboard/src/components/`).

## 4 идеи

### 1. MFE Captured Ratio (гистограмма)
- Для TP/TSL сделок: `exit_r / mfe_r` (сколько % потенциала захватили)
- Bins: 0-20%, 20-40%, 40-60%, 60-80%, 80-100%
- Цветовая разбивка по signal_type
- **Insight:** видно где TSL "пропускает" profit (много сделок в 20-40% bucket)

### 2. Time-to-MFE Distribution
- X: минуты от entry до достижения max MFE (`max_R_possible`)
- Y: count
- Bins: 0-30m / 30m-2h / 2h-6h / 6h-24h / 24h+
- **Insight:** если 80% сделок пик через 1-2ч → текущий 24h time-exit избыточен

### 3. MFE Leak Heatmap
- Y: signal_type (confluence, wt_b, wt_signal, atr_change, pivot_reversal, ...)
- X: mfe_r bucket (0-1R / 1-2R / 2-3R / 3-5R / 5R+)
- Color: avg exit_r (heat: красный = много пропущено, зелёный = хорошо захвачено)
- **Insight:** найдёт конкретную пару (стратегия, MFE bucket) где TSL/TP rules не работают

### 4. R per Strategy Timeline
- X: дата (rolling 7d window)
- Y: avg_R
- Линии: по каждому signal_type (несколько кривых на одном графике)
- **Insight:** покажет какая стратегия **деградирует во времени** — например, confluence avg_R падает с +0.3 до -0.4 за месяц

## Что выбрать сначала

Мой совет: **#3 (MFE Leak Heatmap)** — самый action-able, сразу видно где улучшать TSL правила. Но это самый сложный. Простейший — #1 (просто гистограмма по одному метрику).

## Связь с другими

- [[d-075-mfe-scatter-toggle]] — основной chart MFE vs Exit R, эти будут рядом
- [[arch-104-pattern-mining]] — данные для leak heatmap пересекаются с pattern catalog
