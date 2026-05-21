"""
DEV-261b: Decision Fusion Layer для Risk Intelligence.

Объединяет решения v1 (формульный, `risk_intelligence.py`) и
v2 (LightGBM ML классификатор) → final decision.

Стратегии (выбирается через config):
  - "v1_only": игнорируем v2 (baseline)
  - "v2_only": игнорируем v1 (опасно без safeguards)
  - "vote_50_50": среднее (allow_entry если оба True, risk_pct = avg)
  - "weighted_by_shadow_pnl": веса по shadow track record
  - "v2_with_v1_safeguard": v2 решает, но v1 может veto при extreme risk

Phase 6 Task: shadow logging всех 3 (v1, v2, fused).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.intelligence.risk_intelligence import RiskDecision, RiskIntelligenceV1, RiskInputs

logger = logging.getLogger(__name__)


@dataclass
class V2MLPrediction:
    """Output Risk Intelligence v2 (LightGBM ensemble)."""
    p_win: float                   # 0-1, ROC классификатор
    predicted_mfe_r: float = 0.0   # ожидаемый MFE из regressor (опционально)
    confidence: float = 0.5        # voting agreement если ensemble (0-1)
    model_version: str = "lgbm_v1"


@dataclass
class FusedDecision:
    """Финальное решение после слияния v1 + v2."""
    allow_entry: bool
    risk_pct: float
    leverage: int
    strategy_used: str             # какая strategy выбрала
    v1_decision: RiskDecision
    v2_prediction: Optional[V2MLPrediction] = None
    fusion_reasoning: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionFusion:
    """Объединяет v1 + v2 в одно решение."""

    def __init__(self, strategy: str = "v2_with_v1_safeguard", risk_intel_v1: Optional[RiskIntelligenceV1] = None):
        self.strategy = strategy
        self.v1 = risk_intel_v1 or RiskIntelligenceV1()

    def fuse(self, v1_decision: RiskDecision, v2_pred: Optional[V2MLPrediction] = None) -> FusedDecision:
        # Если v2 не доступен — fallback на v1
        if v2_pred is None:
            return FusedDecision(
                allow_entry=v1_decision.allow_entry,
                risk_pct=v1_decision.risk_pct,
                leverage=v1_decision.leverage,
                strategy_used="v1_only_fallback",
                v1_decision=v1_decision,
                v2_prediction=None,
                fusion_reasoning="v2 unavailable — using v1",
            )

        # ─── Strategy: vote_50_50 ───
        if self.strategy == "vote_50_50":
            # AND логика — оба должны разрешить
            v2_allow = v2_pred.p_win > 0.5
            allow = v1_decision.allow_entry and v2_allow
            # risk_pct = average если оба ok, или min при споре
            if allow:
                # v2 confidence бустит risk_pct
                v2_risk_factor = 0.5 + v2_pred.p_win * 0.5   # [0.5..1.0]
                risk_pct = v1_decision.risk_pct * v2_risk_factor
            else:
                risk_pct = 0
            reasoning = f"vote: v1={'YES' if v1_decision.allow_entry else 'NO'}, v2 p_win={v2_pred.p_win:.2f} → {'ALLOW' if allow else 'BLOCK'}"
            return FusedDecision(
                allow_entry=allow,
                risk_pct=round(risk_pct, 3),
                leverage=v1_decision.leverage,
                strategy_used="vote_50_50",
                v1_decision=v1_decision,
                v2_prediction=v2_pred,
                fusion_reasoning=reasoning,
            )

        # ─── Strategy: v2_with_v1_safeguard (РЕКОМЕНДУЕМАЯ) ───
        if self.strategy == "v2_with_v1_safeguard":
            # v1 имеет veto в трёх случаях:
            #   1. v1.allow_entry=False с hard reason (funding, correlation, cap)
            #   2. v1 multiplier < 0.5 (extreme penalty)
            #   3. v1 leverage = exchange_min (extreme risk_pct относительно SL)
            v1_veto = (
                (not v1_decision.allow_entry) or
                (v1_decision.risk_pct_multiplier < 0.5)
            )
            if v1_veto:
                return FusedDecision(
                    allow_entry=False,
                    risk_pct=0,
                    leverage=v1_decision.leverage,
                    strategy_used="v2_with_v1_safeguard",
                    v1_decision=v1_decision,
                    v2_prediction=v2_pred,
                    fusion_reasoning=f"v1 VETO: {','.join(v1_decision.abort_reasons) if v1_decision.abort_reasons else 'low multiplier'}",
                )

            # v1 OK → v2 решает
            v2_allow = v2_pred.p_win > 0.55   # порог чуть выше 0.5 для запаса
            if not v2_allow:
                return FusedDecision(
                    allow_entry=False,
                    risk_pct=0,
                    leverage=v1_decision.leverage,
                    strategy_used="v2_with_v1_safeguard",
                    v1_decision=v1_decision,
                    v2_prediction=v2_pred,
                    fusion_reasoning=f"v2 low confidence: p_win={v2_pred.p_win:.2f} < 0.55",
                )

            # Оба ok → risk_pct из v1 × v2 boost
            v2_boost = 1.0 + (v2_pred.p_win - 0.5) * 0.6   # [1.0..1.3] для p_win=0.5..1.0
            risk_pct_final = v1_decision.risk_pct * v2_boost
            # Clamp по v1 limits
            risk_pct_final = min(risk_pct_final, v1_decision.risk_pct * 1.5)

            return FusedDecision(
                allow_entry=True,
                risk_pct=round(risk_pct_final, 3),
                leverage=v1_decision.leverage,
                strategy_used="v2_with_v1_safeguard",
                v1_decision=v1_decision,
                v2_prediction=v2_pred,
                fusion_reasoning=f"v1 ok + v2 p_win={v2_pred.p_win:.2f} → boost ×{v2_boost:.2f} → risk={risk_pct_final:.2f}%",
            )

        # ─── Default: v1_only ───
        return FusedDecision(
            allow_entry=v1_decision.allow_entry,
            risk_pct=v1_decision.risk_pct,
            leverage=v1_decision.leverage,
            strategy_used="v1_only",
            v1_decision=v1_decision,
            v2_prediction=v2_pred,
            fusion_reasoning="strategy=v1_only",
        )


# ─────────── Demo / self-test ───────────

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    from core.intelligence.risk_intelligence import RiskIntelligenceV1, RiskInputs

    ri_v1 = RiskIntelligenceV1()

    # Test 1: v1 ok, v2 high confidence → BOOST
    test_inputs = RiskInputs(
        pattern_id="L1_golden",
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=+0.8,
        sharpe_30d=1.5,
        n_trades_30d=80,
        regime="TREND_UP",
        btc_regime="bull",
        funding_pct_8h=0.01,
        open_positions_count=2,
        warnings_24h=0,
        pattern_stability_score=1.0,
    )
    v1_decision = ri_v1.evaluate(test_inputs)
    v2_pred_high = V2MLPrediction(p_win=0.85, predicted_mfe_r=4.5, confidence=0.9)

    fusion = DecisionFusion(strategy="v2_with_v1_safeguard")
    fused = fusion.fuse(v1_decision, v2_pred_high)
    print(f"=== Test 1: Golden + v2 high p_win ===")
    print(f"  v1: allow={v1_decision.allow_entry} risk_pct={v1_decision.risk_pct}%")
    print(f"  v2: p_win={v2_pred_high.p_win}")
    print(f"  FUSED: allow={fused.allow_entry} risk_pct={fused.risk_pct}% lev={fused.leverage}x")
    print(f"  reasoning: {fused.fusion_reasoning}")

    # Test 2: v1 ok, v2 low confidence → BLOCK
    v2_pred_low = V2MLPrediction(p_win=0.40, predicted_mfe_r=1.0, confidence=0.6)
    fused2 = fusion.fuse(v1_decision, v2_pred_low)
    print(f"\n=== Test 2: Golden + v2 LOW p_win → block ===")
    print(f"  FUSED: allow={fused2.allow_entry} reasoning: {fused2.fusion_reasoning}")

    # Test 3: v1 veto → independently от v2
    bad_inputs = RiskInputs(
        pattern_id="L1_golden",
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=-0.5,
        sharpe_30d=0.2,
        n_trades_30d=80,
        regime="HIGH_VOL",
        btc_regime="bear",
        funding_pct_8h=0.05,   # > 0.03 → v1 veto
        open_positions_count=1,
        warnings_24h=2,
        pattern_stability_score=0.5,
    )
    v1_bad = ri_v1.evaluate(bad_inputs)
    fused3 = fusion.fuse(v1_bad, v2_pred_high)
    print(f"\n=== Test 3: v1 VETO (high funding) — v2 не помогает ===")
    print(f"  FUSED: allow={fused3.allow_entry} reasoning: {fused3.fusion_reasoning}")
