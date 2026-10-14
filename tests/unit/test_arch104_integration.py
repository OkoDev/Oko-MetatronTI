"""
DEV-274: End-to-end integration test для ARCH-104 production package.

Проверяет полный pipeline:
  signal flags → ARCH104Registry.find_matching → RiskIntelligence v1
  → V2MLPrediction → DecisionFusion → PatternLifecycle health check
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.confirmations.arch104_patterns import ARCH104Registry
from core.intelligence.risk_intelligence import RiskIntelligenceV1, RiskInputs
from core.intelligence.decision_fusion import DecisionFusion, V2MLPrediction
from core.intelligence.pattern_lifecycle_manager import PatternLifecycle


def run():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("=" * 70)
    print("ARCH-104 INTEGRATION TEST — END-TO-END PIPELINE")
    print("=" * 70)

    # ── Step 1: Load registry ──
    print("\n[1] Loading ARCH104Registry...")
    reg = ARCH104Registry()
    print(f"  ✅ {len(reg.patterns)} patterns loaded")
    assert len(reg.patterns) >= 10

    # ── Step 2: Simulate Live Signal ──
    print("\n[2] Simulating live bull signal...")
    active_flags = {
        # HTF context
        "bull_div_1d", "bull_fvg_4h", "wt_os_4h",  # L1_golden matches
        "wt_os_1d", "wt_os_1h",                     # L2 matches тоже
        "atr_up_4h",                                 # L3 contains
        "discount_1d", "ote_long_4h",                # L3_premium matches!
        # LTF supporting flags
        "atr_up_1h",
        "bull_ob_1h",
    }
    matches = reg.find_matching("LONG", active_flags)
    print(f"  Active flags: {len(active_flags)}")
    print(f"  Matching patterns ({len(matches)}):")
    for m in matches:
        print(f"    → {m.id} (priority={m.priority}, weight={m.weight}, baseline avgR={m.test_avgR:+.3f})")
    assert len(matches) >= 2

    # ── Step 3: Pick best match ──
    best = matches[0]
    print(f"\n[3] Best match: {best.id}")
    print(f"  Anchor: {' + '.join(best.anchor_factors)}")
    print(f"  TP strategy: {best.tp_strategy}, time_exit: {best.time_exit_hours}h")

    # ── Step 4: Risk Intelligence v1 ──
    print("\n[4] Running Risk Intelligence v1...")
    ri_v1 = RiskIntelligenceV1()
    inputs = RiskInputs(
        pattern_id=best.id,
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=0.8,
        sharpe_30d=1.5,
        n_trades_30d=80,
        regime="TREND_UP",
        btc_regime="bull",
        funding_pct_8h=0.01,
        open_positions_count=2,
        warnings_24h=0,
        pattern_stability_score=1.0,
    )
    v1_decision = ri_v1.evaluate(inputs)
    print(f"  v1: allow={v1_decision.allow_entry}, risk_pct={v1_decision.risk_pct}%, lev={v1_decision.leverage}x")
    print(f"  reasoning: {v1_decision.reasoning[:80]}...")
    assert v1_decision.allow_entry

    # ── Step 5: Simulate v2 ML prediction ──
    print("\n[5] Simulating v2 LightGBM prediction (high confidence)...")
    v2_pred = V2MLPrediction(p_win=0.85, predicted_mfe_r=4.5, confidence=0.9)

    # ── Step 6: Decision Fusion ──
    print("\n[6] Decision Fusion (v2_with_v1_safeguard)...")
    fusion = DecisionFusion(strategy="v2_with_v1_safeguard")
    fused = fusion.fuse(v1_decision, v2_pred)
    print(f"  FUSED: allow={fused.allow_entry}, risk_pct={fused.risk_pct}%, lev={fused.leverage}x")
    print(f"  strategy_used: {fused.strategy_used}")
    print(f"  reasoning: {fused.fusion_reasoning}")
    assert fused.allow_entry

    # ── Step 7: Pattern Lifecycle check ──
    print("\n[7] Pattern lifecycle health check...")
    pl = PatternLifecycle()
    health = pl.check_pattern(best.id, best.test_avgR)
    print(f"  Pattern: {health.pattern_id}")
    print(f"  Status: {health.status}")
    print(f"  Reason: {health.decision_reason}")
    print(f"  baseline_avgR: {health.baseline_avgR:.3f}")
    # status может быть insufficient_data (мало real trades), это норм

    # ── Step 8: Failure scenario ──
    print("\n[8] Failure scenario: high funding → v1 VETO...")
    bad_inputs = RiskInputs(
        pattern_id=best.id,
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=-0.5,
        sharpe_30d=0.2,
        n_trades_30d=80,
        regime="HIGH_VOL",
        btc_regime="bear",
        funding_pct_8h=0.05,
        open_positions_count=1,
        warnings_24h=2,
        pattern_stability_score=0.5,
    )
    v1_bad = ri_v1.evaluate(bad_inputs)
    fused_bad = fusion.fuse(v1_bad, v2_pred)  # v2 high p_win не помогает
    print(f"  FUSED bad: allow={fused_bad.allow_entry} (expected False)")
    print(f"  reasoning: {fused_bad.fusion_reasoning}")
    assert not fused_bad.allow_entry

    print("\n" + "=" * 70)
    print("✅ ALL INTEGRATION TESTS PASSED")
    print("=" * 70)
    print("\nPipeline ready for shadow mode (per MIGRATION_ARCH104.md Stage 1)")


if __name__ == "__main__":
    run()
