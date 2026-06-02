---
name: audit-detectors
description: Мониторинг 4 тихих типов сигналов (confluence/anomaly/wt_b_signal/divergence) before/after рестарта. АКТИВИРУЙ на "/audit-detectors", "аудит детекторов", "тихие сигналы", "audit detectors".
---

# Audit-Detectors — тихие сигналы

Запусти: `python tools/audit_silent_detectors.py [--team]`

Сравнивает before (24ч до рестарта) / after (с последнего рестарта) для confluence/anomaly/wt_b_signal/divergence. Время рестарта — авто из `logs/llm_hooks.log`. `--team` = добавить обсуждение роя.
