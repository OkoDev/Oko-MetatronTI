---
name: Metrics hygiene rules
description: avgR alone is dangerous — always use median+Sharpe+histogram. Dead strategies with good metrics poison decisions. Data eras must be explicit.
type: feedback
originSessionId: 8b37741a-d75d-4cf7-9a44-be6f52046c7a
triggers:
  - 'avgR в одиночку'
  - 'сравнение стратегий'
  - '''стратегия X прибыльна'''
  - 'вывод по small sample (<30 сделок)'
---
Никогда не оценивать стратегию по avgR в одиночку.

**Why:** MultiSignalStrategy имела avgR=+3.486, что выглядело как "хвостовая стратегия". SQL-анализ 18.04 показал: 180/511 сделок имели micro-SL <0.2% (артефакт до DEV-157). Три ARIA с R=+112 — один pump event 14.03. Без micro-SL: avgR=-0.348, Sharpe=-0.255. Стратегия никогда не была прибыльной.

**How to apply:**
1. Всегда считать: median_R, Sharpe, гистограмму по бакетам, top-10% contribution
2. Мёртвые стратегии (0 новых сделок) помечать в документации как DEAD, не оставлять исторические метрики без контекста
3. При крупных фиксах (DEV-157 min_sl_dist, DEV-174 TSL) — маркировать data_era, считать метрики отдельно по эрам
4. Перед любым "давайте вернём стратегию X" — проверить чистый срез без артефактов
