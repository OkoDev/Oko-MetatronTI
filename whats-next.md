# What's Next — Handoff Document

> Последнее обновление: **2026-06-08** (Агент: Claude/Opus 4.8).

---

## 🎯 СЕССИЯ 08.06 — Баланс-фикс + Раннеры + 🌊 Золотая связка Волна+SMC

### ⚠️ ПЕРВЫМ ДЕЛОМ: РЕСТАРТ БОТА
Накопились config+code изменения (не применены до рестарта):
```
arch104 вернул из shadow (enabled:true) · OTE min-rr 3.0 · раннеры clamp 50
pivot_reversal+confluence → shadow (exchange_enabled:false)
DS: TSL-профили (ote 3/8/24) · funding-node
```

### ✅ Что сделано (коммиты)
- `dd6b85c` DISCUSSION порядок (1143→563, 03.06→архив) + согласования
- `89ea436` OTE min-rr 3.0 + arch104 shadow (потом вернул)
- `40f043c` раннеры clamp 15→50 (метрика была занижена, юзер заметил +15.00R потолок)
- `1c283bf` pivot+confluence → shadow + WAVE-SERVICE трек
- `6eb218f` 🌊 инструмент wave_smc_entry.py + бэктест
- DS параллельно: `af7bfae` slippage-аудит + TSL-профили + funding-node

### 🔑 Ключевые выводы
1. **Баланс-минус ≠ arch104.** Slippage реально ~0.1% (не 0.45% — моя ошибка). Реальный минус = **pivot_reversal (−1272R WR27%) + confluence**. OTE+arch104 = +1501R (плюс!).
2. **pivot слеп к рыночной фазе:** LONG на росте +0.99 WR60%, на обвале −0.94 WR2%. Корень = нет волнового контекста.
3. **🔥 Связка Волна+SMC ВАЛИДИРОВАНА** (бэктест n=743): edge +0.45..+0.72R vs pivot −0.36. Лечит слепоту. → `memory/wave_smc_backtest_validated.md`.

### 🔄 NEXT (приоритет, в TASKS)
1. **WAVE-WATCH** (🟡 — юзеру очень зашло, быстрая польза) — `scripts/wave_smc_entry.py --watch <ПАРА>`: фон-мониторинг, алерт когда цена в конфлюэнт-зоне (Фибо×Пивот) + LTF (3m/5m) CHoCH-триггер. Сигналит, не торгует. Обкатка ядра перед флагманом.
2. **WAVE-FLAGMAN** (🔴 — идея юзера) — НОВЫЙ движок раннеров (НЕ в OTE): связка как ядро → детектор `wave_smc_generator` → observer-loop (копия ote_observer) → SINGLE+TSL clamp50. signal_type='wave_smc'.
3. **PIVOT-WAVE-GATE** (🟡) — вернуть pivot из shadow с волновым гейтом.
4. **WAVE-SERVICE** (🔴) — формализация per-ТФ структуры → Bus. Добавить коррекции (зигзаг/плоскость, эталон `docs/Гайд по структурам*.pdf` + `memory/reference_elliott_wave_guide.md`).

### 🛠️ Инструмент готов
```bash
python scripts/wave_smc_entry.py XLM         # анализ входа: волна+SMC+OTE+пивоты+конфлюэнция
python scripts/wave_smc_backtest.py          # валидация связки
```

### 📌 DS-зона (параллельно)
DS закрыл 4 приоритета частично (af7bfae). Открыто: DS-BRIDGE-SNAP (движки читают снимок), RiskIntelligence→prod, Shared Context Bus 38 полей, Execution Sphere ARCH-96.

---

## Старый контекст (до 08.06)
ARCH-118 единый снимок ЗАКРЫТ (118.3 вынос core + discount parity 0/10 + DEV-200.2 мост). OTE-флагман в проде (+1115R до clamp-фикса, теперь честнее). ARCH-104 паттерны (DS-315/316). Подробности — git log + `obsidian/`.
