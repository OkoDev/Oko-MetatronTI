---
name: wave_smc_backtest_validated
description: БЭКТЕСТ подтвердил связку Волна+SMC — edge +0.45..+0.72 avgR vs pivot baseline −0.36; основа WAVE-SERVICE гейта
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# Связка Волна + SMC — ВАЛИДИРОВАНА бэктестом (08.06.2026)

**Walk-forward** (без lookahead, df[:i] на каждом баре), 8 пар (BTC/ETH/SOL/XRP/BNB/ADA/LINK/AVAX) × 4h+1h, RR2, horizon 40 баров, SL за swing. Скрипт: `/tmp/wave_smc_bt.py` (перенести в `scripts/wave_smc_backtest.py`).

## Результаты (n=743 сетапов)
| режим | n | avgR | WR | NET |
|---|---|---|---|---|
| TREND (BOS, по тренду) | 654 | **+0.445** | 58% | +291R |
| TREND_SHORT | 500 | **+0.665** | 66% | +333R |
| TREND_LONG | 154 | −0.269 | 32% | −41R |
| REVERSAL (CHoCH, против) | 89 | **+0.571** | 65% | +51R |
| REVERSAL_SHORT | 81 | **+0.716** | 72% | +58R |
| REVERSAL_LONG | 8 | −0.893 | 0% | (мало n) |

## Ключевое
- **Связка РАЗГРОМила слепой pivot:** pivot_reversal −0.36 WR27% (−1126R слив) → связка SHORT +0.72 WR72%. Волновой+CHoCH фильтр превратил слив в edge (+1R, WR ×2.7).
- **SHORT доминирует** = РЫНОК (медвежий период, BTC −28%), НЕ дефект связки. LONG слабый по той же причине (как arch104/pivot LONG в медвежью фазу). LONG-валидация требует БЫЧЬЕЙ фазы.
- **Оба режима работают:** TREND (BOS, импульс активен+откат<38%) +0.45, REVERSAL (CHoCH, импульс выдохся+откат>38%) +0.57.

## Логика сетапа (прототип, [[reference_elliott_wave_guide]])
```
волна (detect_elliott_impulse) → направление импульса + откат%
РЕЖИМ по откату:
  откат<38% + импульс активен → ТРЕНД: BOS по тренду + откат → вход ПО импульсу
  откат>38% + импульс выдохся  → РАЗВОРОТ: CHoCH против + откат(retest<3%) → вход ПРОТИВ
SMC: detect_structure_breaks(length=5, эталон OKO-SM [[calib_choch_length5]])
MTF: согласование TF (4h↓+1h↓ = уверенный тренд; HTF↓+LTF↑ = откат/nested)
```

## Применение (→ [[WAVE-SERVICE]], решает [[PIVOT-CONTEXT]])
1. **Гейт pivot/confluence:** вход только если волна+SMC согласны (фаза разрешает) → лечит слепоту.
2. **Усиление OTE:** CHoCH-подтверждение в зоне (вход где структура сломалась, не просто Фибо-откат).
3. **Новый сигнал WaveSMC:** SHORT-сила (WR72%) = кандидат в торговлю после бычьей-фазы LONG-проверки.

## Оговорки
- Период медвежий → SHORT-смещение. Нужна бычья фаза для LONG.
- RR2/horizon40 фиксированы (тюнить: TSL вместо fixed TP, разные RR).
- Только импульс-фаза классифицируется (коррекции зигзаг/плоскость ещё не добавлены — покрытие ~30% баров, но high-confidence).
