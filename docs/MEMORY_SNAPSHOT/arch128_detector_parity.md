---
name: arch128-detector-parity
description: "🔴 КРИТИЧНО: эталонные SMC-детекторы (core/smc/swing_service.py, ARCH-128) РАСХОДЯТСЯ с наивными rolling-window признаками combinator_v2, на которых майнили arch104_patterns.yaml (187 паттернов). Расхождение train/live = корень самоподтверждения (проблема ARCH-118 «один калькулятор»). Нужен ре-майнинг на эталонах + наполнение features_json эталонными признаками."
metadata:
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# ARCH-128 — расхождение эталонных детекторов с майнингом (03.06.2026)

После воспроизведения OKO-SM (эталонные SMC-детекторы в `core/smc/swing_service.py`) обнаружено:
паттерны (`config/arch104_patterns.yaml`, 187 шт) майнились на **наивных rolling-window**
признаках `tools/pattern_mining/combinator_v2.py`, которые КАРДИНАЛЬНО отличаются от эталона.

## Карта расхождений (combinator_v2 vs эталон swing_service)

| Признак | combinator_v2 (майнинг) | Эталон (ARCH-128) |
|---|---|---|
| **swing** | rolling max/min | ZigZag ATR-dev (dev=3) + защищённые уровни |
| **BOS/CHoCH** | `close>max(high[-20:])` + был BOS (L=20 окно) | ZigZag + слом ЗАЩИЩЁННОГО уровня структуры |
| **OTE** | позиция в rolling-40, зона **0.62-0.79** | импульс СЛОМА (build_ote), зона **0.5-0.79** |
| **OB** | наивный 3-свечный (close<open + 2 растущих) | структурный слом + ATR(200) фильтр + mitigation |
| **FVG** | 3-свечный гэп (порог?) | порог = mean |gap%| ВСЕХ баров ×2, close-mitigation |
| **Эллиотт** | прокси n_down (snижающиеся swing highs) | detect_elliott_impulse (точные волны 1-5 + fib + extension) |

## Почему критично
- **Train/live mismatch:** майнинг на одних признаках, live-бот считает иначе → паттерн, найденный
  на naive-CHoCH, не сработает на эталонном-CHoCH. Это корень самоподтверждения (ARCH-118 инвариант
  «ОДИН КАЛЬКУЛЯТОР»: combinator и сферы Bus = одна формула на признак).
- 187 паттернов arch104 могут быть на нерепрезентативных признаках.

## План (ARCH-129? — отдельный эпик)
1. **Привести combinator к эталону** — заменить naive-функции на вызовы swing_service (один калькулятор).
2. **Ре-майнинг** паттернов на эталонных признаках → сравнить с arch104 (какие выживут).
3. **Наполнить features_json/trade_features** эталонными признаками (наши детекторы) — чтобы будущий
   майнинг и ML шли на той же разметке, что live. → [[arch118-snapshot-decision]] ARCH-118 хранилище.
4. Связать с n_down прокси: detect_elliott даёт точную волну вместо прокси.

→ DISCUSSION 03.06.2026. Эталон: `core/smc/swing_service.py`, `docs/PRICE_PATTERNS_LIBRARY.md`.
Старое: `tools/pattern_mining/combinator_v2.py`. [[oko-sm-pine-ob-fvg]]
