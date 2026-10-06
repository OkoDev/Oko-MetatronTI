---
name: calib-choch-length5
description: "🔴 КАЛИБРОВКА detect_structure_breaks length под эталон OKO-SM: default length=50 СЛЕПНЕТ на свежих разворотах (лаг свинга length баров), length=5 = эталонный pivot Pine (CHoCH верный, крупные BOS на месте). Сверено визуально на XLM 5m 04.06. Движок/разворотная ветка/LTF-триггеры ОБЯЗАНЫ использовать length=5, не дефолт."
metadata:
  node_type: memory
  type: feedback
  triggers:
    - detect_structure_breaks / CHoCH / BOS / structure break
    - length / pivot / swing подтверждение
    - разворотная ветка / LTF-триггер / live генерация сигналов
    - сверка структуры с OKO-SM / TradingView
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# Калибровка length для detect_structure_breaks (эталон OKO-SM)

**Сверка XLM 5m 04.06** (live BingX + график vs пользовательский OKO-SM Pine):
`detect_structure_breaks(df, length=N)` — `length` задаёт масштаб свингов. Свинг
фиксируется через `length` баров после экстремума (`_swings_luxalgo`: `i-length`).

| length | поведение | вердикт |
|---|---|---|
| **50 (default)** | свинги редкие/крупные, свежий CHoCH с лагом ~50 баров (4ч на 5m) | ❌ СЛЕПНЕТ на разворотах |
| **5** | CHoCH верный, крупные BOS на месте — совпал с OKO-SM | ✅ ЭТАЛОН |
| 3 | + ловит микро-BOS, но больше шума | опц. |

**Why:** на свежем V-развороте default length=50 не видит CHoCH (свинг не «вызрел»).
Это НЕ лаг рынка — CHoCH фиксируется на close-пробое сразу (пользователь прав).
Корень — крупный length у нас vs малый pivot Pine. Чуть не наврали (`br[-1]` показал
старый bear-слom как «текущий»). Глаз/чарт поймал ошибку дефолта → правило [[feedback-chart-sync-etalon]].

**How to apply:**
1. Движок генерации, разворотная ветка, LTF-триггеры → `detect_structure_breaks(df, length=5)`.
2. НЕ брать `br[-1]` слепо — это последний слом по ВСЕЙ истории, может быть старый.
   Для «текущего» — фильтровать по свежести (idx >= n - окно).
3. Прописано в `config/ote_setups.yaml` → `execution.choch_length_ltf: 5`.
4. ДИВЕРГЕНЦИЯ опережает CHoCH на развороте (15m bull_regular была ДО bull-CHoCH) →
   ранний триггер = дивергенция, подтверждение = CHoCH(length=5).

Связь: [[ote-nested-mtf-strategy]] (движок), [[feedback-chart-sync-etalon]] (сверка),
[[reference-oko-sm-indicator]] (эталон Pine). ARCH-128 smc_engine.
