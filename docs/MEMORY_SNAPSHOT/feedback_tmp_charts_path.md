---
name: tmp-tmp-charts
description: "Сохранять сгенерированные чарты/PNG/временные файлы в E:\\MTF BOT\\CURSOR\\crypto_volume_bot\\tmp_charts (относительно tmp_charts/), НЕ в e:/tmp/ или корень диска. Пользователь указал 02.06.2026."
metadata: 
  node_type: memory
  type: feedback
  triggers: 
    - сохранить chart / PNG / график
    - render_verify / chart_verify out
    - временный файл для визуализации
    - savefig путь
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Правило: сгенерированные графики и временные визуализации — в `tmp_charts/` проекта (`E:\MTF BOT\CURSOR\crypto_volume_bot\tmp_charts`), НЕ в `e:/tmp/` и НЕ в корень диска.

**Why:** пользователь указал 02.06.2026 — «Tmp тут а не в корне диска → E:\MTF BOT\CURSOR\crypto_volume_bot\tmp_charts». Чарты для визуальной сверки должны лежать в проекте, где он их найдёт.

**How to apply:**
1. `chart_verify.render_verify(out=...)` дефолт = `tmp_charts/...`.
2. Любой `savefig` / PNG для показа пользователю → `tmp_charts/<имя>.png`.
3. Аналитические temp `.py` могут оставаться в `/tmp` (для меня), но ВЫВОД-артефакты (графики) — в `tmp_charts/`.
