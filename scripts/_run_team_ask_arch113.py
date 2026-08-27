"""Запуск team_ask для ARCH-113 TPSelector расширение слоёв."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

# Патчим sys.argv чтобы передать вопрос в team_ask.py
question = """ARCH-113: TPSelector — расширение 4 слоёв "Магнитной зоны" для TP.

КОНТЕКСТ ПРОЕКТА:
Торговый бот BingX, крипто, 15m-4h. Стратегии: confluence, wt_b, pivot_reversal, ARCH-104 patterns (OTE, FVG+div+OS combo). 45 пар, 2.4 года исторических данных.

ТЕКУЩАЯ ПРОБЛЕМА TP:
- fixed_rr: WR=24.4% avgR=-0.44 (ХУДШИЙ)
- pivot_1D: WR=26.7% avgR=-0.31 (много, плохо)
- atr_rr_3.0: WR=40.1% avgR=-0.14 (лучше, но всё равно -avgR)
Нужно: TP = ближайшая "Магнитная зона" с максимальной гравитацией (сумма весов источников в +/-0.5% кластере)

ТЕКУЩИЕ 4 СЛОЯ TP МАГНИТА:

СЛОЙ 1 — FVG midpoints (незаполненные дисбалансы)
  bear_fvg_4h.mid  -> weight=3  (LONG TP: gap выше цены = магнит заполнения)
  bear_fvg_1h.mid  -> weight=2
  bear_fvg_15m.mid -> weight=1
  bull_fvg_4h.mid  -> weight=3  (SHORT TP: gap ниже цены)
  bull_fvg_1h.mid  -> weight=2
Данные: 4h Bear FVG mid достигается в 50% случаев (n=2646 BTC), 1h в 59%.
Combinator 2+TF FVG: avgR=0.238 WR=48.3% (vs no FVG: avgR=0.119 WR=44.2%)

СЛОЙ 2 — Пивоты (горизонтальные уровни реакции)
  pivot_R1/R2_1D -> weight=2/1
  pivot_R1_1W    -> weight=3
  PP_1D          -> weight=2 (зона баланса)
  pivot_S1/S2 для SHORT аналогично
  Future pivots 1D/1W/1M (live H/L/C -> PP/S/R) — данные есть, enabled=False

СЛОЙ 3 — OTE Fibonacci Extensions (проекции импульса)
  Если вход через OTE zone (0.705-0.79 Fib retracement от swing A->B):
  ext_100  (=swing_B, 100% impulse)  -> weight=2
  ext_1618 (161.8% extension)        -> weight=3 (золотое сечение)
  ext_2618 (261.8%)                  -> weight=1
  Минусовые: -1/-1.618/-2.618/-3.618 от entry = цели за swing high

СЛОЙ 4 — Ликвидность
  swing_high_recent    -> weight=2 (стопы лонгов = liquidity pool)
  equal_highs (EQH)   -> weight=3 (двойной max = double top = pool)
  OB_bear.bottom       -> weight=2 (противоположный Order Block)
  eqh_sweep_target     -> weight=3

ДОСТУПНЫЕ ДАННЫЕ В СИСТЕМЕ (уже вычисляются):
  WT: wt1/wt2, zone OS/OB/N, divergence bull/bear/hidden, trendup/trenddown/tsl_line
  Pivot: PP/S1-S5/R1-R5 (1D/1W/1M), future pivots live
  SMC: FVG bull/bear (15m/1h/4h), Order Block bull/bear, BOS/CHoCH, OTE 0.705-0.79
  ATR: atr14, atr_slow, volatility ratio, tsl_line
  MTF: wt1/wt2 на 1h/4h, btc_4h_regime, EMA200 (1h/4h/1d), EMA50 (1d)
  Regime: TREND_UP/DOWN/RANGE/SIDEWAYS
  RSI: rsi на 1h/4h/1d (cross50 уже в combinator флагах)
  Confirmations: 25 типов с весами (zone_OS, smc_choch, div_cascade и др.)
  EQL/EQH sweep: smc_eql_swept, smc_eqh_swept уже есть

ИСТОРИЧЕСКИЕ ДАННЫЕ:
  data/history/: 5m/15m/1h, 45 пар, 2024-01 до 2026-05 (.parquet)
  data/research/combinator_v2_results.csv: 22835 паттернов n/avgR/WR/stdR/score
  Флаги в combinator: above/below_ema200, ote_long/short, discount/premium, vol_spike,
    eql_sweep/eqh_sweep, rsi_cross50, atr_cross_up/down, pivot_above/below_PP, BOS/CHoCH

ВОПРОС:
Для каждого из 4 слоёв предложите ВСЕ возможные расширения — дополнительные источники уровней которые можно добавить как TP магниты. Также предложите НОВЫЕ слои (5, 6, 7+) которых нет в текущей архитектуре.

Для каждого предложения укажите:
1. Конкретный уровень/цена — как вычислить из доступных данных
2. Теоретическое обоснование — почему цена туда идёт (институциональная логика / SMC / Wyckoff / TA)
3. Вес в gravity scoring (1-5)
4. Реалистичность: A=уже есть данные / B=нужно добавить источник / C=сложно/внешние API

Охватите ВСЕ подходы:
- Volume Profile: POC, VAH/VAL, HVN/LVN
- Camarilla/Woodie/DeMark пивоты
- Психологические уровни (round numbers: X.000, X.500, X.X00)
- Wyckoff: Supply/Demand zones, Spring/Upthrust targets, PSY/AR/ST levels
- Межрыночный: BTC dominance levels, USDT.D levels, корреляционные зоны
- Momentum exhaustion: RSI divergence target, WT overbought/oversold zones как TP
- Funding rate: extreme funding = mean-reversion target
- Open Interest: OI clusters, liquidation zones
- Сезонные пивоты: начало недели/месяца/квартала как магниты
- VWAP и anchored VWAP от ключевых событий
- Fractal highs/lows на 1D/1W как уровни
- Previous Day/Week/Month High/Low (PDH/PDL, PWH/PWL, PMH/PML)"""

sys.argv = [
    "team_ask.py",
    question,
    "--no-context",  # вопрос уже содержит весь контекст
]

import team_ask
import sys as _sys
_sys.exit(team_ask.main())
