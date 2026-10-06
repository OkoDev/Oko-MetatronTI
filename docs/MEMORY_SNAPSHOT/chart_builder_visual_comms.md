---
name: chart_builder_visual_comms
description: "🖼️ chart_builder.build_signal_chart — КАНАЛ визуального общения с Егором (он визуал, читает на графиках). Использовать для показа структуры/сетапов/находок. НЕ переписывать рендер."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

**Егор 22.06: «chart_builder (build_signal_chart) СПЕЦИАЛЬНО сделан чтобы ТЫ мог общаться со мной».**

Егор — ВИЗУАЛ (читает на графиках, не в тексте/таблицах). `core/ui/chart_builder.build_signal_chart` = ИНСТРУМЕНТ моей визуальной коммуникации с ним. Когда показываю структуру/сетап/находку/направление — СТРОИТЬ ГРАФИК, не таблицу.

**Как вызвать (reuse, НЕ переписывать рендер — он настроен):**
```python
from core.ui.chart_builder import build_signal_chart
png = await build_signal_chart("GRT/USDT", tf, bars=300, wave_overlay=True)  # → bytes PNG
open(f"chart_{tf}.png","wb").write(png)   # затем Read PNG чтобы увидеть самому
```
Рисует (всё настроено): **свечи** (не линия!) + ZigZag-волна с нумерацией + **CHoCH/BOS метки** (НЕ рисовать свои «сломы» — они уже есть) + **OB-зоны** (магниты) + FVG (multi-TF) + **OTE-фиба** 0.618/0.705/0.786 + пивоты D/W + WT-панель. async, fallback на ccxt если bot=None.

**Why:** Егор «тут видно ВСЁ» — структура, направление (CHoCH/BOS), цели (OB-магниты), вход (OTE) читаются с графика. Текст/таблицы он не воспринимает так. Я ОДИН РАЗ зря переписал рендер своим (линия вместо свечей, дубль сломов) — он поправил. Рендер УЖЕ хорош.

**How to apply:** любой разбор сетапа/структуры/находки для Егора → `build_signal_chart(wave_overlay=True)` → Read PNG → описать что вижу. Связь: [[user_egor_person]] [[vision_bot_as_anchor_against_emotion]] [[strategy_truth_state]] (OKO-OTE).
