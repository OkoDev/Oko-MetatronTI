# Куб Метатрона: Sub-кубы (Фрактальный Куб)

> **Принят:** 29.05.2026 | **Задачи:** ARCH-116..120
> **Основа:** анализ архитектуры + рой-обсуждение ARCH-115 + Elliott Wave исследование
> **Детальный контекст:** `docs/ENCYCLOPEDIA.md` → раздел "Sub-кубы"

---

## Принцип фрактальности

Куб Метатрона масштабируется **рекурсивно**: каждая сфера главного Куба может внутри себя содержать малый Куб — набор из 3-6 внутренних сфер со своей шиной и своим центром-агрегатором.

```
Главный Куб (13 сфер)
│
├── Сфера 4 (MTF SMC) ─────► [SMC Sub-куб]        ← реализуется сейчас
│                               OB + FVG + Struct + Liq → SMCContext
│
├── Сфера 8+14 (Pivot+Wave) ─► [Elliott-Pivot Sub-куб] ← строится сейчас
│                               Wave + Pivot + Fib → PricePositionContext
│
└── Сфера 3 (MTF WT) ───────► [WT Sub-куб]         ← Этап 21 (vision)
                                WT×5TF → MTF_WT_Verdict
```

**Внешний интерфейс Sub-куба = обычная сфера главного Куба.** Никакого изменения в pipeline — снаружи это просто вызов `.compute_and_publish()`.

---

## Sub-куб 1: SMC (ARCH-120) ★ ПЕРВЫЙ

### Статус и обоснование

```
Готовность: core/smc/ содержит все 6 модулей (существуют с ARCH-17, 18.03.2026)
Данные:     data_era v4 (post-29.04.2026) — 6/9 SMC признаков теперь корректны
Триггер:    ≥200 smc_snap сделок → MTF SMC Specialist ML обучится на реальных данных
```

### Внутренние сферы

| Сфера | Файл | Выход |
|-------|------|-------|
| OBSphere | `core/smc/order_blocks.py` | `ob_bull`, `ob_bear`, `ob_distance_pct`, `ob_mitigation_pct` |
| FVGSphere | `core/smc/fvg.py` | `fvg_open`, `fvg_age_bars`, `fvg_dist_R`, `fvg_size_pct` |
| StructureSphere | `core/smc/structure.py` | `choch`, `bos`, `last_break_dir`, `bars_since_break` |
| LiquiditySphere | `core/smc/liquidity.py` | `eqh_near`, `eql_near`, `sweep_recent`, `sweep_bars_ago` |
| OTESphere | `core/smc/ote.py` | `ote_zone_active`, `ote_optimal_price`, `ote_fib_level` |

### Центр: SMCContext

```python
@dataclass
class SMCVerdict:
    label: str          # STRONG_BEAR / WEAK_BEAR / NEUTRAL / WEAK_BULL / STRONG_BULL
    confidence: float   # 0.0 – 1.0
    key_factors: list[str]  # топ-3 фактора ("ob_bear_active", "fvg_open_4h", ...)
    raw: dict           # все поля для features_json

class SMCContext:
    """Центр SMC Sub-куба. Агрегирует 5 внутренних сфер → единый вердикт."""
    
    def aggregate(self, ob, fvg, struct, liq, ote) -> SMCVerdict:
        score = 0.0
        factors = []
        
        # Bearish signals
        if ob['ob_bear']:       score -= ob['ob_distance_pct'] * 0.3; factors.append("ob_bear")
        if fvg['fvg_open']:     score -= 0.2;  factors.append("fvg_open")
        if struct['bos']:       score -= 0.25; factors.append("bos_bearish")
        if struct['choch']:     score -= 0.15; factors.append("choch_bearish")
        if liq['eqh_near']:     score -= 0.1;  factors.append("eqh_liquidity")
        if liq['sweep_recent']: score -= 0.2;  factors.append("sweep_recent")
        
        # Bullish signals (зеркально)
        if ob['ob_bull']:       score += ob['ob_distance_pct'] * 0.3; factors.append("ob_bull")
        if ote['ote_zone_active']: score += 0.3; factors.append("ote_active")
        if liq['eql_near']:     score += 0.1;  factors.append("eql_liquidity")
        
        label = (
            "STRONG_BEAR" if score < -0.5 else
            "WEAK_BEAR"   if score < -0.2 else
            "STRONG_BULL" if score >  0.5 else
            "WEAK_BULL"   if score >  0.2 else
            "NEUTRAL"
        )
        return SMCVerdict(label=label, confidence=min(abs(score), 1.0),
                          key_factors=factors[:3], raw={**ob, **fvg, **struct, **liq, **ote})
```

### Интерфейс в главном Кубе

```python
class SMCSubCube:
    """Снаружи = Сфера 4. Внутри = SMC мини-Куб."""
    
    def compute_and_publish(
        self,
        sym: str,
        dfs: dict,          # {'df_4h': ..., 'df_1h': ..., 'df_15m': ...}
        ctx_bus: SharedContextBus,
    ) -> SMCVerdict:
        
        ob_r     = self._ob_sphere.compute(dfs['df_4h'])
        fvg_r    = self._fvg_sphere.compute(dfs['df_1h'])
        struct_r = self._struct_sphere.compute(dfs['df_4h'])
        liq_r    = self._liq_sphere.compute(dfs['df_1h'])
        ote_r    = self._ote_sphere.compute(dfs['df_15m'])
        
        verdict = self._context.aggregate(ob_r, fvg_r, struct_r, liq_r, ote_r)
        
        ctx_bus.update(sym, {
            "smc_snap":     verdict.raw,
            "smc_verdict":  verdict.label,
            "smc_conf":     verdict.confidence,
            "smc_factors":  verdict.key_factors,
        })
        return verdict
```

### Acceptance criteria (ARCH-120)

```
✅ SMCSubCube.compute() заменяет прямые вызовы core/smc/* в scan_loop
✅ smc_snap в ctx_bus совместим с текущим форматом (обратная совместимость)
✅ MTF SMC Specialist читает из ctx_bus['smc_snap'] а не напрямую из файлов
✅ py_compile OK, 0 регрессий в signal generation
✅ После 200+ SMC-сделок: запустить MTF SMC Specialist обучение
```

---

## Sub-куб 2: Elliott-Pivot (ARCH-121/118/119)

### Статус и обоснование

```
WaveSphere:  DEV-226 ✅ (Elliott функции в indicators.py)
PivotSphere: ARCH-123 🟢 (PivotCalculatorFixed → формализовать)
Reversal Mode: ARCH-119 🟢 (MarketRegime v2)
FibSphere:   🔵 (новый, создать)
```

### Внутренние сферы

| Сфера | Файл | Выход |
|-------|------|-------|
| WaveSphere | `core/intelligence/wave_service.py` (новый) | `n_down`, `n_up`, `n_down_1h`, `elliott_phase`, `wave_confidence` |
| PivotSphere | `core/pivots/pivot_calculator.py` (рефактор) | `PP`, `S1-S3`, `R1-R3`, `above_pp`, `nearest_level`, `fib_equiv` |
| ReversalSphere | `core/indicators/market_regime.py` (расширить) | `regime`, `mode` (TREND/REVERSAL), `reversal_confidence` |
| FibSphere | `core/intelligence/fib_clusters.py` (новый) | `fib_cluster_score`, `ote_zone_price`, `invalidation_level` |

### Центр: PricePositionContext

```python
@dataclass
class PricePositionContext:
    # Волновая фаза
    phase: str              # "wave3_mid" | "wave5_final" | "ABC_waveB" |
                            # "impulse_start" | "correction_end" | "undefined"
    wave_confidence: float  # 0.0 – 1.0
    
    # Пространство
    above_pp: bool
    nearest_level: str      # "PP" | "R1" | "S1" | "S2" | ...
    space_direction: str    # "room_to_short" | "room_to_long" | "congested"
    
    # Режим рынка
    regime_mode: str        # "TREND" | "REVERSAL"
    
    # Fibonacci
    invalidation_level: float   # цена где счёт волн неверен (SL цель)
    fib_cluster_score: int      # кол-во Fib уровней у TP цели
    
    # TP модификаторы (для TPSelector)
    tp_phase_modifier: float    # 1.6 (w3) | 0.5 (w5) | 0.55 (ABC_B) | 1.0
    
    # Входные данные (сырые)
    n_down: int
    n_up: int
    n_down_1h: int


# Таблица phase → tp_modifier:
PHASE_TP_MODIFIER = {
    "impulse_start":   1.5,  # начало волны 3 → большой потенциал
    "wave3_mid":       1.6,  # середина волны 3 → цель 161.8%
    "correction_end":  1.3,  # конец коррекции → продолжение тренда
    "wave5_final":     0.5,  # финал волны 5 + дивергенция → консервативно
    "ABC_waveB":       0.55, # коррекционный SHORT в волне B
    "undefined":       1.0,  # неопределённо → нейтрально
}

# Таблица phase → SL logic:
PHASE_SL_LOGIC = {
    "wave2_ote":   "wave1_start",     # invalidation = начало волны 1
    "wave4_ote":   "wave1_end",       # invalidation = конец волны 1 (правило R3)
    "wave5_final": "nearest_swing",   # тесный SL (быстрое движение)
    "undefined":   "swing_buffer",    # текущая логика
}
```

### gap_guard (обязателен при TSL off)

```python
# Защита при отключении TSL для divergence / liquidity_sweep
# Рекомендован ройем (Cerebras, ARCH-115)

class GapGuard:
    """Hard SL при flash crash / overnight gap."""
    
    GAP_THRESHOLD = 0.02  # 2% движение = gap event
    
    def check(
        self,
        current_price: float,
        last_known_price: float,
        direction: str,
        entry_price: float,
        sl_price: float,
    ) -> bool:
        """True = нужен немедленный hard SL."""
        gap = abs(current_price - last_known_price) / last_known_price
        
        if gap < self.GAP_THRESHOLD:
            return False
        
        # Gap в сторону убытка — закрываем немедленно
        if direction == "SHORT" and current_price > last_known_price:
            return True
        if direction == "LONG" and current_price < last_known_price:
            return True
        
        return False
```

### Реализация WaveService (ARCH-121)

```python
# core/intelligence/wave_service.py

from core.indicators.indicators import (
    find_swing_highs, find_swing_lows,
    calculate_n_down, calculate_n_up,
)

class WaveService:
    """
    Сфера 14 Куба Метатрона.
    Вычисляет волновую фазу и публикует в SharedContextBus.

    АРХИТЕКТУРНОЕ РЕШЕНИЕ (рой 4/4, 29.05.2026):
    Синхронный вызов в scan_loop — ordering гарантирован.
    EventBus уведомления — опционально при phase_change.
    Переход на полный async EventBus: Этап 21 (CubeNode).
    """

    SWING_PERIOD_4H = 5
    SWING_PERIOD_1H = 5
    SWING_PERIOD_LTF = 3
    MIN_BARS = 15

    def compute_and_publish(
        self,
        sym: str,
        df_4h,
        df_1h,
        df_ltf,
        ctx_bus,
        event_bus=None,     # опционально
    ) -> "WavePhase":

        snap = {}

        # 4h
        if df_4h is not None and len(df_4h) >= self.MIN_BARS:
            sh4 = find_swing_highs(df_4h["high"], period=self.SWING_PERIOD_4H)
            sl4 = find_swing_lows(df_4h["low"],  period=self.SWING_PERIOD_4H)
            snap["elliott_n_down"]    = calculate_n_down(sh4)
            snap["elliott_n_up"]      = calculate_n_up(sl4)
            snap["htf_tf"]            = "4h"

        # 1h
        if df_1h is not None and len(df_1h) >= self.MIN_BARS:
            sh1 = find_swing_highs(df_1h["high"], period=self.SWING_PERIOD_1H)
            sl1 = find_swing_lows(df_1h["low"],  period=self.SWING_PERIOD_1H)
            snap["elliott_n_down_1h"] = calculate_n_down(sh1)
            snap["elliott_n_up_1h"]   = calculate_n_up(sl1)

        # LTF
        if df_ltf is not None and len(df_ltf) >= self.MIN_BARS:
            shL = find_swing_highs(df_ltf["high"], period=self.SWING_PERIOD_LTF)
            slL = find_swing_lows(df_ltf["low"],   period=self.SWING_PERIOD_LTF)
            snap["elliott_n_down_ltf"] = calculate_n_down(shL)
            snap["elliott_n_up_ltf"]   = calculate_n_up(slL)

        # Определяем фазу
        phase = self._detect_phase(snap, ctx_bus.get(sym, {}))
        snap["elliott_phase"] = phase.phase
        snap["elliott_conf"]  = phase.confidence

        # Публикуем в Bus
        ctx_bus.update(sym, snap)

        # Опциональный EventBus (для подписчиков: ARCH-104 observer, PostTrade...)
        if event_bus and phase.phase != ctx_bus.get(sym, {}).get("elliott_phase"):
            event_bus.publish_nowait("wave_phase_changed", {
                "sym": sym, "phase": phase.phase, "conf": phase.confidence,
            })

        return phase

    def _detect_phase(self, snap: dict, prev_ctx: dict) -> "WavePhase":
        n_down   = snap.get("elliott_n_down", 0)
        htf_dir  = prev_ctx.get("htf_price_dir", "flat")
        has_choch = bool(prev_ctx.get("smc_snap", {}).get("choch"))
        has_div   = bool(prev_ctx.get("divergence_snap", {}).get("active"))

        # ABC коррекция
        if htf_dir == "up" and has_choch and n_down >= 3:
            return WavePhase("ABC_waveB", 0.80)

        # Волна 5 финал (divergence + глубокий тренд) — GOLD
        if htf_dir == "down" and has_div and n_down >= 3:
            return WavePhase("wave5_final", 0.75 + 0.10 * (has_choch))

        # Начало нисходящего импульса (конец коррекции)
        if htf_dir == "down" and n_down == 0:
            return WavePhase("impulse_start", 0.65)

        # Середина волны 3
        if htf_dir == "down" and 1 <= n_down <= 3 and not has_div:
            return WavePhase("wave3_mid", 0.55 + n_down * 0.05)

        # Глубокий тренд без признаков финала
        if htf_dir == "down" and n_down >= 4 and not has_div:
            return WavePhase("wave3_mid", 0.50)  # waterfall в волне 3

        return WavePhase("undefined", 0.30)
```

---

## Sub-куб 3: WT (Этап 21, vision)

### Концепция

```
Мотивация: MTFInterpreter.py сжимает 7 TF × 5 признаков = 35 чисел
           в одно число "76% медвежий" → теряем 34 из 35 признаков.
           ML обучается на сжатых данных → AUC ~0.5 (не лучше монетки).

Sub-куб даёт ML все 35 признаков:
  WT_15m: {wt1=-62, wt2=-58, zone=OS, cross=BULL, atr_trend=DOWN}
  WT_1h:  {wt1=-44, wt2=-40, zone=OS, cross=NONE, atr_trend=DOWN}
  WT_4h:  {wt1=-71, wt2=-65, zone=OS, cross=NONE, atr_trend=DOWN}
  WT_1d:  {wt1=-35, wt2=-30, zone=NORMAL, cross=NONE, atr_trend=DOWN}
  WT_1w:  {wt1=+20, wt2=+18, zone=NORMAL, cross=NONE, atr_trend=UP}
  → WTSubCube центр: REVERSAL_SETUP (confidence=0.81)
    причина: 15m+1h+4h OS + дивергенция на 4h + 1w ещё в тренде
```

### Внутренние сферы

```
WT_15m_Sphere ─┐
WT_1h_Sphere  ─┤
WT_4h_Sphere  ─┼──► MTF_WT_Verdict (центр)
WT_1d_Sphere  ─┤         ↓
WT_1w_Sphere  ─┘  TREND / REVERSAL / EXHAUSTION / UNCLEAR
                  + confidence 0.0-1.0
                  + key_tfs: list (какие TF решили)
```

### Условие реализации

```
Триггер: LIVE стабилен ≥30 дней + AUC > 0.55 + ≥5000 сделок с wt_snap
(из ROADMAP.md Этап 21.2)
Текущие данные недостаточны для ML Sub-куба: wt_snap записывается, но
MTF WT Specialist (Сфера 3) ещё не обучен на этих данных.
```

---

## Порядок реализации

```
Сейчас (prerequisite chain):

① ARCH-123 — PivotSphere формализация (1-2 дня)
     ↓ (PricePositionContext нужен PivotSphere)
② ARCH-119 — MarketRegime Reversal Mode (1-2 дня)
     ↓ (WaveService читает has_choch из Regime)
③ ARCH-121 — WaveService реализация (2-3 дня)
     ↓ (Elliott-Pivot Sub-куб = Wave + Pivot готовы)
④ Интеграция в TPSelector и SL calc (ARCH-115 пункты 2,5)

Параллельно:
⑤ ARCH-120 — SMC Sub-куб формализация (3-5 дней)
     (независим от ①②③, ждёт ≥200 smc_snap сделок для ML)

Vision (Этап 21):
⑥ WT Sub-куб — после LIVE + AUC > 0.55
⑦ CubeNode интерфейс — WaveService переходит на полный async EventBus
```

---

## Влияние на текущий поток данных

```
ДО (конвейер):
scan_loop
  → [синхронно] pre-compute elliott_snap
  → [синхронно] execute_functions читают из bot._elliott_snap

ПОСЛЕ (Sub-куб в Bus):
scan_loop
  → [синхронно] wave_service.compute_and_publish() → ctx_bus
  → [синхронно] smc_sub_cube.compute_and_publish() → ctx_bus
  → [синхронно] pivot_sphere.compute_and_publish() → ctx_bus
  → [синхронно] execute_functions читают из ctx_bus (те же данные, через Bus)

Изменение скорости: +0ms (всё в одном event loop, синхронно)
Изменение архитектуры: ✅ все данные теперь в Bus, не в bot.*_snap разброс
```

---

## Связанные документы

- [[docs/ENCYCLOPEDIA.md]] → "Sub-кубы" + "12 сфер"
- [[docs/OKO_PRESENTATION.md]] → схема Куба
- [[TASKS.md]] → ARCH-116..120
- [[DISCUSSION.md]] → 29.05.2026 ARCH-115/116
- [[obsidian/Concepts/Elliott-Wave-Fibonacci-Tools.md]] → WaveService алгоритмы
- [[obsidian/Architecture/ARCH-104-Pattern-Mining-RiskIntel/]] → связь с ARCH-104
