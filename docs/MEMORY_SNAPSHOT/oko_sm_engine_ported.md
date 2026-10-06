---
name: oko_sm_engine_ported
description: "OKO-SM (индикатор Егора) пересажен в Python 1:1 — CHoCH/BOS цены идентичны живому графику (BTC 15/15, ETH 13/13, SOL 93%). Глаз Егора = машиночитаемый эталон через TW MCP. Нога для OTE из current_leg"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
  modified: 2026-07-22T22:24:35.260Z
---

# OKO-SM пересажен в Python — глаз Егора стал кодом (23.07)

Егор: «как тебя научить детектить?!» → ответ: не учить заново, а ПЕРЕСАДИТЬ индикатор.

## Что сделано
- TW MCP (CDP): перезапуск TW с портом (MSIX: `Invoke-CommandInDesktopPackage -PackageFamilyName
  TradingView.Desktop_n534cwy3pjxzj -AppId TradingView.Desktop -Command <exe> -Args
  "--remote-debugging-port=9222"`; tv_launch не видит Store-установку).
- Прочитан исходник **OkoSM v163** (pine_open+pine_get_source, 2200 строк) →
  `docs/reference/OkoSM_v163.pine`. Архитектура LuxAlgo SMC + калибровка Егора.
- **`core/smc/oko_sm_engine.py`** — порт 1:1: swings(len) os-машина (top=high[len]>ta.highest,
  подтверждение len баров позже), структурная машина swing(50)+internal(5), CHoCH/BOS
  crossover(close, level), trail_up/dn = Strong High/Weak Low, `current_leg()` (нога для OTE).

## Верификация (авто-эталон: data_get_pine_labels с живого графика Егора)
| пара | совпадение CHoCH/BOS цен | окно |
|---|---|---|
| BTC | 15/15 хвост (100%) | 500 |
| ETH | **13/13 (100%)** | 1000 |
| SOL | 13/15 (93%: 1 округление, 1 холодный старт окна) | 500 |
**Окно ≥1000 баров убирает холодный старт.** Учительский цикл БЕЗ ручной разметки: моё событие
обязано = метка индикатора. Егор дал право переключать пары/менять настройки индикатора
(indicator_set_inputs) для сверки чувствительности.

## Ноги (current_leg, len50): ETH LONG 1511→1956 · SOL LONG 64→83.9 · BTC двухмасштабие
(swing SHORT 67251→57772, цена premium 0.87 / internal LONG 57772→66921) — вопрос ноги-для-OTE
в смешанном состоянии = вердикт Егора (метод: СТОРОНА от len50, вход от len5).

**Why:** решает вердикт «неверно детектим OTE» ([[ote_waiting_limit_golden_pocket_edge]]) —
старый детектор брал ногу мельче; теперь нога = нога Егора. **How to apply:** (1) большой
бэктест waiting-limit (канонич. fib + структурный SL) на ногах oko_sm_engine, ohlcv_cache 4h
2022-26; (2) leg_verify v2 через engine; (3) при расхождении с графиком — сначала окно/история,
потом правила. Связано: [[method_egor_two_scale_entry]], [[calib_choch_length5]], [[tradingview_mcp_setup]].
