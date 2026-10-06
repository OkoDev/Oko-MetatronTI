---
name: marketcap_dominance_engine
description: "Self-computed dominance engine (24.07) — USDT.D/BTC.D/ALT.D БЕЗ TW, продукт-грейд. Σ(supply×live_price)+tail. + rotation_now триада Егора (USDT.D↑BTC.D↓=альты стоят / USDT.D↓=летят)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
  modified: 2026-07-24T18:17:35.852Z
---

# SELF-COMPUTED DOMINANCE ENGINE (24.07) — Куб считает доминации сам

Егор (продуктовое мышление): «Куб как продукт — у юзера может не быть открытого/настроенного TW».
→ TW-read = личный костыль, НЕ фундамент. Доминации Куб вычисляет из первичных данных.

## Формула / источники (core/context/marketcap_engine.py)
`USDT.D = usdt_mcap / TOTAL`, `TOTAL = Σ(supply_i × price_i) + tail`
- supply_i — daily CMC listings топ-500 (ключ юзера, medленно меняется). tail = global−Σlisted.
- price_i — LIVE Binance ticker + BingX perps (один REST каждой, **85% total-mcap живьё**, без ключа).
- Автономно, tick-fast, любой install, БЕЗ TW. Функции: refresh_supply_snapshot (pm2 mcap-refresh
  cron 00:10), live_dominance (кэш 45с), rotation_now.

## Точность (сверка TW 24.07)
Куб USDT.D 8.25 / BTC.D 57.7 / ETH.D 10.1 / ALT.D 30.1 vs TW ~8.49 / 59.4 / 10.3. Смещение ~1-2%
(состав TOTAL: CMC-универс + возможный дабл-каунт wrapped/staked vs CRYPTOCAP). Для РЕЖИМА/ротации
нормализуется — важны движения/направление, не абсолют. NEXT-точность: дедуп WBTC/stETH/WETH.

## 🔺 ТРИАДА-РОТАЦИЯ (наблюдение Егора, rotation_now, порог FLAT=1.2 калибр. по глазу)
Тренды USDT.D/BTC.D/альт-mcap за window_h (CMC global-hist total+altcoin) → вердикт:
- **USDT.D↓** → 🟢 АЛЬТЫ ЛЕТЯТ (деньги из стейблов в крипту) — сигнал альт-лонгов.
- **USDT.D↑ & BTC.D↓ & альт≈flat** → 🟡 АЛЬТЫ СТОЯТ (risk-off тянет, но альты отбирают долю у BTC — гасятся).
- **USDT.D↑ & альт↓** → 🔴 RISK-OFF. **BTC.D↑ & альт↓** → 🟠 BTC-сезон.
Живьё 24.07: ΔUSDT.D+0.09 ΔBTC.D-0.18 альт-0.58% → 🟡 СТОЯТ = точь-в-точь слова Егора.

## Продуктовая архитектура доминаций (слоями)
1. Baseline (0 конфига, любой юзер): CoinGecko /global снапшот — лагает, для режима ок.
2. **Real-time автономный: ЭТОТ движок** (свой фид × supply) — tick-fast, без TW.
3. ~~TW-read (MCP)~~ — только личная сверка Егора, НЕ продукт (юзер TW не имеет).

**Why:** USDT.D-данные TW ≠ секрет; разница была в частоте опроса Куба (CG раз в 4ч→дневной) +
смещении состава. **How to apply:** usdtd_watch/[[phase_sphere_decision_core]] дёргают live_dominance
(moment) + rotation_now (триада) вместо лагающего CMC-снапшота; rotation-алерт в TG. Связано:
[[env_binance_fstream_ws_blocked]] (BingX для tail), atr_S2 USDT.D-гейт.
