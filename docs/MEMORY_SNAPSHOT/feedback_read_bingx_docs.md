---
name: Read BingX API docs before diagnosing exchange behavior
description: For any task touching exchange (order types, stopPrice, positionSide, API codes) — first consult official BingX API docs, don't guess from code or symptom
type: feedback
originSessionId: 92fc13a1-42d6-462d-b62f-7160951a4a09
triggers:
  - 'BingX'
  - 'ccxt'
  - 'order type'
  - 'stopPrice'
  - 'positionSide'
  - 'exchange error'
  - 'VST / LIVE поведение биржи'
---
При любой задаче касающейся биржи (BingX API — ордера, типы, параметры, error codes, поведение endpoint'ов) — **первым делом** сверяться с официальной документацией BingX.

**Why:** 19.04.2026 при расследовании "исчезновения STOP-LIMIT" я построил ложную гипотезу "BingX VST не сохраняет STOP-LIMIT", хотя ордера сохранялись. Реальный баг был в нашем коде (`update_sl` фильтровал только `STOP_MARKET`, пропускал `STOP` → накопление). Пользователь принёс выдержку из BingX docs — это переосмыслило диагноз. Час потрачен на неверную гипотезу, пока не прочитана документация биржи.

**How to apply:**
- Задача упоминает BingX / ccxt / биржевой API / VST / order type / stopPrice / positionSide → **до** grep'а по коду или построения гипотез открыть/запросить официальные docs:
  - BingX Swap v2 API: https://bingx-api.github.io/docs/
  - Order types, error codes, endpoint структуры — берём оттуда
- Если docs недоступны — явно сказать пользователю и попросить выдержку, НЕ строить гипотезы про "биржа сломана / не поддерживает".
- Перед тем как обвинить биржу в нестандартном поведении — проверить, что **наш** код посылает корректные параметры согласно docs.
