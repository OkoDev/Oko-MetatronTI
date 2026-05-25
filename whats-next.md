# What's Next — Handoff Document

> Последнее обновление: **2026-05-25 ~18:00 UTC** (Агент: Architect/Sonnet 4.6).

---

<current_session>

<original_task>
ARCH-113: TPSelector — Intelligent TP Gravity Engine.
Полное исследование + рой + документация + TASK на реализацию.
</original_task>

<work_completed>

## Исследование ARCH-113 TPSelector (7 скриптов, 156K+ уровней)

### Ключевые выводы:
1. **Woodie/Camarilla → EXCLUDED** (overlap 89.5%, unique hits 0%)
2. **Gravity scoring: score = gravity / dist^1.5** (alpha=1.5 доказан → top10%=83% reach)
3. **FVG decay**: effective_weight = base × exp(-age/tau). 1h FVG: 73.8% → 16.3% (age 0-3 vs 60+)
4. **Pyramiding подтверждён**: P(4h FVG | 15m FVG hit) = 65.8% vs 51.3% → Lift +14-21%
5. **42% SL сделок** имели max_R_possible > 0.5R — потенциал конверсии с правильным TP
6. **Прогноз**: WR 25% → 70-85% при FVG магнитах, expectancy +0.75R (vs -0.44R сейчас)

### Созданные файлы:
- `scripts/pivot_comparison_test.py` — Woodie/Camarilla excluded
- `scripts/tp_levels_comprehensive_test.py` — reach по источникам
- `scripts/gravity_cluster_test.py` — кластеризация + lift
- `scripts/gravity_alpha_optimizer.py` — alpha=1.5 оптимум
- `scripts/tp_atr_normalized_test.py` — ATR-нормировка, FVG decay
- `scripts/tp_reach_over_time.py` — временная динамика (504h)
- `scripts/mtf_pyramid_test.py` — MTF иерархия + P(HTF|LTF)

### Документация:
- `obsidian/Tasks/ARCH-113.md` — ОБНОВЛЁН: полный план Phase 1/2/3
- `obsidian/Research/ARCH-113-TPSelector-Research-2026-05-25.md` — СОЗДАН
- `memory/project_confluence_principle.md` — СОЗДАН
- `TASKS.md` — ARCH-113 обновлён
- Team Discussion: `obsidian/Team-Discussions/2026-05-25-arch-113-tpselector-plan-реализации-intelligent-sl.md`

## Рой-синтез (4/6 моделей):
- **Начать с TPSelector** (3/4 моделей — WR TP сейчас 8-13%, это критичнее SL)
- **MVP источников**: FVG(young 0-3 bars) + PDH + psycho (консенсус 5/5)
- **Интеграция**: plugin-layer `apply_tp_selector()` + config флаг `tp_selector_enabled: false`
- **Хранение**: on-the-fly в calculate_levels(), LRU cache TTL=30s
- **Pyramiding**: signal type `PYRAMID_ADD` → через monitoring.py

</work_completed>

<next_session_priorities>

## 🔴 ПРИОРИТЕТ 1: D-053 (в параллельной сессии)
WsFeed cascade crash — scan_loop dies. 105 случаев за 3 дня. КРИТИЧЕСКИЙ БАГ.
Обрабатывается отдельно.

## 🔴 ПРИОРИТЕТ 2: ARCH-113 Phase 1 — TPSelector MVP

**Задача: создать `core/smc/tp_selector.py`**

### Шаг 1: Структура модуля
```python
# core/smc/tp_selector.py
import math
from dataclasses import dataclass
from typing import Optional

@dataclass
class TPCandidate:
    price: float
    gravity: float
    dist_pct: float
    score: float          # gravity / dist^1.5
    sources: list[str]    # ['fvg_1h', 'psycho']
    label: str            # для tp_source в БД

class TPSelector:
    EPS_PCT = 0.5          # ±0.5% кластеризация
    ALPHA = 1.5            # score = gravity / dist^alpha
    MAX_DIST_PCT = 15.0    # фильтр дальних уровней
    
    DECAY_TAU = {'5m': 60, '15m': 40, '1h': 20, '4h': 15}
    BASE_WEIGHTS = {
        'fvg_5m': 2, 'fvg_15m': 3, 'fvg_1h': 4, 'fvg_4h': 5,
        'pdh': 3, 'pdl': 3, 'pwh': 4, 'pwl': 4,
        'psycho': 2, 'vp_poc': 3, 'std_r1': 2, 'std_r2': 1,
    }
    
    def select(self, entry, direction, market_context, signals):
        magnets = self._collect_magnets(entry, direction, market_context, signals)
        clusters = self._cluster(magnets)
        ranked = sorted(clusters, key=lambda c: c.score, reverse=True)
        tp1 = self._pick_tp1(ranked)  # dist <0.5R, ближайший хороший
        tp2 = self._pick_tp2(ranked, tp1)  # dist 1-3R, макс гравитация
        return tp1, tp2
```

### Шаг 2: Интеграция в recommendation_generator.py
```python
# В calculate_levels(), ПОСЛЕ расчёта SL, ПЕРЕД возвратом:
def apply_tp_selector(entry, direction, sl_pct, market_context, signals, config):
    if not config.get('sl_tp_engine', {}).get('tp_selector_enabled', False):
        return None, None
    try:
        from core.smc.tp_selector import TPSelector
        tp1, tp2 = TPSelector().select(entry, direction, market_context, signals)
        return tp1, tp2
    except Exception as e:
        logger.warning('TPSelector failed: %s', e)
        return None, None
```

### Шаг 3: config.yaml
```yaml
sl_tp_engine:
  tp_selector_enabled: false   # A/B флаг (включить на 50% пар для теста)
  tp_selector_eps_pct: 0.5     # кластеризация ±%
  tp_selector_alpha: 1.5       # gravity score alpha
  tp_selector_max_dist_pct: 15.0
```

### Шаг 4: Источники данных в market_context
Проверить что доступно в MarketContext при вызове calculate_levels():
- FVG bull/bear по TF: `grep "fvg\|bear_fvg\|bull_fvg" core/signals/signal_models.py`
- PDH/PDL: `grep "prev_day_high\|pdh" core/`
- Psycho: нужно добавить в MarketContext или вычислять inline
- VP POC: `grep "vp_poc\|volume_profile" core/`

## 🔴 ПРИОРИТЕТ 3: D-047
Интеграция wt_cross_*_1h gate. Walkforward avgR=+1.55 WR=85% подтверждён.

</next_session_priorities>

<context_for_next_agent>

### Что нужно знать следующей сессии:

**Основа решения:** данные из 7 исследований (156K уровней) однозначно показывают:
- FVG <0.3R: 73-86% reach за 24h (ЛУЧШИЙ источник TP)
- Gravity кластер 2+: +14-21% lift
- Alpha=1.5 оптимум для score = gravity/dist^alpha

**Что НЕ трогать:**
- RANGE BOUNCE SL/TP (`core/smc/sl_tp_calculator.py`) — отдельная стратегия, остаётся
- ARCH-104 паттерны — у них свой SL через `arch104:no_trail_r2.0`
- Текущую иерархию SL в `calculate_levels()` — Phase 2 задача, не Phase 1

**Флаг для безопасного A/B:**
`tp_selector_enabled: false` — по умолчанию выключен, включить только для тестовой группы пар

**Ключевой файл:** `obsidian/Tasks/ARCH-113.md` — полный план с acceptance criteria

</context_for_next_agent>

</current_session>
