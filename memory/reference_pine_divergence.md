---
name: pine-divergence-algorithm
description: Эталонный Pine Script алгоритм расчёта дивергенций (Divergence for Many Indicators v4 by LonesomeTheBlue). Используется как reference для переписывания combinator_v2.py (DEV-233).
metadata:
  type: reference
---

# Эталонный Pine Script алгоритм дивергенций

**Источник:** "Divergence for Many Indicators v4" by LonesomeTheBlue (@version=4)
**Сохранён:** 29.05.2026 — для переписывания combinator_v2.py (DEV-233)

## Ключевые параметры
- `prd=5` — Pivot Period (prd баров подтверждения с каждой стороны)
- `source="Close"/"High/Low"` — источник для пивотов цены
- `maxpp=10` — максимум пивотов для проверки
- `maxbars=100` — максимум баров для поиска
- `dontconfirm=false` — ждать подтверждения закрытием

## Алгоритм

### 1. Пивоты (реальные структурные)
```pine
ph = pivothigh(source == "Close" ? close : high, prd, prd)
pl = pivotlow(source == "Close" ? close : low, prd, prd)
```
Хранит последние 20 пивотов в массивах ph_positions/ph_vals/pl_positions/pl_vals.

### 2. Поиск бычьей regular (cond=1) / медвежьей hidden (cond=2) дивергенции
```pine
positive_regular_positive_hidden_divergence(src, cond):
  startpoint = dontconfirm ? 0 : 1  // ждать подтверждения
  for x = 0 to maxpp-1:
    len = bar_index - pl_positions[x] + prd
    if pl_positions[x]==0 or len>maxbars: break
    if len > 5 and condOk:
      // trendline validation — линии не должны пересекаться
      slope1 = (src[sp] - src[len]) / (len - sp)
      slope2 = (close[sp] - close[len]) / (len - sp)
      for y = 1+sp to len-1:
        if src[y] < virtual_line1 or close[y] < virtual_line2:
          arrived = false; break
      if arrived: divlen = len; break
```

### 3. Типы дивергенций
- **cond=1 в pos_function:** bull regular — price LL + indicator HL
- **cond=2 в pos_function:** bear hidden — price HL + indicator LL  
- **cond=1 в neg_function:** bear regular — price HH + indicator LH
- **cond=2 в neg_function:** bull hidden — price LH + indicator HH

### 4. Рисование линий — по low/high (не close)
```pine
y1 = source=="Close" ? close[divlen] : (bull ? low[divlen] : high[divlen])
y2 = source=="Close" ? close[sp]     : (bull ? low[sp]     : high[sp])
```

## Критические отличия от combinator_v2.py

| Аспект | Pine (эталон) | combinator_v2 (текущий) |
|---|---|---|
| Пивоты | `ta.pivothigh/low(prd,prd)` — реальные | `argmin(lo_w)` — минимум скользящего окна |
| Поиск | До 10 пивотов назад (maxpp) | Только 1 "первый минимум" в окне |
| Trendline | Проверяет что линии не пересекаются | Нет проверки |
| Окно | До 100 баров (maxbars) | Только 14 баров |
| Персистентность | Нет (пересчитывается каждый бар) | Rolling 10 баров (флаг живёт 10 свечей) |
| Подтверждение | Ждёт закрытия свечи (startpoint=1) | i-1 (тоже закрытый бар) |

## ✅ РЕАЛИЗОВАНО (DEV-233, 29.05.2026) — source="Close"

`combinator_v2.py` переписан на pivot-based:
- `_pivot_indices(arr, prd=5, is_high)` — реальные пивоты close.
- `_calc_divergence(close, osc, prd, maxpp=10, maxbars=100, persist=3)` — **пивот-к-пивоту**.
- Всё по close. Trendline non-intersection по обеим линиям. Флаг на баре `idx_правого_пивота + prd`.
- **Задержка подтверждения prd=5 баров** (фундаментально, как Pine dontconfirm=false).
- Частота 0.8-2.5% баров. Имена флагов сохранены (bull_div, bear_div, wt_div_*, rsi_div_*_hidden).
- ⚠️ Бэктест паттернов считался на СТАРОМ алгоритме → нужен ретробэктест (метрики 72 5m-паттернов с div-якорями могут быть невалидны).
