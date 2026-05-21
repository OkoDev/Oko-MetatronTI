# MIGRATION_ARCH104 — VST → LIVE Migration Plan

> Production migration plan для Phase 7 ARCH-104.
> **D-028 (2026-05-20):** Shadow Mode НЕ НУЖЕН — у нас уже VST на BingX = реальная execution с виртуальными деньгами. Сразу из VST → LIVE.

## Pre-Conditions (должны быть True перед стартом)

- [ ] Phase 0-7 завершены (см. [[ARCH-104]] phase docs) ✅
- [ ] Patterns в Confirmation Registry соответствуют `config/arch104_patterns.yaml` (11 patterns) ✅
- [ ] Risk Intelligence v1 validated (E2E test ALL PASSED) ✅
- [ ] Rolling WF подтвердил устойчивость (94/100 stable, 87 robust 6/6) ✅
- [ ] Backups: БД, models, configs

## Stage 1 — VST Observation (Week 1-2)

**Цель:** валидировать новые ARCH-104 patterns на VST против исторических ожиданий.

- [ ] Запустить бот с `EXECUTION_MODE=vst` (текущий режим)
- [ ] Включить в Confirmation Registry **11 ARCH-104 patterns** из `config/arch104_patterns.yaml`
- [ ] Risk Intelligence v1 в LIVE inference (формула применяется на каждое решение)
- [ ] Risk Intelligence v2 в logging mode (LightGBM считает прогноз, но не блокирует)
- [ ] Decision Fusion = `v1_only` (пока v2 collects data)
- [ ] `risk_decisions_log` table пишет каждое решение для post-hoc анализа

### Мониторинг VST Week 1-2:

- [ ] Daily review каждое утро:
  - [ ] Сравнить shadow predictions vs actual VST trade outcomes
  - [ ] avgR на VST vs backtest expectations (target: |Δ| ≤ 20%)
  - [ ] WR на VST vs backtest expectations
  - [ ] No production errors (orphan orders, missing stops)
- [ ] Если ARCH-104 паттерны на VST показывают avgR < 50% baseline → investigate before live
- [ ] Если 3+ consecutive losing days на VST → пауза для investigate

**Acceptance for Stage 2:**
- ≥20 VST trades по новым ARCH-104 patterns
- avgR within [0.5×baseline, 1.5×baseline]
- 0 critical production errors

## Stage 2 — LIVE 10% капитала (Week 3)

- [ ] Переключить `EXECUTION_MODE=live`
- [ ] Capital allocation: 10% от total
- [ ] `risk_pct_max_clamp = 0.5` (половина от обычного)
- [ ] Risk Intelligence v1 LIVE
- [ ] v2 продолжает в shadow logging
- [ ] Decision Fusion = `v1_only`
- [ ] **Critical monitoring:**
  - [ ] Order execution matches VST timing
  - [ ] Real slippage ≤ 0.05% (vs assumed 0.03%)
  - [ ] Funding charges within expected
- [ ] Daily PnL comparison: VST decisions vs LIVE execution
- [ ] **Auto-rollback** if DD > 3% за week

## Stage 3 — LIVE 30% капитала (Week 4-5)

- [ ] `risk_pct_max_clamp = 1.0` (full base)
- [ ] **Включить v2 в Decision Fusion** (`v2_with_v1_safeguard`)
- [ ] v2 порог: `p_win > 0.55`
- [ ] Watch для регрессий v1+v2 vs v1 only
- [ ] Если v2 ROC-AUC деградирует → fallback v1 only

## Stage 4 — LIVE 50% капитала (Week 6-7)

- [ ] `risk_pct_max_clamp = 1.5`
- [ ] Включить **все anti-pattern kill-switches** из `config/risk_policies.yaml`
- [ ] Включить **boost factors** (×1.2)
- [ ] Activate `PatternLifecycle` auto-retire monitoring (DEV-275)

## Stage 5 — LIVE 100% (Week 8-9)

- [ ] Full capital
- [ ] `risk_pct_max_clamp = 2.0`
- [ ] **Все ARCH-104 production systems active:**
  - [ ] 11 patterns в Confirmation Registry
  - [ ] Risk Intelligence v1 + v2 + Decision Fusion
  - [ ] Anti-pattern kill-switches
  - [ ] Boost factors
  - [ ] Regime-aware exit (no_trail TREND, trail_after_1R RANGE)
  - [ ] Pattern auto-retire monitoring
- [ ] Daily review continues 1 week после full ramp
- [ ] Если DD > 8% за week → rollback в Stage 3

## Kill-Switches (auto-rollback во ВСЕХ stages)

| Trigger | Action |
|---------|--------|
| 3 consecutive losing days | Revert to previous stage |
| Rolling-7d Sharpe < -1.0 | Revert + investigate |
| BTC flash crash ≥-15% за 4h | Halt all entries 6h |
| Pattern avgR_30d < 0.5 × baseline | Auto-shadow pattern (DEV-275) |
| Funding spike > 0.1%/8h | Block new entries until normalized |
| VST vs LIVE PnL diverge > 30% | Stop LIVE, investigate execution |

## Rollback Procedure (≤30 минут)

1. Stop bot: остановить процесс `oko_mtf`
2. Set `EXECUTION_MODE=vst` обратно
3. Revert `config/arch104_patterns.yaml` к предыдущему commit
4. Restart bot — продолжает в VST режиме
5. Investigate в logs + `risk_decisions_log` table
6. Resume previous stage когда issue resolved

## Real-Time Monitoring

- Web dashboard: `http://localhost:8000` — extended ARCH-104 panels:
  - Per-pattern PnL heatmap
  - Per-pair attribution
  - v1 vs v2 disagreement rate
  - Risk_pct distribution
  - Drawdown curve
  - Active patterns count (auto-retire status)
- TG alerts:
  - 3 losing days → notify
  - DD > 5% week → notify
  - Pattern fired для важных setups (priority=1) → notify

## Multi-TF Scaling Implementation Notes (D-026)

При активации **L1_golden_5m + L1_golden_15m + L1_golden_1h + L1_golden_4h** одновременно на одной паре:
- **Per-pair max concurrent = 4** позиции на pattern family
- Each TF получает independent `risk_pct` (через RI v1+v2 per pattern)
- Total exposure per pair ≤ 4% (1% × 4 TF)
- Total leverage per pair ≤ 20× (clamp от per-TF leverage)
- В Position Sizer: учитывать уже открытые positions same direction

## Mass-Concurrent Считать Опасным (D-027)

С 500 паттернами concurrent на пару может быть 185 triggers — **НЕ применять без cap**:
- Per-pair max concurrent positions = 4 (тоже как Multi-TF)
- При срабатывании >4 patterns на пару — выбираем TOP-4 по weight×confidence
- Pareto filter: торгуем только TOP-20 пар (несут 80% R)
- Black-list low-performing пар (JUPUSDT, NEARUSDT, WIFUSDT по результатам)

## Documentation Updates Post-Migration

После каждого Stage:
- [ ] Update [[ARCH-104-Pattern-Library]] статус patterns: 🟡 → 🟢
- [ ] Update [[ARCH-104-Decisions-Log]] с реальными performance
- [ ] Update [[ARCH-104-FINAL-Production-Package]] с production metrics
- [ ] Weekly review in DISCUSSION.md
