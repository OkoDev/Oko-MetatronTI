---
name: arch124-regime-audit
description: ARCH-124 аудит — классификатор RANGE мислейблит 78% трендов; regime-гейтинг построен на неверной метке; предпочитать прямые htf_dir фильтры
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# ARCH-124: Классификатор режимов МЕШАЕТ (аудит 30.05.2026)

Гипотеза ARCH «вычисление режимов мешает» — ПОДТВЕРЖДЕНА данными. Аудит = только данные.

## Железобетонное доказательство

**(A) Price-action спот-чек 18 RANGE-сделок (4h фетч):** критерий «тренд» = |Δцены 40h|≥5% ИЛИ ADX≥25.
→ **14/18 = 78% реально ТРЕНДИЛИ**. Венец: LAB SHORT при аптренде +46.1%/40h, ADX=44, помечен RANGE и зашортен (R=-1.11). BANANA SHORT -6.3% ADX=31 → R=-6.18.

**(A2) max_R proxy (7д):** RANGE avg_max_R=0.65 > TREND_UP 0.59 > TREND_DOWN 0.56. RANGE имеет БОЛЬШЕ крупных движений (9.1% сделок ≥2R). Флэт дал бы НИЗКИЙ max_R → значит трендили.

**(B) help/hurt:** regime слабый дискриминатор. watch_list_breach убыток ВЕЗДЕ (-0.17/-0.12/-0.09); pivot_reversal ХУЖЕ в "range" (-0.23 vs TREND +1.2/+1.7). Нет паттерна «RANGE=плохо».

**(C):** RANGE LONG +0.159 vs SHORT -0.533 → дело в НАПРАВЛЕНИИ (дрейф вверх), не в режиме.

## КОРЕНЬ (код)

`market_regime.classify_from_dataframes`: TREND требует 15m+1h+4h ВСЕ синхронны ПО направлению + `|WT1-WT2|>10`. В шумной крипте 15m-supertrend часто ≠ 4h → почти никогда TREND → 78% трендов сваливаются в RANGE.

## Связанная находка: SHORT-фильтр протекает

`allow_short_regimes:[TREND_DOWN]` применяется ТОЛЬКО в scan_loop.py:700 (atr_change). 10/11 signal_type игнорируют → 455 RANGE SHORT/7д avgR=-0.391 (-178R). Главный протекатель после confluence-off (DEV-224) = watch_list_breach (160).

## ВЕРДИКТ + рекомендация

**Классификатор режимов МЕШАЕТ.** Метка неверна в 78%, гейты на ней — мусор.

Рекомендация: свернуть regime-гейтинг → ПРЯМЫЕ направленные фильтры:
- `htf_price_dir=down` для SHORT (реальное 4h-направление, не label)
- `n_down × htf` (Elliott фаза, см. [[arch117-wt-audit]] смежно Elliott)
- PP position / ADX напрямую

ЛИБО чинить классификатор: HTF-доминантность (4h-тренд главный) вместо требования полной MTF-синхронности.

Скрипты: `e:/tmp/arch124_spotcheck.py`, `e:/tmp/arch124_audit.py`. Разбор: DISCUSSION 30.05.
Смежно: DEV-237 (BTCRegimeProvider лаг — тот же мотив, другой компонент).

## РЕШЕНИЕ + РЕАЛИЗАЦИЯ (02.06.2026, shadow) — коммит 5389bcc

Пользователь выбрал «чинить классификатор» (НЕ htf_dir-фильтры: они = второй источник тренда, нарушают «один калькулятор» ARCH-118, regime остаётся сломан для 8 потребителей). Чиним корень-Сферу **за shadow** (как магнит ARCH-122 P2). Сфера regime НЕ тронута, живое поведение 0 изменений.

**Сделано:**
- `market_regime.classify_v2` переписан HTF-доминантным: 4h-supertrend главный (fallback 1h), 15m/1h НЕ требуют синхронности. RANGE только если HTF затухает (WT-div≤10 И ADX≤25). Корень мислейбла = `market_regime.py:191` `mtf_aligned = len(set)==1`.
- Фикс HIGH_VOL: range>3×median (ложный ~всегда) → ATR-метод как v1.
- `regime_v2` shadow-поле БД (рядом с regime, use_v2=false → не влияет). Пишется в trade_simulator register.
- `scripts/regime_v2_ab.py` — A/B v1 vs v2, ловит вредные SHORT (v1=RANGE→v2=TREND_UP).
- Тест истории (39 пар, HTF=1h): RANGE 13%→3%, 4 пары RANGE→TREND_DOWN, HIGH_VOL 31=31.

**Дальше:** рестарт бота → regime_v2 пишется → через 24-48ч `regime_v2_ab.py` (нужно ~30+ закрытых) → переключить `use_v2=true` ТОЛЬКО по данным. См. [[feedback_db_query_utc]] (created_at=UTC при анализе).
