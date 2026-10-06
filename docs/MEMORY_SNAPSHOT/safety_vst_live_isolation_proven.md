---
name: safety-vst-live-isolation-proven
description: "🛡️ ИЗОЛЯЦИЯ VST↔LIVE ДОКАЗАНА ФАКТИЧЕСКИ (21.08): бот на open-api-vst.bingx.com с ключами BINGX_VST_*, видит 0 позиций; Егор торгует на LIVE (open-api.bingx.com, BINGX_API_KEY). Разные домены И разные ключи. orphan_autoclose=live опасен ТОЛЬКО внутри своего домена"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 696399f2-16be-4ffc-97be-acad52cc3fb5
  modified: 2026-08-21T10:41:14.129Z
---

# 🛡️ ИЗОЛЯЦИЯ VST ↔ LIVE — ПРОВЕРЕНО ФАКТИЧЕСКИ (21.08.2026)

Повод: Егор торгует на LIVE РЕАЛЬНЫМИ деньгами ПРЯМО СЕЙЧАС и требует, чтобы бот
не мог задеть его позиции. Прецедент есть: [[bot_autocloses_manual_positions_d070]] —
`orphan_autoclose: live` закрыл ручные RPL/YFI/MELANIA/RSR.

## РАЗДЕЛЕНИЕ НА ДВУХ УРОВНЯХ (`core/exchange/bingx_client.py:826-841`)
```
mode == "vst"  → ключи BINGX_VST_API_KEY / BINGX_VST_SECRET_KEY
                 домен  https://open-api-vst.bingx.com
mode == "live" → ключи BINGX_API_KEY / BINGX_SECRET_KEY
                 домен  https://open-api.bingx.com
```
**Разные ключи И разные домены.** Аккаунты не пересекаются.

## ФАКТИЧЕСКАЯ ПРОВЕРКА (не теория)
```
execution_mode:      vst
домен клиента:       https://open-api-vst.bingx.com
LIVE-домен:          False
ПОЗИЦИЙ ВИДИТ БОТ:   0        ← у Егора на LIVE позиции ОТКРЫТЫ
```
Бот не видит ни одной позиции Егора → `orphan_autoclose` физически не может их
тронуть: он закрывает только то, что видит в СВОЁМ домене.

## 🔴 ГДЕ ОПАСНОСТЬ ВЕРНЁТСЯ
`orphan_autoclose: live` (config.yaml:359) ВСЁ ЕЩЁ ВКЛЮЧЁН.
`order_manager.is_live()` возвращает True и для VST, и для LIVE
(`order_manager.py:117-118`) — то есть автозакрытие АКТИВНО и на демо.

**Смена `trading.execution_mode` на `live` мгновенно делает бота опасным
для ручных позиций.** Перед любым переключением на live:
1. Выключить `orphan_autoclose` (`off` или `shadow`).
2. Проверить `sl_reconcile` (тоже `live`).
3. Перепроверить фактически: сколько позиций видит бот.

## Проверка одной командой (повторять перед КАЖДЫМ включением боевого режима)
```python
from core.exchange.bingx_client import make_client, VST_BASE_URL, LIVE_BASE_URL
cl = make_client(mode, config, 1)      # порядок аргументов: mode, config, account
print(cl.base_url == VST_BASE_URL, len(await cl.get_positions() or []))
```

Связано: [[bot_autocloses_manual_positions_d070]], [[bingx_api_key_single_per_account]],
[[orphan_root_dbexch_desync]], [[bug_close_position_market_side_inverted]].
