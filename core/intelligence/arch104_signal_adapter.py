"""
ARCH-104 Signal Adapter — единая точка подключения ARCH-104 в живой бот.

Pipeline integration:
  scan_one() detects signal candidate
    ↓
  ARCH104SignalAdapter.process(symbol, signal_context)
    ↓
  1. Собирает active SMC/indicator flags на текущем баре
  2. ARCH104Registry.find_matching() → matched patterns
  3. RiskIntelligenceV1.evaluate() → risk_pct/leverage
  4. (опц.) DecisionFusion с v2 LightGBM prediction
  5. PatternLifecycle.check → не shadowed ли pattern
  6. Логирует решение в risk_decisions_log
    ↓
  Returns Decision (apply / skip)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ARCH104Decision:
    """Финальное решение adapter'а — принимать или нет сигнал."""
    apply: bool
    pattern_id: Optional[str] = None
    matched_patterns: list[str] = field(default_factory=list)
    risk_pct: float = 0.0
    leverage: int = 1
    sl_price: Optional[float] = None
    time_exit_hours: int = 24
    tp_strategy: str = "no_trail"
    skip_reason: str = ""
    reasoning: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ARCH104SignalAdapter:
    """Связывает signal pipeline бота с ARCH-104 components."""

    def __init__(self,
                 db_path: str = "subscriptions.db",
                 enable_v2: bool = False,
                 enable_lifecycle_check: bool = True):
        from core.confirmations.arch104_patterns import ARCH104Registry
        from core.intelligence.risk_intelligence import RiskIntelligenceV1
        from core.intelligence.pattern_lifecycle_manager import PatternLifecycle
        from core.intelligence.decision_fusion import DecisionFusion

        self.registry = ARCH104Registry()
        self.risk_intel = RiskIntelligenceV1()
        self.lifecycle = PatternLifecycle(db_path=Path(db_path)) if enable_lifecycle_check else None
        self.fusion = DecisionFusion(strategy="v2_with_v1_safeguard", risk_intel_v1=self.risk_intel)
        self.enable_v2 = enable_v2
        self.db_path = db_path

        # Load risk_policies.yaml для kill_switches/boost_factors per pattern
        self.risk_policies = self._load_risk_policies()

        logger.info("ARCH104SignalAdapter initialized: %d patterns, %d risk policies, v2=%s",
                    len(self.registry.patterns), len(self.risk_policies), enable_v2)

    def _load_risk_policies(self) -> dict:
        """Загружает risk_policies.yaml — kill_switches и boost_factors per pattern_id."""
        try:
            import yaml
            policy_path = Path(__file__).resolve().parent.parent.parent / "config" / "risk_policies.yaml"
            if not policy_path.exists():
                return {}
            with open(policy_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("patterns", {})
        except Exception as e:
            logger.warning("Failed to load risk_policies.yaml: %s", e)
            return {}

    def _apply_kill_switches_and_boosts(self, pattern_id: str, active_flags: set[str],
                                        base_risk_pct: float) -> tuple[float, list[str], str]:
        """Применяет kill_switches и boost_factors из risk_policies.yaml.

        Returns (adjusted_risk_pct, abort_reasons, log_note).
        """
        policy = self.risk_policies.get(pattern_id)
        if not policy:
            return base_risk_pct, [], ""

        # Также проверяем policy у parent (для LTF nested)
        risk_pct = base_risk_pct
        aborts = []
        notes = []

        # Kill switches: если factor=TRUE → блокируем entry
        for ks in (policy.get("kill_switches") or []):
            factor = ks.get("factor")
            if factor and factor in active_flags:
                aborts.append(f"KILL: {factor} ({ks.get('reason','')})")

        # Boost factors: если factor=TRUE → multiplier
        for bf in (policy.get("boost_factors") or []):
            factor = bf.get("factor")
            if factor and factor in active_flags:
                bonus = bf.get("multiplier_bonus", 1.0)
                risk_pct *= bonus
                notes.append(f"BOOST {factor} ×{bonus}")

        # Penalty factors: factor=TRUE → multiplier_penalty
        for pf in (policy.get("penalty_factors") or []):
            factor = pf.get("factor")
            if factor and factor in active_flags:
                penalty = pf.get("multiplier_penalty", 1.0)
                risk_pct *= penalty
                notes.append(f"PENALTY {factor} ×{penalty}")

        # Clamp
        risk_pct = max(0.0, min(risk_pct, 3.0))   # абсолютный clamp на 3% risk

        return risk_pct, aborts, " | ".join(notes)

    def process(self,
                symbol: str,
                direction: str,
                active_flags: set[str],
                price: float,
                sl_price: float,
                context: Optional[dict] = None,
                v2_prediction=None,
                detection_tf: Optional[str] = None) -> ARCH104Decision:
        """Main entry — обрабатывает сигнал через всю ARCH-104 цепочку.

        Args:
            symbol: торговая пара
            direction: "LONG" or "SHORT"
            active_flags: set of TRUE SMC/indicator flag names
            price: текущая цена
            sl_price: уровень SL (для расчёта sl_distance_pct)
            context: optional dict с EMA avgR, Sharpe, regime, BTC regime, funding etc.
            v2_prediction: optional V2MLPrediction object (если v2 enabled)

        Returns:
            ARCH104Decision — final apply/skip + risk params
        """
        context = context or {}

        # Step 1: Match patterns (фильтр по detection_tf если указан)
        matches = self.registry.find_matching(direction, active_flags, detection_tf=detection_tf)
        if not matches:
            return ARCH104Decision(apply=False, skip_reason="no_arch104_pattern_matched")

        best = matches[0]
        all_ids = [m.id for m in matches]

        # Step 2: Pattern lifecycle check
        if self.lifecycle:
            health = self.lifecycle.check_pattern(best.id, best.test_avgR)
            if health.status == "shadow":
                return ARCH104Decision(
                    apply=False,
                    pattern_id=best.id,
                    matched_patterns=all_ids,
                    skip_reason=f"pattern_shadowed: {health.decision_reason}",
                )

        # Step 3: Risk Intelligence v1
        from core.intelligence.risk_intelligence import RiskInputs
        sl_dist_pct = abs(price - sl_price) / price * 100 if price > 0 else 0
        ri_inputs = RiskInputs(
            pattern_id=best.id,
            direction=direction,
            signal_strength=context.get("signal_strength", 70),
            sl_distance_pct=sl_dist_pct,
            ema_avg_r_30d=context.get("ema_avg_r_30d", 0.0),
            sharpe_30d=context.get("sharpe_30d", 0.0),
            n_trades_30d=context.get("n_trades_30d", 0),
            regime=context.get("regime", "UNKNOWN"),
            btc_regime=context.get("btc_regime", "UNKNOWN"),
            funding_pct_8h=context.get("funding_pct_8h", 0.0),
            open_positions_count=context.get("open_positions_count", 0),
            open_positions_same_dir_corr=context.get("correlation", 0.0),
            warnings_24h=context.get("warnings_24h", 0),
            pattern_stability_score=context.get("pattern_stability", 1.0),
        )
        v1_decision = self.risk_intel.evaluate(ri_inputs)

        # Step 4: Decision Fusion (если v2 включён)
        if self.enable_v2 and v2_prediction is not None:
            fused = self.fusion.fuse(v1_decision, v2_prediction)
            allow = fused.allow_entry
            risk_pct = fused.risk_pct
            leverage = fused.leverage
            reasoning = fused.fusion_reasoning
        else:
            allow = v1_decision.allow_entry
            risk_pct = v1_decision.risk_pct
            leverage = v1_decision.leverage
            reasoning = v1_decision.reasoning

        if not allow:
            decision = ARCH104Decision(
                apply=False,
                pattern_id=best.id,
                matched_patterns=all_ids,
                risk_pct=risk_pct,
                leverage=leverage,
                skip_reason=f"risk_intel_block: {', '.join(v1_decision.abort_reasons) or 'low_multiplier'}",
                reasoning=reasoning,
            )
        else:
            # Apply kill_switches/boost_factors из risk_policies.yaml
            adj_risk_pct, policy_aborts, policy_note = self._apply_kill_switches_and_boosts(
                best.id, active_flags, risk_pct
            )
            # Также проверяем risk_policy_ref (если paterrn ссылается на другой)
            if best.risk_policy_ref and best.risk_policy_ref != best.id:
                adj_risk_pct2, policy_aborts2, policy_note2 = self._apply_kill_switches_and_boosts(
                    best.risk_policy_ref, active_flags, adj_risk_pct
                )
                adj_risk_pct = adj_risk_pct2
                policy_aborts.extend(policy_aborts2)
                if policy_note2:
                    policy_note = (policy_note + " | " + policy_note2) if policy_note else policy_note2

            if policy_aborts:
                decision = ARCH104Decision(
                    apply=False,
                    pattern_id=best.id,
                    matched_patterns=all_ids,
                    risk_pct=adj_risk_pct,
                    leverage=leverage,
                    skip_reason=f"kill_switch: {'; '.join(policy_aborts)}",
                    reasoning=reasoning + " | " + (policy_note if policy_note else ""),
                )
            else:
                decision = ARCH104Decision(
                    apply=True,
                    pattern_id=best.id,
                    matched_patterns=all_ids,
                    risk_pct=adj_risk_pct,
                    leverage=leverage,
                    sl_price=sl_price,
                    time_exit_hours=best.time_exit_hours,
                    tp_strategy=best.tp_strategy,
                    reasoning=reasoning + (" | " + policy_note if policy_note else ""),
                )

        # Step 5: Log decision parallel to actual VST/LIVE trade
        self._log_decision(symbol, direction, decision, v1_decision, v2_prediction, active_flags)

        return decision

    def _log_decision(self, symbol, direction, decision, v1_decision, v2_pred, active_flags):
        """Логирует в БД для post-hoc analysis (D-028: VST/LIVE parallel, не shadow-only)."""
        import sqlite3
        import json

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS risk_decisions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT,
                pattern_id TEXT,
                matched_patterns TEXT,
                apply INTEGER,
                risk_pct REAL,
                leverage INTEGER,
                sl_price REAL,
                time_exit_hours INTEGER,
                tp_strategy TEXT,
                skip_reason TEXT,
                v1_allow INTEGER,
                v1_abort_reasons TEXT,
                v2_p_win REAL,
                active_flags_json TEXT,
                reasoning TEXT
            )
        """)
        cur.execute("""
            INSERT INTO risk_decisions_log (
                ts, symbol, direction, pattern_id, matched_patterns,
                apply, risk_pct, leverage, sl_price, time_exit_hours, tp_strategy,
                skip_reason, v1_allow, v1_abort_reasons, v2_p_win,
                active_flags_json, reasoning
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision.ts.isoformat(),
            symbol,
            direction,
            decision.pattern_id,
            json.dumps(decision.matched_patterns),
            1 if decision.apply else 0,
            decision.risk_pct,
            decision.leverage,
            decision.sl_price,
            decision.time_exit_hours,
            decision.tp_strategy,
            decision.skip_reason,
            1 if v1_decision.allow_entry else 0,
            json.dumps(v1_decision.abort_reasons),
            float(v2_pred.p_win) if v2_pred is not None else None,
            json.dumps(sorted(list(active_flags))),
            decision.reasoning,
        ))
        conn.commit()
        conn.close()


# ─────────── Self-test ───────────

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    adapter = ARCH104SignalAdapter(enable_v2=False)
    print(f"Loaded {len(adapter.registry.patterns)} patterns")

    # Simulate golden setup
    active_flags = {"bull_div_1d", "bull_fvg_4h", "wt_os_4h", "wt_os_1h",
                    "discount_1d", "ote_long_4h"}
    decision = adapter.process(
        symbol="BTC/USDT:USDT",
        direction="LONG",
        active_flags=active_flags,
        price=100000,
        sl_price=98000,
        context={"signal_strength": 85, "ema_avg_r_30d": 0.8,
                 "sharpe_30d": 1.5, "n_trades_30d": 80, "regime": "TREND_UP",
                 "btc_regime": "bull", "funding_pct_8h": 0.01,
                 "open_positions_count": 1, "warnings_24h": 0},
    )

    print(f"\nDecision: apply={decision.apply}")
    print(f"  pattern_id: {decision.pattern_id}")
    print(f"  matched: {decision.matched_patterns}")
    print(f"  risk_pct: {decision.risk_pct}%, lev: {decision.leverage}x")
    print(f"  time_exit: {decision.time_exit_hours}h, tp: {decision.tp_strategy}")
    print(f"  reasoning: {decision.reasoning[:100]}")

    # Test no match
    decision2 = adapter.process(
        symbol="BTC/USDT:USDT",
        direction="LONG",
        active_flags={"some_random_flag"},
        price=100000, sl_price=98000,
    )
    print(f"\nNo match scenario: apply={decision2.apply}, reason={decision2.skip_reason}")

    print("\n✅ ARCH104SignalAdapter self-test OK")
    print(f"  Records logged: see DB table risk_decisions_log")
